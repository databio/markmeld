"""
Google Drive Processor - Unified class for processing Google Drive files

This module provides a single interface for:
- Downloading and cleaning Google Docs as markdown
- Processing SVG files and converting them to PDFs
"""

import os
import subprocess
import tempfile
import io
import re
import frontmatter
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


class GoogleDriveProcessor:
    """
    Unified processor for Google Drive documents and SVG files.
    
    This class combines functionality for:
    - Downloading Google Docs and converting them to clean markdown
    - Processing SVG files from Google Drive and converting them to PDFs
    - In-memory caching of Google Docs to avoid redundant downloads
    
    The document cache automatically tracks document modifications using
    modifiedTime and md5Checksum metadata, only re-downloading when
    documents have changed on Google Drive.
    """
    
    def __init__(self, 
                 credentials_path: Optional[str] = None,
                 local_base_dir: str = "fig",
                 scopes: Optional[List[str]] = None,
                 save_to_disk: bool = True):
        """
        Initialize the Google Drive Processor.
        
        Args:
            credentials_path: Path to the service account credentials JSON file.
                            If not provided, looks for default credentials.
            local_base_dir: Base directory for all local output (docs, pdfs, digests)
            scopes: List of Google API scopes. Auto-determined if not provided.
            save_to_disk: Whether to save downloaded documents to disk (default: True).
                         When True, documents are saved to the docs directory and
                         can be reused across sessions.
        """
        # Set default credentials path
        if credentials_path is None:
            credentials_path = "/home/nsheff/auth/shefflab-google-service-acct-credentials.json"
        
        # Set default scopes (read-only for safety)
        if scopes is None:
            scopes = ['https://www.googleapis.com/auth/drive.readonly']
        
        # Store initialization parameters
        self.credentials_path = credentials_path
        self.scopes = scopes
        self.local_base_dir = Path(local_base_dir)
        self.save_to_disk = save_to_disk
        
        # Set up directory structure
        self.docs_dir = self.local_base_dir / "docs"
        self.pdf_dir = self.local_base_dir / "pdf"
        self.digest_dir = self.local_base_dir / "digest"
        
        # Create directories
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.digest_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize credentials and service
        self.credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
        
        # Get service account email for display
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
    # Common Properties
    # ====================
    
    @property
    def is_ready(self) -> bool:
        """Check if the processor is properly initialized and ready to use."""
        return self.drive_service is not None and self.credentials is not None
    
    def __repr__(self) -> str:
        """Return a detailed string representation of the processor instance."""
        creds_file = Path(self.credentials_path).name
        creds_dir = Path(self.credentials_path).parent.name
        
        return (
            f"GoogleDriveProcessor(\n"
            f"  service_account={self.service_account_email!r},\n"
            f"  credentials='{creds_dir}/{creds_file}',\n"
            f"  scopes={len(self.scopes)} scope(s),\n"
            f"  local_base_dir='{self.local_base_dir}',\n"
            f"  ready={self.is_ready}\n"
            f")"
        )
    
    def __str__(self) -> str:
        """Return a simple string representation of the processor instance."""
        return f"GoogleDriveProcessor(account={self.service_account_email}, base_dir={self.local_base_dir})"
    
    def _is_doc_cached(self, doc_id: str) -> bool:
        """
        Check if document is in cache and still valid.
        
        Args:
            doc_id: The ID of the Google Doc
            
        Returns:
            True if document is cached and unchanged, False otherwise
        """
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
    
    def info(self) -> Dict[str, Any]:
        """
        Get information about the processor configuration.
        
        Returns:
            Dictionary with configuration details
        """
        return {
            'service_account': self.service_account_email,
            'credentials_path': str(self.credentials_path),
            'scopes': self.scopes,
            'ready': self.is_ready,
            'directories': {
                'base': str(self.local_base_dir.absolute()),
                'docs': str(self.docs_dir.absolute()),
                'pdf': str(self.pdf_dir.absolute()),
                'digest': str(self.digest_dir.absolute())
            },
            'capabilities': [
                'download_docs',
                'clean_markdown',
                'process_svgs',
                'convert_to_pdf'
            ]
        }
    
    # ====================
    # Shared Utilities
    # ====================
    
    def download_file(self, file_id: str, destination_path: str):
        """
        Download any file from Google Drive to local path.
        
        Args:
            file_id: Google Drive file ID
            destination_path: Local path to save the file
        """
        request = self.drive_service.files().get_media(fileId=file_id)
        
        with io.FileIO(destination_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
    
    def get_metadata(self, file_id: str) -> Dict[str, Any]:
        """
        Get metadata about any Google Drive file.
        
        Args:
            file_id: The ID of the file
            
        Returns:
            Dictionary containing file metadata
        """
        try:
            file_metadata = self.drive_service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, size, modifiedTime, createdTime, owners, md5Checksum'
            ).execute()
            return file_metadata
        except Exception as e:
            print(f"Error getting file metadata: {e}")
            return {}
    
    @staticmethod
    def write_to_file(content: str, output_path: Union[str, Path]) -> None:
        """
        Write content to a file.
        
        Args:
            content: The content to write
            output_path: Path where the file should be saved
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize a filename by removing/replacing invalid characters.
        
        Args:
            filename: The filename to sanitize
            
        Returns:
            Sanitized filename safe for filesystem use
        """
        # Remove invalid characters for filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Remove trailing dots and spaces (Windows compatibility)
        # But preserve the extension
        name_parts = filename.rsplit('.', 1)
        if len(name_parts) == 2:
            name, ext = name_parts
            name = name.rstrip('. ')
            filename = f"{name}.{ext}" if name else f"file.{ext}"
        else:
            filename = filename.rstrip('. ')
        
        # Limit length to 255 characters (common filesystem limit)
        # Note: Using 251 for the name part to match original behavior
        if len(filename) > 255:
            # Preserve extension if present
            name_parts = filename.rsplit('.', 1)
            if len(name_parts) == 2:
                name, ext = name_parts
                # Truncate name to 251 chars to match original behavior
                if len(name) > 251:
                    filename = f"{name[:251]}.{ext}"
            else:
                filename = filename[:251]
        
        return filename
    
    # ====================
    # Document Processing
    # ====================
    
    def download_doc(self,
                     doc_id: str,
                     clean: bool = True,
                     output_path: Optional[Union[str, Path]] = None,
                     parse_frontmatter: bool = True) -> Any:
        """
        Download a Google Doc and optionally clean it and save to disk.
        
        Note: If save_to_disk is True (default), the document is automatically
        saved to the docs directory. The output_path parameter allows saving
        to an additional custom location.
        
        Args:
            doc_id: The ID of the Google Doc to download
            clean: Whether to apply all cleaning operations (default: True)
            output_path: Optional additional path to save the markdown file
            parse_frontmatter: Whether to parse frontmatter (default: True)
            
        Returns:
            If parse_frontmatter is True: frontmatter.Post object
            If parse_frontmatter is False: cleaned markdown string
        """
        # Download the raw markdown (automatically saves to docs dir if save_to_disk=True)
        raw_content = self._download_raw_markdown(doc_id)
        markdown_content = raw_content
        
        # Check if content was loaded from disk to avoid re-saving
        was_loaded_from_disk = (doc_id in self._doc_cache and 
                               self._doc_cache[doc_id].get('loaded_from_disk', False))
        
        # Apply cleaning if requested
        if clean:
            cleaned_content = self.clean_markdown(raw_content)
            # Only save if content actually changed after cleaning AND wasn't just loaded from disk
            if self.save_to_disk and cleaned_content != raw_content and not was_loaded_from_disk:
                self._save_to_disk(doc_id, cleaned_content, is_cleaned=True)
            markdown_content = cleaned_content
        
        # Save to additional custom path if provided
        if output_path:
            self.write_to_file(markdown_content, output_path)
            print(f"Also saved to: {output_path}")
        
        # Parse or return raw
        if parse_frontmatter:
            return frontmatter.loads(markdown_content)
        else:
            return markdown_content
    
    def download_doc_raw(self, doc_id: str) -> str:
        """
        Download a Google Doc as raw markdown without any cleaning.
        
        Args:
            doc_id: The ID of the Google Doc to download
            
        Returns:
            Raw markdown string
        """
        return self._download_raw_markdown(doc_id)
    
    def download_doc_clean(self, doc_id: str, output_path: Optional[Union[str, Path]] = None) -> str:
        """
        Download a Google Doc and apply all cleaning operations.
        
        Args:
            doc_id: The ID of the Google Doc to download
            output_path: Optional path to save the cleaned markdown file
            
        Returns:
            Cleaned markdown string
        """
        return self.download_doc(doc_id, clean=True, parse_frontmatter=False, output_path=output_path)
    
    def download_docs_batch(self,
                           doc_ids: List[str],
                           clean: bool = True,
                           output_folder: Optional[Union[str, Path]] = None,
                           use_document_names: bool = True) -> Dict[str, Any]:
        """
        Download multiple Google Docs.
        
        Args:
            doc_ids: List of Google Doc IDs to download
            clean: Whether to apply cleaning operations
            output_folder: Optional folder path to save all documents
            use_document_names: If True, use document names from metadata for filenames
            
        Returns:
            Dictionary mapping doc_id to parsed content
        """
        results = {}
        
        # Prepare output folder if provided
        if output_folder:
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)
            print(f"Saving documents to: {output_folder}")
        
        for doc_id in doc_ids:
            try:
                print(f"Downloading document: {doc_id}")
                
                # Determine output path if folder provided
                output_path = None
                if output_folder:
                    if use_document_names:
                        metadata = self.get_metadata(doc_id)
                        doc_name = metadata.get('name', doc_id)
                        safe_name = self.sanitize_filename(doc_name)
                    else:
                        safe_name = doc_id
                    
                    if not safe_name.endswith('.md'):
                        safe_name += '.md'
                    
                    output_path = output_folder / safe_name
                
                # Download with optional file output
                results[doc_id] = self.download_doc(
                    doc_id,
                    clean=clean,
                    output_path=output_path,
                    parse_frontmatter=True
                )
                
                if output_path:
                    print(f"  Saved as: {output_path.name}")
                    
            except Exception as e:
                print(f"Error downloading {doc_id}: {e}")
                results[doc_id] = None
                
        return results
    
    def _download_raw_markdown(self, doc_id: str, skip_disk_save: bool = False) -> str:
        """
        Internal method to download raw markdown from Google Drive.
        Now with in-memory and disk caching support.
        
        Args:
            doc_id: The ID of the Google Doc to download
            skip_disk_save: If True, skip saving to disk (used when content loaded from disk)
            
        Returns:
            Raw markdown content as string
        """
        # Check in-memory cache first
        if self._is_doc_cached(doc_id):
            self._cache_hits += 1
            print(f"Memory cache hit for document {doc_id}")
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
                    'etag': metadata.get('etag'),
                },
                'cached_at': datetime.now(),
                'loaded_from_disk': True  # Mark that this was loaded from disk
            }
            return disk_content
        
        # Cache miss - download the document
        self._cache_misses += 1
        print(f"Cache miss for document {doc_id} - downloading from Google Drive...")
        
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
                print(f"Download {int(status.progress() * 100)}%.")
        
        # Get the markdown content as string
        file_content.seek(0)
        content = file_content.read().decode('utf-8')
        
        # Handle auto-added document title (same logic as original)
        lines = content.split('\n') if content else []
        if len(lines) >= 2 and lines[0].startswith('# '):
            if lines[1].strip() in ['---', '']:
                metadata = self.get_metadata(doc_id)
                doc_title = metadata.get('name', '')
                first_line_title = lines[0][2:].strip()
                
                if first_line_title == doc_title:
                    print(f"Removing auto-added title: '{first_line_title}'")
                    if lines[1].strip() == '---':
                        print("Frontmatter block detected")
                    content = '\n'.join(lines[1:])
                    if content.startswith('\n'):
                        content = content[1:]
        
        elif content.strip().startswith('---'):
            print("Frontmatter block detected")
        
        # Before returning, cache the document
        metadata = self.get_metadata(doc_id)
        self._doc_cache[doc_id] = {
            'content': content,
            'metadata': {
                'modifiedTime': metadata.get('modifiedTime'),
                'md5Checksum': metadata.get('md5Checksum'),
                'etag': metadata.get('etag'),
            },
            'cached_at': datetime.now(),
            'loaded_from_disk': False  # This was freshly downloaded
        }
        
        # Save to disk if enabled (and not skipped)
        if not skip_disk_save:
            self._save_to_disk(doc_id, content)
        
        return content
    
    def clean_markdown(self, 
                      markdown_content: str,
                      clean_escapes: bool = True,
                      remove_images: bool = True,
                      strip_heading_bold: bool = True) -> str:
        """
        Apply all cleaning operations to markdown content.
        
        Args:
            markdown_content: The markdown string to clean
            clean_escapes: Whether to remove escape characters
            remove_images: Whether to remove embedded images
            strip_heading_bold: Whether to remove bold from headings
            
        Returns:
            Cleaned markdown string
        """
        if clean_escapes:
            markdown_content = self.clean_escape_characters(markdown_content)
        
        if remove_images:
            markdown_content = self.remove_embedded_images(markdown_content)
        
        if strip_heading_bold:
            markdown_content = self.strip_bold_from_headings(markdown_content)
        
        return markdown_content
    
    @staticmethod
    def clean_escape_characters(markdown_content: str) -> str:
        """
        Remove escape characters from brackets, underscores, exclamation marks, backticks, hyphens, and asterisks.
        Also handles LaTeX commands by preserving double backslashes while removing single escapes.
        
        Args:
            markdown_content: The markdown string to clean
            
        Returns:
            Cleaned markdown string with escapes removed
        """
        # Handle LaTeX commands first - preserve double backslashes for LaTeX
        content = markdown_content.replace('\\\\\\', '\\\\')
        
        # Remove escapes from various characters
        content = content.replace('\\[', '[')
        content = content.replace('\\]', ']')
        content = content.replace('\\_', '_')
        content = content.replace('\\!', '!')
        content = content.replace('\\(', '(')
        content = content.replace('\\)', ')')
        content = content.replace('\\`', '`')
        content = content.replace('\\-', '-')
        content = content.replace('\\*', '*')
        
        # Handle LaTeX commands: remove escape before backslash when followed by alphanumeric
        content = re.sub(r'\\(\\[a-zA-Z0-9])', r'\1', content)
        
        return content
    
    @staticmethod
    def remove_embedded_images(markdown_content: str) -> str:
        """
        Remove embedded images and image references from markdown content.
        
        Args:
            markdown_content: The markdown string to clean
            
        Returns:
            Cleaned markdown string with images removed
        """
        # Remove reference-style image definitions with data URIs
        # Pattern: [anything]: <data:...>
        content = re.sub(r'\[[^\]]+\]:\s*<data:[^>]*>', '', markdown_content)
        
        # Remove markdown image references
        # Pattern: ![][anything]
        content = re.sub(r'!\[\]\[[^\]]+\]', '', content)
        
        # Clean up extra blank lines that might be left
        content = re.sub(r'\n\n+', '\n\n', content)
        
        return content.strip()
    
    @staticmethod
    def strip_bold_from_headings(markdown_content: str) -> str:
        """
        Remove bold formatting (**text**) from markdown headings.
        
        Args:
            markdown_content: The markdown string to clean
            
        Returns:
            Markdown string with bold formatting removed from headings
        """
        # Pattern matches heading lines with bold markers
        content = re.sub(r'^(#+)\s+\*\*(.*?)\*\*\s*$', r'\1 \2', markdown_content, flags=re.MULTILINE)
        
        # Also handle cases where there might be bold within the heading
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip().startswith('#'):
                line = line.replace('**', '')
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    # ====================
    # Cache Management
    # ====================
    
    def clear_cache(self, doc_id: Optional[str] = None):
        """
        Clear the document cache.
        
        Args:
            doc_id: Optional specific document ID to clear from cache.
                    If not provided, clears entire cache.
        """
        if doc_id:
            self._doc_cache.pop(doc_id, None)
            print(f"Cleared cache for document {doc_id}")
        else:
            self._doc_cache.clear()
            print("Cleared entire document cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary containing cache statistics including size, hits, misses,
            hit rate, and list of cached document IDs.
        """
        return {
            'size': len(self._doc_cache),
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'hit_rate': self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            'cached_docs': list(self._doc_cache.keys())
        }
    
    def preload_cache(self, doc_ids: List[str]):
        """
        Preload multiple documents into cache.
        
        Args:
            doc_ids: List of Google Doc IDs to preload into cache
        """
        print(f"Preloading {len(doc_ids)} documents into cache...")
        for doc_id in doc_ids:
            try:
                # This will populate the cache
                self._download_raw_markdown(doc_id)
                print(f"  Preloaded: {doc_id}")
            except Exception as e:
                print(f"  Failed to preload {doc_id}: {e}")
    
    def set_output_directories(self, 
                              base_dir: Optional[Union[str, Path]] = None,
                              pdf_dir: Optional[Union[str, Path]] = None,
                              docs_dir: Optional[Union[str, Path]] = None,
                              digest_dir: Optional[Union[str, Path]] = None):
        """
        Update output directories for PDFs, docs, and digests.
        
        Args:
            base_dir: If provided, updates the base directory and all subdirectories
            pdf_dir: Custom directory for PDF outputs
            docs_dir: Custom directory for document outputs
            digest_dir: Custom directory for digest files
        """
        if base_dir:
            self.local_base_dir = Path(base_dir)
            self.docs_dir = self.local_base_dir / "docs"
            self.pdf_dir = self.local_base_dir / "pdf"
            self.digest_dir = self.local_base_dir / "digest"
        
        if pdf_dir:
            self.pdf_dir = Path(pdf_dir)
        if docs_dir:
            self.docs_dir = Path(docs_dir)
        if digest_dir:
            self.digest_dir = Path(digest_dir)
        
        # Create directories if they don't exist
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.digest_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Output directories updated:")
        print(f"  Base: {self.local_base_dir}")
        print(f"  PDFs: {self.pdf_dir}")
        print(f"  Docs: {self.docs_dir}")
        print(f"  Digests: {self.digest_dir}")
    
    def get_output_directories(self) -> Dict[str, Path]:
        """
        Get current output directory configuration.
        
        Returns:
            Dictionary with current directory paths
        """
        return {
            'base': self.local_base_dir,
            'pdf': self.pdf_dir,
            'docs': self.docs_dir,
            'digest': self.digest_dir
        }
    
    def _get_doc_filename(self, doc_id: str) -> str:
        """
        Generate a filename for saving a document to disk.
        
        Args:
            doc_id: The Google Doc ID
            
        Returns:
            Filename with .md extension
        """
        # Try to get the document name from metadata
        try:
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            safe_name = self.sanitize_filename(doc_name)
        except:
            safe_name = doc_id
        
        if not safe_name.endswith('.md'):
            safe_name += '.md'
        
        return safe_name
    
    def _get_doc_path(self, doc_id: str) -> Path:
        """
        Get the full path where a document would be saved on disk.
        
        Args:
            doc_id: The Google Doc ID
            
        Returns:
            Full path to the document file
        """
        return self.docs_dir / self._get_doc_filename(doc_id)
    
    def _load_from_disk(self, doc_id: str) -> Optional[str]:
        """
        Try to load a document from disk cache.
        
        Args:
            doc_id: The Google Doc ID
            
        Returns:
            Document content if found on disk, None otherwise
        """
        if not self.save_to_disk:
            return None
        
        doc_path = self._get_doc_path(doc_id)
        if doc_path.exists():
            try:
                # For now, we'll use a simpler approach:
                # Check if the Google Drive version has been modified
                # If we can't determine, we'll re-download to be safe
                content = doc_path.read_text(encoding='utf-8')
                
                # Check if Google Drive version is newer
                try:
                    metadata = self.get_metadata(doc_id)
                    google_modified = metadata.get('modifiedTime', '')
                    
                    # Store the modification time as a comment in the file
                    # to check on next load
                    if content.startswith(f"<!-- gdrive-modified: {google_modified} -->"):
                        # File has our metadata, it's valid
                        print(f"Loading from disk cache: {doc_path}")
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
                print(f"Error loading from disk cache: {e}")
        
        return None
    
    def _save_to_disk(self, doc_id: str, content: str, is_cleaned: bool = False):
        """
        Save document content to disk with metadata for cache validation.
        
        Args:
            doc_id: The Google Doc ID
            content: The document content to save
            is_cleaned: Whether the content has been cleaned
        """
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
            print(f"Saved to disk: {doc_path}")
        except Exception as e:
            print(f"Error saving to disk: {e}")
    
    # ====================
    # SVG Processing
    # ====================
    
    def process_svg_folder(self, folder_id: str, skip_unchanged: bool = True) -> Dict[str, Any]:
        """
        Process all SVG files in a Google Drive folder, converting to local PDFs.
        
        Args:
            folder_id: Google Drive folder ID
            skip_unchanged: Skip files that haven't changed since last processing
            
        Returns:
            Dictionary with processing results
        """
        # Show where files will be saved
        print(f"Processing SVG files from Google Drive folder: {folder_id}")
        print(f"PDFs will be saved to: {self.pdf_dir}")
        print(f"Digests will be saved to: {self.digest_dir}")
        print()
        
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
            
            print(f"Processing: {file_name}")
            
            try:
                # Check local digest if skip_unchanged is True
                if skip_unchanged:
                    local_digest = self.load_local_digest(file_name)
                    
                    if local_digest == remote_digest and local_digest:
                        pdf_name = os.path.splitext(file_name)[0] + '.pdf'
                        pdf_path = self.pdf_dir / pdf_name
                        print(f"  Skipping (unchanged): {file_name} -> {pdf_path}")
                        results['skipped'].append(file_name)
                        results['stats']['skipped'] += 1
                        continue
                
                # Create temporary directory for processing
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Download SVG from Drive
                    svg_path = os.path.join(temp_dir, file_name)
                    self.download_svg(file_id, svg_path)
                    
                    # Convert to PDF locally
                    pdf_name = os.path.splitext(file_name)[0] + '.pdf'
                    pdf_path = self.pdf_dir / pdf_name
                    
                    success, error_msg = self.convert_svg_to_pdf(svg_path, str(pdf_path))
                    
                    if success:
                        # Save digest locally if tracking changes
                        if skip_unchanged:
                            self.save_local_digest(file_name, remote_digest)
                        
                        print(f"  Converted: {file_name} -> {pdf_path}")
                        results['processed'].append(file_name)
                        results['stats']['converted'] += 1
                    else:
                        print(f"  Failed to convert: {file_name}")
                        print(f"    Error: {error_msg}")
                        results['failed'].append({
                            'file': file_name,
                            'error': error_msg
                        })
                        results['stats']['failed'] += 1
                        
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                print(f"  Error processing {file_name}: {error_msg}")
                results['failed'].append({
                    'file': file_name,
                    'error': error_msg
                })
                results['stats']['failed'] += 1
        
        return results
    
    def download_svg(self, file_id: str, destination_path: str):
        """
        Download an SVG file from Google Drive.
        
        Args:
            file_id: Google Drive file ID
            destination_path: Local path to save the SVG file
        """
        self.download_file(file_id, destination_path)
    
    def list_svg_files(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List all SVG files in a Google Drive folder.
        
        Args:
            folder_id: Google Drive folder ID
            
        Returns:
            List of file metadata dictionaries
        """
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
        """
        Convert SVG to PDF using Inkscape.
        
        Args:
            svg_path: Path to input SVG file
            pdf_path: Path to output PDF file
            
        Returns:
            Tuple of (success: bool, error_message: str)
        """
        try:
            # Check if input file exists
            if not os.path.exists(svg_path):
                error_msg = f"Input SVG file does not exist: {svg_path}"
                return False, error_msg
            
            # Run Inkscape conversion
            cmd = [
                self.inkscape_command,
                "--export-type=pdf",
                f"--export-filename={pdf_path}",
                svg_path
            ]
            
            print(f"  Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Check both return code and if PDF was created
            if result.returncode != 0:
                error_msg = f"Inkscape returned non-zero exit code {result.returncode}\n"
                error_msg += f"  STDOUT: {result.stdout}\n"
                error_msg += f"  STDERR: {result.stderr}"
                return False, error_msg
            
            if not os.path.exists(pdf_path):
                error_msg = f"PDF file was not created at {pdf_path}\n"
                error_msg += f"  STDOUT: {result.stdout}\n"
                error_msg += f"  STDERR: {result.stderr}"
                return False, error_msg
            
            # Success
            return True, ""
            
        except subprocess.TimeoutExpired:
            error_msg = "Inkscape conversion timed out after 60 seconds"
            return False, error_msg
        except FileNotFoundError:
            error_msg = f"Inkscape not found: '{self.inkscape_command}'. Please ensure Inkscape is installed."
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            return False, error_msg
    
    def load_local_digest(self, svg_filename: str) -> Optional[str]:
        """
        Load stored digest from local filesystem.
        
        Args:
            svg_filename: Name of the SVG file
            
        Returns:
            Stored digest string or None
        """
        digest_file = self.digest_dir / f"{svg_filename}.digest"
        
        if digest_file.exists():
            try:
                return digest_file.read_text().strip()
            except Exception as e:
                print(f"Error reading digest file {digest_file}: {str(e)}")
                return None
        
        return None
    
    def save_local_digest(self, svg_filename: str, digest: str):
        """
        Save digest to local filesystem.
        
        Args:
            svg_filename: Name of the SVG file
            digest: Digest string to save
        """
        digest_file = self.digest_dir / f"{svg_filename}.digest"
        
        try:
            digest_file.write_text(digest)
        except Exception as e:
            print(f"Error saving digest file {digest_file}: {str(e)}")
    
    # ====================
    # Convenience Methods
    # ====================
    
    def process_docs(self, doc_ids: List[str], output_folder: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """
        Convenience method to process multiple Google Docs with default settings.
        
        Args:
            doc_ids: List of Google Doc IDs to process
            output_folder: Optional folder to save documents
            
        Returns:
            Dictionary of results
        """
        if output_folder is None:
            output_folder = self.docs_dir
        
        return self.download_docs_batch(
            doc_ids=doc_ids,
            clean=True,
            output_folder=output_folder,
            use_document_names=True
        )
    
    def process_svgs(self, folder_id: str) -> Dict[str, Any]:
        """
        Convenience method to process SVG files from a folder with default settings.
        
        Args:
            folder_id: Google Drive folder ID containing SVG files
            
        Returns:
            Dictionary of processing results
        """
        return self.process_svg_folder(folder_id, skip_unchanged=True)
    
    # ====================
    # Unified Folder Processing
    # ====================
    
    def process_drive_folder(self, 
                            folder_id: str,
                            process_doc: bool = True,
                            process_figs: bool = True,
                            output_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """
        Process a Google Drive folder containing a manuscript and figures.
        
        This is a lightweight wrapper that automatically:
        1. Finds and downloads the manuscript document
        2. Finds and processes SVG figures in a 'figs' subfolder
        
        Args:
            folder_id: Google Drive folder ID containing the manuscript and figs
            process_doc: Whether to process the document (default: True)
            process_figs: Whether to process the figures (default: True)
            output_path: Optional path to save the manuscript markdown
            
        Returns:
            Dictionary with:
                - 'document': The processed document (if found)
                - 'document_id': ID of the document processed
                - 'document_name': Name of the document processed
                - 'figs_results': Results from SVG processing (if processed)
                - 'figs_folder_id': ID of the figs folder (if found)
                - 'errors': List of any errors encountered
        """
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
                    print(f"Found manuscript: {doc_info['name']} (ID: {doc_info['id']})")
                    results['document_id'] = doc_info['id']
                    results['document_name'] = doc_info['name']
                    
                    # Download and clean the document
                    results['document'] = self.download_doc(
                        doc_info['id'],
                        clean=True,
                        output_path=output_path,
                        parse_frontmatter=True
                    )
                    print(f"Successfully processed manuscript: {doc_info['name']}")
                else:
                    error_msg = "Could not find manuscript document. Please ensure there's either only one Google Doc in the folder or one with 'manuscript' in its name."
                    results['errors'].append(error_msg)
                    print(f"Warning: {error_msg}")
            except Exception as e:
                error_msg = f"Error processing document: {str(e)}"
                results['errors'].append(error_msg)
                print(f"Error: {error_msg}")
        
        # Process figures if requested
        if process_figs:
            try:
                figs_folder_id = self._find_figs_folder(folder_id)
                if figs_folder_id:
                    print(f"Found figs folder (ID: {figs_folder_id})")
                    results['figs_folder_id'] = figs_folder_id
                    results['figs_results'] = self.process_svg_folder(figs_folder_id)
                    
                    stats = results['figs_results'].get('stats', {})
                    print(f"Processed figures: {stats.get('converted', 0)} converted, "
                          f"{stats.get('skipped', 0)} skipped, {stats.get('failed', 0)} failed")
                else:
                    error_msg = "Could not find figs subfolder. Please create a subfolder named 'figs' containing your SVG files."
                    results['errors'].append(error_msg)
                    print(f"Warning: {error_msg}")
            except Exception as e:
                error_msg = f"Error processing figures: {str(e)}"
                results['errors'].append(error_msg)
                print(f"Error: {error_msg}")
        
        # Summary
        print("\n=== Processing Complete ===")
        if results['document_name']:
            print(f"✓ Document: {results['document_name']}")
        if results['figs_results']:
            stats = results['figs_results'].get('stats', {})
            print(f"✓ Figures: {stats.get('total_svgs', 0)} SVGs processed")
        if results['errors']:
            print(f"⚠ Errors encountered: {len(results['errors'])}")
            for error in results['errors']:
                print(f"  - {error}")
        
        return results
    
    def _find_manuscript_in_folder(self, folder_id: str) -> Optional[Dict[str, Any]]:
        """
        Find the manuscript document in a Google Drive folder.
        
        Logic:
        1. If there's only one Google Doc, use that
        2. If there are multiple, look for one with 'manuscript' in the name
        3. Otherwise return None
        
        Args:
            folder_id: Google Drive folder ID
            
        Returns:
            File metadata dictionary or None
        """
        # List all Google Docs in the folder
        page_token = None
        docs = []
        
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
        
        if not docs:
            return None
        
        # If only one doc, use it
        if len(docs) == 1:
            return docs[0]
        
        # Look for one with 'manuscript' in the name (case-insensitive)
        manuscript_docs = [doc for doc in docs if 'manuscript' in doc['name'].lower()]
        
        if len(manuscript_docs) == 1:
            return manuscript_docs[0]
        elif len(manuscript_docs) > 1:
            # If multiple manuscripts, use the first one but warn
            print(f"Warning: Found {len(manuscript_docs)} documents with 'manuscript' in name, using: {manuscript_docs[0]['name']}")
            return manuscript_docs[0]
        else:
            # No manuscript found in multiple docs
            print(f"Warning: Found {len(docs)} documents but none with 'manuscript' in the name")
            print("Available documents:")
            for doc in docs[:5]:  # Show first 5
                print(f"  - {doc['name']}")
            if len(docs) > 5:
                print(f"  ... and {len(docs) - 5} more")
            return None
    
    def _find_figs_folder(self, folder_id: str) -> Optional[str]:
        """
        Find the figures subfolder in a Google Drive folder.
        
        Logic:
        1. If there's only one subfolder, use that
        2. If there are multiple, look for one named 'figs'
        3. Otherwise return None
        
        Args:
            folder_id: Google Drive folder ID
            
        Returns:
            Folder ID of the figs folder or None
        """
        # List all subfolders
        page_token = None
        folders = []
        
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
            print(f"Using subfolder: {folders[0]['name']}")
            return folders[0]['id']
        
        # Look for one named 'figs' (case-insensitive)
        figs_folders = [f for f in folders if f['name'].lower() == 'figs']
        
        if figs_folders:
            return figs_folders[0]['id']
        else:
            # No 'figs' folder found
            print(f"Warning: Found {len(folders)} subfolders but none named 'figs'")
            print("Available subfolders:")
            for folder in folders[:5]:  # Show first 5
                print(f"  - {folder['name']}")
            if len(folders) > 5:
                print(f"  ... and {len(folders) - 5} more")
            return None