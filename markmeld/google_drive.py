"""
Google Drive Processor - Unified class for processing Google Drive files

This module provides a single interface for:
- Downloading and cleaning Google Docs as markdown
- Processing SVG files and converting them to PDFs
"""

import frontmatter
import io
import logging
import os
import re
import subprocess
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List
from functools import wraps
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Import utility functions from utilities module
from .utilities import (
    sanitize_filename,
    write_to_file,
    clean_markdown,
    clean_escape_characters,
    remove_embedded_images,
    strip_bold_from_headings,
    replace_svg_extensions
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def handle_drive_errors(func):
    """Decorator for common Google Drive API error handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            raise
    return wrapper


class GoogleDriveProcessor:
    """
    Processor for Google Drive documents and SVG files.
    
    Provides functionality for:
    - Downloading Google Docs and converting them to clean markdown
    - Processing SVG files from Google Drive and converting them to PDFs
    - In-memory caching of Google Docs to avoid redundant downloads
    """
    
    def __init__(self, 
                 credentials_path: Optional[str] = None,
                 local_base_dir: str = "fig",
                 scopes: Optional[List[str]] = None,
                 save_to_disk: bool = True):
        """
        Initialize the Google Drive Processor.
        
        Args:
            credentials_path: Path to the service account credentials JSON file
            local_base_dir: Base directory for all local output
            scopes: List of Google API scopes
            save_to_disk: Whether to save downloaded documents to disk
        """
        # Set defaults
        if credentials_path is None:
            credentials_path = "/home/nsheff/auth/shefflab-google-service-acct-credentials.json"
        if scopes is None:
            scopes = ['https://www.googleapis.com/auth/drive.readonly']
        
        # Store initialization parameters
        self.credentials_path = credentials_path
        self.scopes = scopes
        self.local_base_dir = Path(local_base_dir)
        self.save_to_disk = save_to_disk
        
        # Initialize credentials and service
        self.credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
        
        # Get service account email
        try:
            self.service_account_email = self.credentials.service_account_email
        except:
            self.service_account_email = "unknown"
        
        # SVG processing configuration
        self.inkscape_command = "inkscape"
        
        # Initialize document cache
        self._doc_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0
    
    # ====================
    # Properties with lazy directory creation
    # ====================
    
    @property
    def docs_dir(self) -> Path:
        """Get docs directory, creating it if needed."""
        docs_dir = self.local_base_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        return docs_dir
    
    @property
    def pdf_dir(self) -> Path:
        """Get PDF directory, creating it if needed."""
        pdf_dir = self.local_base_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        return pdf_dir
    
    @property
    def digest_dir(self) -> Path:
        """Get digest directory, creating it if needed."""
        digest_dir = self.local_base_dir / "digest"
        digest_dir.mkdir(parents=True, exist_ok=True)
        return digest_dir
    
    # ====================
    # Core Download and Processing
    # ====================
    
    @handle_drive_errors
    def download_file(self, file_id: str, destination_path: str):
        """Download any file from Google Drive to local path."""
        request = self.drive_service.files().get_media(fileId=file_id)
        
        with io.FileIO(destination_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
    
    @handle_drive_errors
    def get_metadata(self, file_id: str) -> Dict[str, Any]:
        """Get metadata about any Google Drive file."""
        file_metadata = self.drive_service.files().get(
            fileId=file_id,
            fields='id, name, mimeType, size, modifiedTime, createdTime, owners, md5Checksum, parents'
        ).execute()
        return file_metadata
    
    def download_doc(self,
                     doc_id: str,
                     clean: bool = True,
                     output_path: Optional[Union[str, Path]] = None,
                     parse_frontmatter: bool = True,
                     update_figure_paths: bool = True,
                     folder_id: Optional[str] = None) -> Any:
        """
        Download a Google Doc and optionally clean it and save to disk.
        
        Args:
            doc_id: The ID of the Google Doc to download
            clean: Whether to apply all cleaning operations (default: True)
            output_path: Optional path to save the markdown file
            parse_frontmatter: Whether to parse frontmatter (default: True)
            update_figure_paths: Whether to update SVG paths to converted PDFs (default: True)
            folder_id: Optional folder ID to search for figures (if not provided, uses doc's parent)
            
        Returns:
            If parse_frontmatter is True: frontmatter.Post object
            If parse_frontmatter is False: cleaned markdown string
        """
        # Download the markdown (cleaned by default if clean=True)
        markdown_content = self._download_raw_markdown(doc_id, apply_cleaning=clean)
        
        # Note: Cleaning is now done during caching in _download_raw_markdown
        
        # Update figure paths if requested
        if update_figure_paths:
            markdown_content = self._update_document_figure_paths(markdown_content, doc_id, folder_id)
        
        # Save to additional custom path if provided
        if output_path:
            write_to_file(markdown_content, output_path)
            logger.info(f"Also saved to: {output_path}")
        
        # Parse or return raw
        if parse_frontmatter:
            return frontmatter.loads(markdown_content)
        else:
            return markdown_content
    
    def _download_raw_markdown(self, doc_id: str, skip_disk_save: bool = False, apply_cleaning: bool = True) -> str:
        """
        Internal method to download markdown from Google Drive.
        Includes in-memory and disk caching support.
        Now caches cleaned content by default instead of raw content.
        """
        # Check in-memory cache first
        if self._is_doc_cached(doc_id):
            self._cache_hits += 1
            logger.info(f"Memory cache hit for document {doc_id}")
            # Don't save to disk when retrieving from memory cache
            return self._doc_cache[doc_id]['content']
        
        # Check disk cache if enabled
        disk_content = self._load_from_disk(doc_id)
        if disk_content is not None:
            # Add to memory cache for faster subsequent access
            metadata = self.get_metadata(doc_id)
            self._doc_cache[doc_id] = {
                'content': disk_content,
                'metadata': {
                    'modifiedTime': metadata.get('modifiedTime'),
                    'md5Checksum': metadata.get('md5Checksum'),
                },
                'cached_at': datetime.now(),
                'loaded_from_disk': True
            }
            return disk_content
        
        # Cache miss - download the document
        self._cache_misses += 1
        logger.info(f"Cache miss for document {doc_id} - downloading from Google Drive...")
        
        # Check for active changes before downloading
        self._check_for_active_changes(doc_id)
        
        # Export the document as markdown
        request = self.drive_service.files().export_media(
            fileId=doc_id,
            mimeType='text/markdown'
        )
        
        # Download the file into memory
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        done = False
        
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info(f"Download {int(status.progress() * 100)}%.")
        
        # Get the markdown content as string
        file_content.seek(0)
        content = file_content.read().decode('utf-8')
        
        # Handle auto-added document title
        content = self._remove_auto_title(content, doc_id)
        
        # Apply cleaning before caching if requested (default is True)
        if apply_cleaning:
            content = clean_markdown(content)
            logger.info(f"Applied cleaning to document {doc_id} before caching")
        
        # Cache the document (now cleaned by default)
        metadata = self.get_metadata(doc_id)
        self._doc_cache[doc_id] = {
            'content': content,
            'metadata': {
                'modifiedTime': metadata.get('modifiedTime'),
                'md5Checksum': metadata.get('md5Checksum'),
            },
            'cached_at': datetime.now(),
            'loaded_from_disk': False
        }
        
        # Save to disk if enabled
        if not skip_disk_save and self.save_to_disk:
            self._save_to_disk(doc_id, content, is_cleaned=apply_cleaning)
        
        return content
    
    def _remove_auto_title(self, content: str, doc_id: str) -> str:
        """Remove auto-added document title if present."""
        lines = content.split('\n') if content else []
        if len(lines) >= 2 and lines[0].startswith('# '):
            if lines[1].strip() in ['---', '']:
                metadata = self.get_metadata(doc_id)
                doc_title = metadata.get('name', '')
                first_line_title = lines[0][2:].strip()
                
                if first_line_title == doc_title:
                    logger.info(f"Removing auto-added title: '{first_line_title}'")
                    if lines[1].strip() == '---':
                        logger.info("Frontmatter block detected")
                    content = '\n'.join(lines[1:])
                    if content.startswith('\n'):
                        content = content[1:]
        elif content.strip().startswith('---'):
            logger.info("Frontmatter block detected")
        
        return content
    
    def _is_doc_cached(self, doc_id: str) -> bool:
        """Check if document is in cache and still valid."""
        if doc_id not in self._doc_cache:
            return False
        
        # Get current metadata
        current_metadata = self.get_metadata(doc_id)
        cached_metadata = self._doc_cache[doc_id]['metadata']
        
        # Compare modified time (primary check)
        if current_metadata.get('modifiedTime') != cached_metadata.get('modifiedTime'):
            return False
        
        # If md5 available, use as secondary validation
        if 'md5Checksum' in current_metadata and 'md5Checksum' in cached_metadata:
            if current_metadata['md5Checksum'] != cached_metadata['md5Checksum']:
                return False
        
        return True
    
    def _check_for_active_changes(self, doc_id: str):
        """
        Check if a document has active changes/suggestions and warn the user.
        
        This uses the Google Drive API's revisions endpoint to check if the document
        has unpublished changes that might not be reflected in the exported content.
        """
        try:
            # Get document metadata first
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            
            # Try to get revision information
            # Note: The revisions API may require additional permissions
            try:
                revisions = self.drive_service.revisions().list(
                    fileId=doc_id,
                    fields='revisions(id,modifiedTime,published,keepForever)',
                    pageSize=10
                ).execute()
                
                revisions_list = revisions.get('revisions', [])
                
                # Check if the latest revision is unpublished (has active changes)
                if revisions_list:
                    latest_revision = revisions_list[-1]
                    if not latest_revision.get('published', True):
                        logger.warning("")
                        logger.warning("=" * 70)
                        logger.warning("⚠️  WARNING: DOCUMENT HAS ACTIVE CHANGES")
                        logger.warning("=" * 70)
                        logger.warning(f"Document: {doc_name}")
                        logger.warning("")
                        logger.warning("This document appears to have unpublished changes or active")
                        logger.warning("suggestions that may not be included in the exported version.")
                        logger.warning("")
                        logger.warning("You are building a production PDF from a document with active")
                        logger.warning("changes, which is probably not what you want.")
                        logger.warning("")
                        logger.warning("Please review and accept/reject all changes in Google Docs")
                        logger.warning("before generating the final output.")
                        logger.warning("=" * 70)
                        logger.warning("")
                        
            except Exception as rev_error:
                # Revisions API might fail due to permissions or API limitations
                # In this case, try alternative approach using comments/suggestions
                try:
                    # Check for active comments which might indicate ongoing review
                    comments = self.drive_service.comments().list(
                        fileId=doc_id,
                        fields='comments(resolved)',
                        includeDeleted=False
                    ).execute()
                    
                    unresolved_comments = [c for c in comments.get('comments', []) 
                                         if not c.get('resolved', False)]
                    
                    if unresolved_comments:
                        logger.warning("")
                        logger.warning("=" * 70)
                        logger.warning("⚠️  WARNING: DOCUMENT HAS UNRESOLVED COMMENTS")
                        logger.warning("=" * 70)
                        logger.warning(f"Document: {doc_name}")
                        logger.warning(f"Unresolved comments: {len(unresolved_comments)}")
                        logger.warning("")
                        logger.warning("This document has unresolved comments which may indicate")
                        logger.warning("ongoing review or required changes.")
                        logger.warning("")
                        logger.warning("Consider resolving all comments before generating")
                        logger.warning("the final output.")
                        logger.warning("=" * 70)
                        logger.warning("")
                        
                except:
                    # Comments API also failed, skip the check silently
                    pass
                    
        except Exception as e:
            # Don't fail the download if the check fails, just log a debug message
            logger.debug(f"Could not check for active changes: {e}")
    
    # ====================
    # Cache Management
    # ====================
    
    def clear_cache(self, doc_id: Optional[str] = None):
        """Clear the document cache."""
        if doc_id:
            self._doc_cache.pop(doc_id, None)
            logger.info(f"Cleared cache for document {doc_id}")
        else:
            self._doc_cache.clear()
            logger.info("Cleared entire document cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'size': len(self._doc_cache),
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'hit_rate': self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            'cached_docs': list(self._doc_cache.keys())
        }
    
    def preload_cache(self, doc_ids: List[str]):
        """Preload multiple documents into cache."""
        logger.info(f"Preloading {len(doc_ids)} documents into cache...")
        for doc_id in doc_ids:
            try:
                self._download_raw_markdown(doc_id)
                logger.info(f"  Preloaded: {doc_id}")
            except Exception as e:
                logger.error(f"  Failed to preload {doc_id}: {e}")
    
    # ====================
    # Disk Cache Operations
    # ====================
    
    def _get_doc_filename(self, doc_id: str) -> str:
        """Generate a filename for saving a document to disk."""
        try:
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            safe_name = sanitize_filename(doc_name)
        except:
            safe_name = doc_id
        
        if not safe_name.endswith('.md'):
            safe_name += '.md'
        
        return safe_name
    
    def _get_doc_path(self, doc_id: str) -> Path:
        """Get the full path where a document would be saved on disk."""
        return self.docs_dir / self._get_doc_filename(doc_id)
    
    def _load_from_disk(self, doc_id: str) -> Optional[str]:
        """Try to load a document from disk cache."""
        if not self.save_to_disk:
            return None
        
        doc_path = self._get_doc_path(doc_id)
        if doc_path.exists():
            try:
                content = doc_path.read_text(encoding='utf-8')
                
                # Check if Google Drive version is newer
                try:
                    metadata = self.get_metadata(doc_id)
                    google_modified = metadata.get('modifiedTime', '')
                    
                    # Check if file has our metadata comment
                    if content.startswith("<!-- gdrive-modified:") and google_modified:
                        first_line = content.split('\n')[0]
                        if f"gdrive-modified: {google_modified}" in first_line:
                            logger.info(f"Loading from disk cache: {doc_path}")
                            # Remove the metadata comment before returning
                            lines = content.split('\n')
                            if lines[0].startswith("<!-- gdrive-modified:"):
                                content = '\n'.join(lines[1:])
                                if content.startswith('\n'):
                                    content = content[1:]
                            return content
                except:
                    pass
                
                # If we can't verify, return None to trigger re-download
                return None
                
            except Exception as e:
                logger.error(f"Error loading from disk cache: {e}")
        
        return None
    
    def _save_to_disk(self, doc_id: str, content: str, is_cleaned: bool = False):
        """Save document content to disk with metadata for cache validation."""
        if not self.save_to_disk:
            return
        
        doc_path = self._get_doc_path(doc_id)
        try:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Add metadata comment for cache validation
            try:
                metadata = self.get_metadata(doc_id)
                modified_time = metadata.get('modifiedTime', '')
                cleaned_flag = "cleaned" if is_cleaned else "raw"
                if modified_time:
                    content_with_meta = f"<!-- gdrive-modified: {modified_time} gdrive-state: {cleaned_flag} -->\n{content}"
                else:
                    content_with_meta = content
            except:
                content_with_meta = content
            
            doc_path.write_text(content_with_meta, encoding='utf-8')
            logger.info(f"Saved to disk: {doc_path}")
        except Exception as e:
            logger.error(f"Error saving to disk: {e}")
    
    # ====================
    # SVG Processing
    # ====================
    
    def process_svg_folder(self, folder_id: str, skip_unchanged: bool = True) -> Dict[str, Any]:
        """Process all SVG files in a Google Drive folder, converting to local PDFs."""
        logger.info(f"Processing SVG files from Google Drive folder: {folder_id}")
        logger.info(f"PDFs will be saved to: {self.pdf_dir}")
        
        # List SVG files from Drive
        svg_files = self.list_svg_files(folder_id)
        
        results = {
            'processed': [],
            'skipped': [],
            'failed': [],
            'stats': {
                'total_svgs': len(svg_files),
                'converted': 0,
                'skipped': 0,
                'failed': 0
            }
        }
        
        for svg_file in svg_files:
            file_id = svg_file['id']
            file_name = svg_file['name']
            remote_digest = svg_file.get('md5Checksum', '')
            
            logger.info(f"Processing: {file_name}")
            
            try:
                # Check if unchanged
                if skip_unchanged:
                    local_digest = self.load_local_digest(file_name)
                    
                    if local_digest == remote_digest and local_digest:
                        pdf_name = os.path.splitext(file_name)[0] + '.pdf'
                        pdf_path = self.pdf_dir / pdf_name
                        logger.info(f"  Skipping (unchanged): {file_name} -> {pdf_path}")
                        results['skipped'].append(file_name)
                        results['stats']['skipped'] += 1
                        continue
                
                # Download SVG to temp location
                svg_path = Path(tempfile.mktemp(suffix='.svg'))
                self.download_file(file_id, str(svg_path))
                
                try:
                    # Convert to PDF
                    pdf_name = os.path.splitext(file_name)[0] + '.pdf'
                    pdf_path = self.pdf_dir / pdf_name
                    
                    success, error_msg = self.convert_svg_to_pdf(str(svg_path), str(pdf_path))
                    
                    if success:
                        # Save digest
                        if skip_unchanged:
                            self.save_local_digest(file_name, remote_digest)
                        
                        logger.info(f"  Converted: {file_name} -> {pdf_path}")
                        results['processed'].append(file_name)
                        results['stats']['converted'] += 1
                    else:
                        logger.error(f"  Failed to convert: {file_name}")
                        logger.error(f"    Error: {error_msg}")
                        results['failed'].append({
                            'file': file_name,
                            'error': error_msg
                        })
                        results['stats']['failed'] += 1
                finally:
                    # Clean up SVG file
                    if svg_path.exists():
                        svg_path.unlink()
                        
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"  Error processing {file_name}: {error_msg}")
                results['failed'].append({
                    'file': file_name,
                    'error': error_msg
                })
                results['stats']['failed'] += 1
        
        return results
    
    def list_svg_files(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all SVG files in a Google Drive folder."""
        svg_files = []
        page_token = None
        
        while True:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='image/svg+xml' and trashed=false",
                fields="nextPageToken, files(id, name, md5Checksum, modifiedTime)",
                pageToken=page_token
            ).execute()
            
            svg_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        return svg_files
    
    def convert_svg_to_pdf(self, svg_path: str, pdf_path: str) -> tuple[bool, str]:
        """Convert SVG to PDF using Inkscape."""
        try:
            # Check if input file exists
            if not os.path.exists(svg_path):
                error_msg = f"Input SVG file does not exist: {svg_path}"
                return False, error_msg
            
            # Run Inkscape conversion
            cmd = [
                self.inkscape_command,
                "--batch-process",
                "--export-type=pdf",
                f"--export-filename={pdf_path}",
                svg_path
            ]
            
            logger.info(f"  Running: {' '.join(cmd)}")
            
            # Set environment to avoid X11/DBus issues
            env = os.environ.copy()
            env['DISPLAY'] = ''
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )
            
            # Check return code and if PDF was created
            if result.returncode != 0:
                error_msg = f"Inkscape returned non-zero exit code {result.returncode}. Error: {result.stderr.strip() if result.stderr else result.stdout.strip()}"
                return False, error_msg
            
            if not os.path.exists(pdf_path):
                error_msg = f"PDF file was not created at {pdf_path}. Output: {result.stderr.strip() if result.stderr else result.stdout.strip()}"
                return False, error_msg
            
            return True, ""
            
        except subprocess.TimeoutExpired:
            return False, "Inkscape conversion timed out after 60 seconds"
        except FileNotFoundError:
            return False, f"Inkscape not found: '{self.inkscape_command}'"
        except Exception as e:
            return False, f"Unexpected error: {type(e).__name__}: {str(e)}"
    
    # ====================
    # Digest Management (path-based only)
    # ====================
    
    def load_local_digest(self, file_identifier: str) -> Optional[str]:
        """
        Load stored digest from local filesystem.
        Automatically handles path structure based on whether file_identifier contains paths.
        """
        # Create digest path that mirrors the original structure
        digest_path = Path(file_identifier).with_suffix('.digest')
        digest_file = self.digest_dir / digest_path
        
        if digest_file.exists():
            try:
                return digest_file.read_text().strip()
            except Exception as e:
                logger.error(f"Error reading digest file {digest_file}: {str(e)}")
                return None
        
        return None
    
    def save_local_digest(self, file_identifier: str, digest: str):
        """
        Save digest to local filesystem.
        Automatically handles path structure based on whether file_identifier contains paths.
        """
        # Create digest path that mirrors the original structure
        digest_path = Path(file_identifier).with_suffix('.digest')
        digest_file = self.digest_dir / digest_path
        
        try:
            # Create parent directories if needed
            digest_file.parent.mkdir(parents=True, exist_ok=True)
            digest_file.write_text(digest)
        except Exception as e:
            logger.error(f"Error saving digest file {digest_file}: {str(e)}")
    
    # ====================
    # Document-Driven Figure Processing
    # ====================
    
    def extract_figure_paths(self, markdown_content: str) -> List[str]:
        """Extract all figure paths from markdown content."""
        # Find markdown images: ![alt](path)
        inline_pattern = r'!\[[^\]]*\]\(([^)]+)\)'
        
        # Find reference-style images: [ref]: path
        ref_pattern = r'^\[[^\]]+\]:\s*(.+)$'
        
        paths = []
        paths.extend(re.findall(inline_pattern, markdown_content))
        paths.extend(re.findall(ref_pattern, markdown_content, re.MULTILINE))
        
        # Filter out URLs and data URIs, keep only local paths
        local_paths = [p for p in paths if not p.startswith(('http://', 'https://', 'data:'))]
        
        # Remove duplicates while preserving order
        seen = set()
        unique_paths = []
        for path in local_paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        
        return unique_paths
    
    def extract_csv_paths(self, markdown_content: str) -> List[str]:
        """Extract all CSV file paths from markdown content using {csv/...} syntax."""
        # Pattern to match {csv/path/to/file.csv} syntax
        csv_pattern = r'\{(csv/[^}]+\.csv)\}'
        
        paths = re.findall(csv_pattern, markdown_content)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_paths = []
        for path in paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        
        return unique_paths
    
    def find_file_in_drive(self, file_path: str, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find a file by path in Google Drive folder."""
        filename = Path(file_path).name
        
        try:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and name='{filename}' and trashed=false",
                fields="files(id, name, mimeType)"
            ).execute()
            
            files = response.get('files', [])
            return files[0] if files else None
        except Exception as e:
            logger.error(f"Error searching for file {filename}: {e}")
            return None
    
    def process_document_figures(self, doc_id: str, folder_id: Optional[str] = None, 
                                skip_unchanged: bool = True) -> Dict[str, Any]:
        """Process only figures referenced in the document."""
        logger.info(f"Processing figures for document: {doc_id}")
        
        # Download and read the document (with cleaning to remove embedded images)
        doc_content = self.download_doc(doc_id, clean=True, parse_frontmatter=False, update_figure_paths=False)
        
        # Extract figure paths
        figure_paths = self.extract_figure_paths(doc_content)
        logger.info(f"Found {len(figure_paths)} figure references in document")
        
        # If no folder_id provided, try to find the parent folder of the document
        if not folder_id:
            try:
                doc_metadata = self.get_metadata(doc_id)
                parents = doc_metadata.get('parents', [])
                if parents:
                    folder_id = parents[0]
                    logger.info(f"Using document's parent folder: {folder_id}")
                else:
                    logger.warning("No parent folder found for document")
            except Exception as e:
                logger.error(f"Error getting document parent folder: {e}")
        
        # Optimize API calls by pre-fetching file metadata for all referenced folders
        folder_file_cache = self._batch_fetch_folder_metadata(figure_paths, folder_id)
        
        # Process each figure path
        results = {'processed': [], 'skipped': [], 'failed': [], 'mapping': {}}
        
        # Create converted directory structure
        converted_dir = Path('converted')
        converted_dir.mkdir(parents=True, exist_ok=True)
        
        for fig_path in figure_paths:
            logger.info(f"Processing: {fig_path}")
            
            # Check if it's a PDF file
            is_pdf = fig_path.endswith('.pdf')
            is_svg = fig_path.endswith('.svg')
            
            # Skip if neither SVG nor PDF
            if not is_svg and not is_pdf:
                logger.info(f"  Skipping unsupported file type: {fig_path}")
                continue
            
            # Try to find the file in the cached metadata
            file_info = None
            if folder_id:
                file_info = self._find_file_in_cache(fig_path, folder_file_cache)
            
            if not file_info:
                logger.error(f"  Failed: File not found in Google Drive")
                results['failed'].append(fig_path)
                continue
            
            # Get digest from cached metadata (no additional API call needed!)
            remote_digest = file_info.get('md5Checksum', '')
            
            # Create output path structure
            if is_svg:
                # For SVG files, create path in converted directory with .pdf extension
                pdf_path = fig_path.replace('.svg', '.pdf')
                output_path = converted_dir / pdf_path
            else:
                # For PDF files, mirror the original path structure
                output_path = Path(fig_path)
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if we should skip unchanged files
            if skip_unchanged and remote_digest:
                local_digest = self.load_local_digest(fig_path)
                if local_digest == remote_digest and output_path.exists():
                    logger.info(f"  Skipping (unchanged): {fig_path}")
                    results['skipped'].append(fig_path)
                    results['mapping'][fig_path] = str(output_path)
                    continue
            
            # Download and process
            try:
                if is_svg:
                    # For SVG: download to a local temp file in the output directory
                    # This ensures we have write access and avoids Docker /tmp issues
                    temp_dir = output_path.parent
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Create a unique temp filename in the local directory
                    temp_svg = temp_dir / f".temp_{Path(fig_path).stem}_{os.getpid()}.svg"
                    
                    self.download_file(file_info['id'], str(temp_svg))
                    
                    # Convert to PDF
                    success, error_msg = self.convert_svg_to_pdf(str(temp_svg), str(output_path))
                    
                    # Clean up temp file
                    if temp_svg.exists():
                        temp_svg.unlink()
                    
                    if success:
                        logger.info(f"  Converted: {fig_path} -> {output_path}")
                        results['processed'].append(fig_path)
                        results['mapping'][fig_path] = str(output_path)
                        
                        # Save digest
                        if skip_unchanged and remote_digest:
                            self.save_local_digest(fig_path, remote_digest)
                    else:
                        logger.error(f"  Failed to convert: {error_msg}")
                        results['failed'].append(fig_path)
                else:
                    # For PDF: download directly to target location
                    self.download_file(file_info['id'], str(output_path))
                    logger.info(f"  Downloaded: {fig_path} -> {output_path}")
                    results['processed'].append(fig_path)
                    # No path mapping needed for PDFs - they keep the same path
                    
                    # Save digest
                    if skip_unchanged and remote_digest:
                        self.save_local_digest(fig_path, remote_digest)
                    
            except Exception as e:
                logger.error(f"  Error processing {fig_path}: {str(e)[:200]}")
                results['failed'].append(fig_path)
        
        # Update document with new paths (this replaces .svg with converted .pdf paths)
        updated_content = self._update_figure_paths(doc_content, results['mapping'])
        
        # Summary
        logger.info(f"\n=== Figure Processing Complete ===")
        logger.info(f"✓ Processed: {len(results['processed'])} figures")
        logger.info(f"⏭ Skipped: {len(results['skipped'])} unchanged figures")
        logger.info(f"✗ Failed: {len(results['failed'])} figures")
        
        return {
            'document': updated_content,
            'results': results
        }
    
    def process_document_csvs(self, doc_id: str, folder_id: Optional[str] = None,
                             skip_unchanged: bool = True) -> Dict[str, Any]:
        """Process CSV files referenced in the document."""
        logger.info(f"Processing CSV files for document: {doc_id}")
        
        # Download and read the document
        doc_content = self.download_doc(doc_id, clean=False, parse_frontmatter=False, 
                                       update_figure_paths=False)
        
        # Extract CSV paths
        csv_paths = self.extract_csv_paths(doc_content)
        logger.info(f"Found {len(csv_paths)} CSV file references in document")
        
        if not csv_paths:
            logger.info("No CSV files to process")
            return {'csvs': [], 'results': {'processed': [], 'skipped': [], 'failed': []}}
        
        # If no folder_id provided, try to find the parent folder of the document
        if not folder_id:
            try:
                doc_metadata = self.get_metadata(doc_id)
                parents = doc_metadata.get('parents', [])
                if parents:
                    folder_id = parents[0]
                    logger.info(f"Using document's parent folder: {folder_id}")
                else:
                    logger.warning("No parent folder found for document")
            except Exception as e:
                logger.error(f"Error getting document parent folder: {e}")
        
        # Batch fetch metadata
        folder_cache = self._batch_fetch_folder_metadata([], folder_id, csv_paths=csv_paths)
        
        # Process CSVs
        results = self._process_csv_files(csv_paths, folder_cache, skip_unchanged)
        
        # Summary
        logger.info(f"\n=== CSV Processing Complete ===")
        logger.info(f"✓ Processed: {len(results['processed'])} CSV files")
        logger.info(f"⏭ Skipped: {len(results['skipped'])} unchanged CSV files")
        logger.info(f"✗ Failed: {len(results['failed'])} CSV files")
        
        return {
            'csvs': csv_paths,
            'results': results
        }
    
    def _process_csv_files(self, csv_paths: List[str], folder_file_cache: Dict, 
                          skip_unchanged: bool = True) -> Dict[str, Any]:
        """Process CSV files referenced in the document."""
        results = {'processed': [], 'skipped': [], 'failed': []}
        
        for csv_path in csv_paths:
            logger.info(f"Processing CSV: {csv_path}")
            
            # Find file in cache
            file_info = self._find_file_in_cache(csv_path, folder_file_cache)
            
            if not file_info:
                logger.error(f"  Failed: CSV file not found in Google Drive")
                results['failed'].append(csv_path)
                continue
            
            # Create local path structure
            local_path = Path(csv_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if unchanged (using digest)
            remote_digest = file_info.get('md5Checksum', '')
            if skip_unchanged and remote_digest:
                local_digest = self.load_local_digest(csv_path)
                if local_digest == remote_digest and local_path.exists():
                    logger.info(f"  Skipping (unchanged): {csv_path}")
                    results['skipped'].append(csv_path)
                    continue
            
            # Download CSV file
            try:
                self.download_file(file_info['id'], str(local_path))
                logger.info(f"  Downloaded: {csv_path}")
                results['processed'].append(csv_path)
                
                # Save digest for future cache checks
                if skip_unchanged and remote_digest:
                    self.save_local_digest(csv_path, remote_digest)
                    
            except Exception as e:
                logger.error(f"  Error downloading {csv_path}: {str(e)}")
                results['failed'].append(csv_path)
        
        return results
    
    def download_document_csvs(self, doc_id: str, folder_id: Optional[str] = None,
                              skip_unchanged: bool = True) -> Dict[str, Any]:
        """
        Download all CSV files referenced in a document.
        
        Args:
            doc_id: The ID of the Google Doc to process
            folder_id: Optional folder ID to search for CSV files (if not provided, uses doc's parent)
            skip_unchanged: Whether to skip files that haven't changed (based on MD5 checksum)
            
        Returns:
            Dictionary with 'csvs' list and 'results' containing processing outcome
        """
        # This is an alias for process_document_csvs for consistency with naming conventions
        return self.process_document_csvs(doc_id, folder_id, skip_unchanged)
    
    def _batch_fetch_folder_metadata(self, figure_paths: List[str], parent_folder_id: str, 
                                     csv_paths: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Pre-fetch metadata for all files in the folders referenced by figure and CSV paths.
        This minimizes API calls by fetching all files in each folder once.
        
        Args:
            figure_paths: List of figure paths to fetch metadata for
            parent_folder_id: The parent folder ID to search in
            csv_paths: Optional list of CSV paths to fetch metadata for
            
        Returns:
            Dictionary mapping folder_path -> {filename -> file_info}
        """
        # Combine all paths to identify unique folders
        all_paths = figure_paths + (csv_paths or [])
        
        folders_to_fetch = set()
        folders_to_fetch.add('')  # Root folder
        
        for path in all_paths:
            path_parts = Path(path).parts
            if len(path_parts) > 1:
                # Add the subfolder (e.g., 'fig' from 'fig/image.svg' or 'csv' from 'csv/data.csv')
                folders_to_fetch.add(path_parts[0])
        
        logger.info(f"Pre-fetching metadata for {len(folders_to_fetch)} folder(s): {folders_to_fetch}")
        
        folder_cache = {}
        
        for folder_name in folders_to_fetch:
            if folder_name == '':
                # Root folder
                target_folder_id = parent_folder_id
                cache_key = ''
            else:
                # Find subfolder ID
                subfolder_id = self._find_subfolder_by_name(parent_folder_id, folder_name)
                if not subfolder_id:
                    logger.warning(f"Subfolder '{folder_name}' not found")
                    continue
                target_folder_id = subfolder_id
                cache_key = folder_name
            
            # List all files in this folder
            files_in_folder = self._list_all_files_in_folder(target_folder_id)
            
            # Create a mapping of filename -> file_info
            file_map = {}
            for file_info in files_in_folder:
                file_map[file_info['name']] = file_info
            
            folder_cache[cache_key] = file_map
            logger.info(f"  Cached {len(file_map)} files from folder '{folder_name or 'root'}'")
        
        return folder_cache
    
    def _list_all_files_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all files (not folders) in a Google Drive folder."""
        files = []
        page_token = None
        
        while True:
            try:
                response = self.drive_service.files().list(
                    q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)",
                    pageToken=page_token,
                    pageSize=1000  # Max page size for efficiency
                ).execute()
                
                files.extend(response.get('files', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            except Exception as e:
                logger.error(f"Error listing files in folder {folder_id}: {e}")
                break
        
        return files
    
    def _find_file_in_cache(self, file_path: str, folder_cache: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find a file in the pre-fetched folder cache."""
        path_parts = Path(file_path).parts
        
        # Determine which folder to look in
        if len(path_parts) == 1:
            # File is in root
            folder_key = ''
            filename = path_parts[0]
        else:
            # File is in a subfolder
            folder_key = path_parts[0]
            filename = path_parts[-1]  # Just the filename
        
        # Look up in cache
        if folder_key in folder_cache:
            return folder_cache[folder_key].get(filename)
        
        return None
    
    def _find_file_in_folder_hierarchy(self, file_path: str, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find a file in folder hierarchy, checking subfolders if needed."""
        # First try in the main folder
        file_info = self.find_file_in_drive(file_path, folder_id)
        
        # If not found and path has subdirectories, try searching in subfolders
        if not file_info and '/' in file_path:
            path_parts = Path(file_path).parts
            if len(path_parts) > 1:
                subfolder_name = path_parts[0]
                subfolder_id = self._find_subfolder_by_name(folder_id, subfolder_name)
                if subfolder_id:
                    logger.info(f"  Searching in subfolder: {subfolder_name}")
                    file_info = self.find_file_in_drive(file_path, subfolder_id)
        
        return file_info
    
    def _find_subfolder_by_name(self, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
        """Find a subfolder by name within a parent folder."""
        try:
            response = self.drive_service.files().list(
                q=f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' "
                  f"and name='{subfolder_name}' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            folders = response.get('files', [])
            return folders[0]['id'] if folders else None
        except Exception as e:
            logger.error(f"Error searching for subfolder {subfolder_name}: {e}")
            return None
    
    def _update_figure_paths(self, markdown_content: str, path_mapping: Dict[str, str]) -> str:
        """Replace figure paths in document with converted paths."""
        updated = markdown_content
        
        for old_path, new_path in path_mapping.items():
            # Replace in both inline and reference style images
            updated = updated.replace(f']({old_path})', f']({new_path})')
            updated = updated.replace(f']: {old_path}', f']: {new_path}')
            updated = updated.replace(f']:{old_path}', f']:{new_path}')
        
        return updated
    
    def _create_figure_path_mapping(self, figure_paths: List[str]) -> Dict[str, str]:
        """
        Create a mapping of figure paths for SVG to PDF conversions.
        This just creates the mapping without doing any actual processing.
        
        Args:
            figure_paths: List of figure paths extracted from the document
            
        Returns:
            Dictionary mapping original paths to converted paths
        """
        mapping = {}
        converted_dir = Path('converted')
        
        for fig_path in figure_paths:
            # Only map SVG files to their PDF equivalents
            if fig_path.endswith('.svg'):
                pdf_path = fig_path.replace('.svg', '.pdf')
                output_path = converted_dir / pdf_path
                mapping[fig_path] = str(output_path)
        
        return mapping
    
    def _update_document_figure_paths(self, markdown_content: str, doc_id: str, 
                                     folder_id: Optional[str] = None) -> str:
        """
        Update figure paths in document content to point to converted PDFs.
        This is a lighter-weight version that just updates paths without processing files.
        
        Args:
            markdown_content: The markdown content to update
            doc_id: The document ID (used to find parent folder if needed)
            folder_id: Optional folder ID where figures are located
            
        Returns:
            Updated markdown content with figure paths replaced
        """
        # Extract figure paths from the document
        figure_paths = self.extract_figure_paths(markdown_content)
        
        if not figure_paths:
            return markdown_content
        
        # If no folder_id provided, try to find the parent folder of the document
        if not folder_id:
            try:
                doc_metadata = self.get_metadata(doc_id)
                parents = doc_metadata.get('parents', [])
                if parents:
                    folder_id = parents[0]
            except Exception as e:
                logger.debug(f"Could not get parent folder for doc {doc_id}: {e}")
        
        # Create the path mapping
        path_mapping = self._create_figure_path_mapping(figure_paths)
        
        # Update the content with the new paths
        if path_mapping:
            return self._update_figure_paths(markdown_content, path_mapping)
        
        return markdown_content
    
    def process_document_assets(self, doc_id: str, folder_id: Optional[str] = None,
                                skip_unchanged: bool = True) -> Dict[str, Any]:
        """
        Process all assets (figures and CSV files) referenced in a document.
        
        This is a wrapper function that handles both:
        - Figure processing (SVG to PDF conversion, PDF downloads)
        - CSV file downloads
        
        Args:
            doc_id: The ID of the Google Doc to process
            folder_id: Optional folder ID to search for assets (if not provided, uses doc's parent)
            skip_unchanged: Whether to skip files that haven't changed (based on MD5 checksum)
            
        Returns:
            Dictionary containing results from both figure and CSV processing:
            {
                'document': The updated document content with figure paths replaced,
                'figures': Results from figure processing,
                'csvs': Results from CSV processing,
                'summary': Overall summary statistics
            }
        """
        logger.info(f"Processing all assets for document: {doc_id}")
        
        # Get folder ID if not provided
        if not folder_id:
            try:
                doc_metadata = self.get_metadata(doc_id)
                parents = doc_metadata.get('parents', [])
                if parents:
                    folder_id = parents[0]
                    logger.info(f"Using document's parent folder: {folder_id}")
                else:
                    logger.warning("No parent folder found for document")
            except Exception as e:
                logger.error(f"Error getting document parent folder: {e}")
        
        results = {
            'document': None,
            'figures': None,
            'csvs': None,
            'summary': {
                'total_figures': 0,
                'figures_processed': 0,
                'figures_skipped': 0,
                'figures_failed': 0,
                'total_csvs': 0,
                'csvs_processed': 0,
                'csvs_skipped': 0,
                'csvs_failed': 0
            }
        }
        
        # Process figures
        logger.info("\n=== Processing Figures ===")
        try:
            figure_results = self.process_document_figures(doc_id, folder_id, skip_unchanged)
            results['figures'] = figure_results['results']
            results['document'] = figure_results['document']
            
            # Update summary
            results['summary']['total_figures'] = len(figure_results['results'].get('processed', [])) + \
                                                  len(figure_results['results'].get('skipped', [])) + \
                                                  len(figure_results['results'].get('failed', []))
            results['summary']['figures_processed'] = len(figure_results['results'].get('processed', []))
            results['summary']['figures_skipped'] = len(figure_results['results'].get('skipped', []))
            results['summary']['figures_failed'] = len(figure_results['results'].get('failed', []))
            
        except Exception as e:
            logger.error(f"Error processing figures: {e}")
            results['figures'] = {'error': str(e)}
        
        # Process CSV files
        logger.info("\n=== Processing CSV Files ===")
        try:
            csv_results = self.process_document_csvs(doc_id, folder_id, skip_unchanged)
            results['csvs'] = csv_results['results']
            
            # Update summary
            results['summary']['total_csvs'] = len(csv_results.get('csvs', []))
            results['summary']['csvs_processed'] = len(csv_results['results'].get('processed', []))
            results['summary']['csvs_skipped'] = len(csv_results['results'].get('skipped', []))
            results['summary']['csvs_failed'] = len(csv_results['results'].get('failed', []))
            
        except Exception as e:
            logger.error(f"Error processing CSV files: {e}")
            results['csvs'] = {'error': str(e)}
        
        # Print summary
        logger.info("\n" + "=" * 50)
        logger.info("ASSET PROCESSING COMPLETE")
        logger.info("=" * 50)
        
        if results['summary']['total_figures'] > 0:
            logger.info(f"📊 Figures:")
            logger.info(f"   ✓ Processed: {results['summary']['figures_processed']}")
            logger.info(f"   ⏭ Skipped: {results['summary']['figures_skipped']}")
            logger.info(f"   ✗ Failed: {results['summary']['figures_failed']}")
            logger.info(f"   Total: {results['summary']['total_figures']}")
        
        if results['summary']['total_csvs'] > 0:
            logger.info(f"📁 CSV Files:")
            logger.info(f"   ✓ Downloaded: {results['summary']['csvs_processed']}")
            logger.info(f"   ⏭ Skipped: {results['summary']['csvs_skipped']}")
            logger.info(f"   ✗ Failed: {results['summary']['csvs_failed']}")
            logger.info(f"   Total: {results['summary']['total_csvs']}")
        
        if results['summary']['total_figures'] == 0 and results['summary']['total_csvs'] == 0:
            logger.info("No assets found to process.")
        
        logger.info("=" * 50)
        
        return results
    
    # ====================
    # Unified Folder Processing
    # ====================
    
    def process_drive_folder(self, 
                            folder_id: str,
                            process_doc: bool = True,
                            process_figs: bool = True,
                            output_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """Process a Google Drive folder containing a manuscript and figures."""
        results = {
            'document': None,
            'document_id': None,
            'document_name': None,
            'figs_results': None,
            'figs_folder_id': None,
            'errors': []
        }
        
        # Process document if requested
        if process_doc:
            try:
                doc_info = self._find_manuscript_in_folder(folder_id)
                if doc_info:
                    logger.info(f"Found manuscript: {doc_info['name']} (ID: {doc_info['id']})")
                    results['document_id'] = doc_info['id']
                    results['document_name'] = doc_info['name']
                    
                    # Download and clean the document
                    results['document'] = self.download_doc(
                        doc_info['id'],
                        clean=True,
                        output_path=output_path,
                        parse_frontmatter=True
                    )
                    logger.info(f"Successfully processed manuscript: {doc_info['name']}")
                else:
                    error_msg = "Could not find manuscript document"
                    results['errors'].append(error_msg)
                    logger.warning(f"Warning: {error_msg}")
            except Exception as e:
                error_msg = f"Error processing document: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(f"Error: {error_msg}")
        
        # Process figures if requested
        if process_figs:
            try:
                figs_folder_id = self._find_figs_folder(folder_id)
                if figs_folder_id:
                    logger.info(f"Found figs folder (ID: {figs_folder_id})")
                    results['figs_folder_id'] = figs_folder_id
                    results['figs_results'] = self.process_svg_folder(figs_folder_id)
                    
                    stats = results['figs_results'].get('stats', {})
                    logger.info(f"Processed figures: {stats.get('converted', 0)} converted, "
                              f"{stats.get('skipped', 0)} skipped, {stats.get('failed', 0)} failed")
                else:
                    error_msg = "Could not find figs subfolder"
                    results['errors'].append(error_msg)
                    logger.warning(f"Warning: {error_msg}")
            except Exception as e:
                error_msg = f"Error processing figures: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(f"Error: {error_msg}")
        
        # Summary
        logger.info("\n=== Processing Complete ===")
        if results['document_name']:
            logger.info(f"✓ Document: {results['document_name']}")
        if results['figs_results']:
            stats = results['figs_results'].get('stats', {})
            logger.info(f"✓ Figures: {stats.get('total_svgs', 0)} SVGs processed")
        if results['errors']:
            logger.info(f"⚠ Errors encountered: {len(results['errors'])}")
            for error in results['errors']:
                logger.info(f"  - {error}")
        
        return results
    
    def _find_manuscript_in_folder(self, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find the manuscript document in a Google Drive folder."""
        # List all Google Docs in the folder
        docs = self._list_documents_in_folder(folder_id)
        
        # First try to find actual documents
        if docs:
            # If only one doc, use it
            if len(docs) == 1:
                return docs[0]
            
            # Look for one with 'manuscript' in the name
            manuscript_docs = [doc for doc in docs if 'manuscript' in doc['name'].lower()]
            
            if len(manuscript_docs) == 1:
                return manuscript_docs[0]
            elif len(manuscript_docs) > 1:
                logger.warning(f"Found {len(manuscript_docs)} documents with 'manuscript' in name, using: {manuscript_docs[0]['name']}")
                return manuscript_docs[0]
            else:
                logger.warning(f"Found {len(docs)} documents but none with 'manuscript' in the name")
                return None
        
        # No actual documents found, look for shortcuts
        return self._find_manuscript_shortcut(folder_id)
    
    def _list_documents_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all Google Docs in a folder."""
        docs = []
        page_token = None
        
        while True:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token
            ).execute()
            
            docs.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        return docs
    
    def _find_manuscript_shortcut(self, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find shortcuts to Google Docs in a folder."""
        logger.info("No Google Docs found in folder, looking for shortcuts/links...")
        shortcuts = []
        page_token = None
        
        while True:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.shortcut' and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, shortcutDetails)",
                pageToken=page_token
            ).execute()
            
            shortcuts.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        if not shortcuts:
            return None
        
        # Filter shortcuts that point to Google Docs
        doc_shortcuts = []
        for shortcut in shortcuts:
            shortcut_details = shortcut.get('shortcutDetails', {})
            target_mime = shortcut_details.get('targetMimeType', '')
            if target_mime == 'application/vnd.google-apps.document':
                shortcut['targetId'] = shortcut_details.get('targetId')
                doc_shortcuts.append(shortcut)
        
        if not doc_shortcuts:
            logger.info("No shortcuts to Google Docs found")
            return None
        
        # If only one doc shortcut, use it
        if len(doc_shortcuts) == 1:
            logger.info(f"Found shortcut to document: {doc_shortcuts[0]['name']}")
            return {
                'id': doc_shortcuts[0]['targetId'],
                'name': doc_shortcuts[0]['name'].replace('.gdoc', ''),
                'mimeType': 'application/vnd.google-apps.document'
            }
        
        # Look for one with 'manuscript' in the name
        manuscript_shortcuts = [s for s in doc_shortcuts if 'manuscript' in s['name'].lower()]
        
        if manuscript_shortcuts:
            logger.info(f"Found shortcut with 'manuscript' in name: {manuscript_shortcuts[0]['name']}")
            return {
                'id': manuscript_shortcuts[0]['targetId'],
                'name': manuscript_shortcuts[0]['name'].replace('.gdoc', ''),
                'mimeType': 'application/vnd.google-apps.document'
            }
        
        logger.warning(f"Found {len(doc_shortcuts)} document shortcuts but none with 'manuscript' in the name")
        return None
    
    def _find_figs_folder(self, folder_id: str) -> Optional[str]:
        """Find the figures subfolder in a Google Drive folder."""
        # List all subfolders
        folders = []
        page_token = None
        
        while True:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token
            ).execute()
            
            folders.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        if not folders:
            return None
        
        # If only one folder, use it
        if len(folders) == 1:
            logger.info(f"Using subfolder: {folders[0]['name']}")
            return folders[0]['id']
        
        # Look for one named 'figs'
        figs_folders = [f for f in folders if f['name'].lower() == 'figs']
        
        if figs_folders:
            return figs_folders[0]['id']
        else:
            logger.warning(f"Found {len(folders)} subfolders but none named 'figs'")
            return None

