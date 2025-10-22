"""
Google Drive Processor - Unified class for processing Google Drive files

This module provides a single interface for:
- Downloading and cleaning Google Docs as markdown
- Processing SVG files and converting them to PDFs
"""

import frontmatter
import io
import json
import logging
import os
import re
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List, Tuple
from functools import wraps
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Suppress the 403 Forbidden warnings from googleapiclient
# These are misleading as the download actually succeeds
logging.getLogger('googleapiclient.http').setLevel(logging.ERROR)

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

# Import cache manager and figure converter
from .cloud_cache_manager import CloudCacheManager
from .figure_converter import FigureConverter

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
    - Disk caching of Google Docs to avoid redundant downloads
    """
    
    def __init__(self, 
                 credentials_path: Optional[str] = None,
                 credentials_dict: Optional[Dict[str, Any]] = None,
                 cache_root: Union[str, Path] = ".cache",
                 scopes: Optional[List[str]] = None,
                 save_to_disk: bool = True):
        """
        Initialize the Google Drive Processor.
        
        Args:
            credentials_path: Path to the service account credentials JSON file
            credentials_dict: Dictionary containing service account credentials
            cache_root: Root directory for the centralized cache (default: ".cache")
            scopes: List of Google API scopes
            save_to_disk: Whether to save downloaded documents to disk
            
        Note:
            Credentials can be provided in three ways (in order of precedence):
            1. credentials_dict parameter
            2. MM_GOOGLE_DRIVE_CREDENTIALS environment variable (can be JSON string or file path)
            3. credentials_path parameter
        """
        # Set default scopes
        if scopes is None:
            scopes = ['https://www.googleapis.com/auth/drive.readonly']
        
        # Track credential source for logging
        self._credentials_source = None
        self._credentials_info = {}
        
        # Determine credentials source (in order of precedence)
        if credentials_dict is not None:
            # Use provided dictionary directly
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_dict, scopes=scopes
            )
            self.credentials_path = None  # No file path when using dict
            self._credentials_source = "dictionary parameter"
            self._credentials_info = self._extract_credentials_info(credentials_dict)
            
        elif os.environ.get('MM_GOOGLE_DRIVE_CREDENTIALS'):
            # Check environment variable
            env_creds = os.environ['MM_GOOGLE_DRIVE_CREDENTIALS']
            
            # Try to parse as JSON first
            try:
                creds_dict = json.loads(env_creds)
                self.credentials = service_account.Credentials.from_service_account_info(
                    creds_dict, scopes=scopes
                )
                self.credentials_path = None
                self._credentials_source = "MM_GOOGLE_DRIVE_CREDENTIALS env var (JSON)"
                self._credentials_info = self._extract_credentials_info(creds_dict)
            except json.JSONDecodeError:
                # Not JSON, treat as file path
                self.credentials_path = env_creds
                self.credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_path, scopes=scopes
                )
                self._credentials_source = f"MM_GOOGLE_DRIVE_CREDENTIALS env var (file: {env_creds})"
                # Load file to extract info
                with open(env_creds, 'r') as f:
                    creds_dict = json.load(f)
                self._credentials_info = self._extract_credentials_info(creds_dict)
                
        elif credentials_path is not None:
            # Use provided file path
            self.credentials_path = credentials_path
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=scopes
            )
            self._credentials_source = f"credentials_path parameter (file: {credentials_path})"
            # Load file to extract info
            with open(credentials_path, 'r') as f:
                creds_dict = json.load(f)
            self._credentials_info = self._extract_credentials_info(creds_dict)
            
        else:
            # No credentials provided
            raise ValueError(
                "No Google Drive credentials provided. Please provide credentials via:\n"
                "  1. credentials_dict parameter\n"
                "  2. MM_GOOGLE_DRIVE_CREDENTIALS environment variable\n"
                "  3. credentials_path parameter"
            )
        
        # Store initialization parameters
        self.scopes = scopes
        self.save_to_disk = save_to_disk
        
        # Initialize cache manager
        self.cache_manager = CloudCacheManager(cache_root)
        
        # Initialize drive service
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
        
        # Initialize figure converter
        self.figure_converter = FigureConverter(self.cache_manager, self.drive_service)
        
        # Get service account email
        try:
            self.service_account_email = self.credentials.service_account_email
        except:
            self.service_account_email = "unknown"
        
        # SVG processing configuration
        self.inkscape_command = "inkscape"
        
        # Log credentials information
        self._log_credentials_info()
    
    def _extract_credentials_info(self, creds_dict: Dict[str, Any]) -> Dict[str, str]:
        """Extract key information from credentials dictionary."""
        return {
            'type': creds_dict.get('type', 'unknown'),
            'project_id': creds_dict.get('project_id', 'unknown'),
            'client_email': creds_dict.get('client_email', 'unknown')
        }
    
    def _log_credentials_info(self):
        """Log information about the credentials being used."""
        logger.info("=" * 60)
        logger.info("Google Drive Processor initialized")
        logger.info("-" * 60)
        logger.info(f"Credentials source: {self._credentials_source}")
        logger.info(f"Service account type: {self._credentials_info.get('type', 'unknown')}")
        logger.info(f"Project ID: {self._credentials_info.get('project_id', 'unknown')}")
        logger.info(f"Client email: {self._credentials_info.get('client_email', 'unknown')}")
        logger.info("=" * 60)
    
    def __repr__(self) -> str:
        """Return string representation of the GoogleDriveProcessor."""
        return (
            f"GoogleDriveProcessor(\n"
            f"  credentials_source={self._credentials_source},\n"
            f"  type={self._credentials_info.get('type', 'unknown')},\n"
            f"  project_id={self._credentials_info.get('project_id', 'unknown')},\n"
            f"  client_email={self._credentials_info.get('client_email', 'unknown')},\n"
            f"  cache_root={self.cache_manager.cache_root},\n"
            f"  save_to_disk={self.save_to_disk}\n"
            f")"
        )
    
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
        Includes disk caching support.
        Caches cleaned content by default instead of raw content.
        """
        # Check disk cache if enabled
        disk_content = self._load_from_disk(doc_id)
        if disk_content is not None:
            return disk_content
        
        # Need to download from Google Drive (either not cached or cache is outdated)
        logger.info(f"✗ Changes detected - downloading fresh content from Google Drive...")
        logger.info(f"  Document ID: {doc_id}")
        
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
    
    
    def _document_has_suggestions(self, doc_id: str) -> bool:
        """
        Check if a Google Doc has any suggested edits.
        
        Uses the Google Docs API to fetch the document with suggestions inline
        and checks for suggestion markers in the content.
        """
        try:
            # Build Google Docs service if not already available
            if not hasattr(self, 'docs_service'):
                self.docs_service = build('docs', 'v1', credentials=self.credentials)
            
            # Fetch document with suggestions inline
            doc = self.docs_service.documents().get(
                documentId=doc_id,
                suggestionsViewMode='SUGGESTIONS_INLINE'
            ).execute()
            
            # Check for suggestions in the document content
            if self._check_element_for_suggestions(doc.get('body', {})):
                return True
            
            # Check headers and footers if they exist
            for header_id in doc.get('headers', {}):
                if self._check_element_for_suggestions(doc['headers'][header_id]):
                    return True
            
            for footer_id in doc.get('footers', {}):
                if self._check_element_for_suggestions(doc['footers'][footer_id]):
                    return True
            
            # Check footnotes if they exist
            for footnote_id in doc.get('footnotes', {}):
                if self._check_element_for_suggestions(doc['footnotes'][footnote_id]):
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Could not check for suggestions using Docs API: {e}")
            # Fall back to false if we can't check
            return False
    
    def _check_element_for_suggestions(self, element: dict) -> bool:
        """
        Recursively check a document element for suggestion markers.
        
        Returns True if any suggestions are found.
        """
        if not element:
            return False
        
        # Check for suggestion IDs in various fields
        if element.get('suggestedInsertionIds') or element.get('suggestedDeletionIds'):
            return True
        
        # Check for suggested text style changes
        if element.get('suggestedTextStyleChanges'):
            return True
        
        # Check for suggested paragraph style changes
        if element.get('suggestedParagraphStyleChanges'):
            return True
        
        # Check for suggested named style changes
        if element.get('suggestedNamedStylesChanges'):
            return True
        
        # Check for suggested bullet changes
        if element.get('suggestedBulletChanges'):
            return True
        
        # Check for suggested positioning changes
        if element.get('suggestedPositionedObjectPositioningChanges'):
            return True
        
        # Recursively check content arrays
        if 'content' in element:
            for content_element in element['content']:
                if self._check_element_for_suggestions(content_element):
                    return True
        
        # Check paragraph elements
        if 'paragraph' in element:
            if self._check_element_for_suggestions(element['paragraph']):
                return True
            
            # Check elements within paragraph
            if 'elements' in element['paragraph']:
                for elem in element['paragraph']['elements']:
                    if self._check_element_for_suggestions(elem):
                        return True
        
        # Check table
        if 'table' in element:
            table = element['table']
            # Check table rows
            for row in table.get('tableRows', []):
                for cell in row.get('tableCells', []):
                    if self._check_element_for_suggestions(cell):
                        return True
                    # Check content within cell
                    for content in cell.get('content', []):
                        if self._check_element_for_suggestions(content):
                            return True
        
        # Check section break
        if 'sectionBreak' in element:
            if self._check_element_for_suggestions(element['sectionBreak']):
                return True
        
        # Check table of contents
        if 'tableOfContents' in element:
            if self._check_element_for_suggestions(element['tableOfContents']):
                return True
        
        # Check text run
        if 'textRun' in element:
            text_run = element['textRun']
            if text_run.get('suggestedInsertionIds') or text_run.get('suggestedDeletionIds'):
                return True
            if text_run.get('suggestedTextStyleChanges'):
                return True
        
        return False
    
    def _check_for_active_changes(self, doc_id: str):
        """
        Check if a document has active suggestions and warn the user.
        
        This uses the Google Docs API to check if the document contains
        suggested edits that haven't been accepted or rejected.
        """
        try:
            # Get document metadata first
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            
            # Check for suggestions using Google Docs API
            if self._document_has_suggestions(doc_id):
                logger.warning("")
                logger.warning("=" * 70)
                logger.warning("⚠️  WARNING: DOCUMENT HAS SUGGESTED EDITS")
                logger.warning("=" * 70)
                logger.warning(f"Document: {doc_name}")
                logger.warning("")
                logger.warning("This document contains unresolved suggested edits that")
                logger.warning("may not be included in the exported version.")
                logger.warning("")
                logger.warning("You are building a production PDF from a document with")
                logger.warning("suggested edits, which is probably not what you want.")
                logger.warning("")
                logger.warning("Please review and accept/reject all suggested edits in")
                logger.warning("Google Docs before generating the final output.")
                logger.warning("=" * 70)
                logger.warning("")
            
            # Also check for unresolved comments
            try:
                # Get detailed comment information including quotedFileContent
                comments = self.drive_service.comments().list(
                    fileId=doc_id,
                    fields='comments(id,content,author(displayName,emailAddress),createdTime,modifiedTime,resolved,deleted,replies,quotedFileContent)',
                    includeDeleted=False
                ).execute()
                
                # Filter out deleted and phantom comments
                all_comments = comments.get('comments', [])
                unresolved_comments = []
                
                for comment in all_comments:
                    # Skip if explicitly deleted (safety check even with includeDeleted=False)
                    if comment.get('deleted', False):
                        continue
                    
                    # Skip if no content (phantom comment)
                    content = comment.get('content', '').strip()
                    if not content:
                        continue
                    
                    # Skip if this is an "Original content deleted" comment
                    # These occur when the text a comment was attached to has been deleted
                    # but the comment itself remains unresolved
                    if 'original content deleted' in content.lower():
                        continue
                    
                    # Also check if quotedFileContent indicates deleted content
                    quoted_content = comment.get('quotedFileContent', {})
                    if quoted_content and not quoted_content.get('value', '').strip():
                        # Comment's anchor text was deleted
                        continue
                    
                    # Check if unresolved
                    if not comment.get('resolved', False):
                        unresolved_comments.append(comment)
                
                if unresolved_comments:
                    logger.warning("")
                    logger.warning("=" * 70)
                    logger.warning("📝 NOTICE: DOCUMENT HAS UNRESOLVED DISCUSSION COMMENTS")
                    logger.warning("=" * 70)
                    logger.warning(f"Document: {doc_name}")
                    logger.warning(f"")
                    logger.warning(f"Found {len(unresolved_comments)} unresolved comment(s):")
                    logger.warning("")
                    
                    # Show details about each comment (up to 5)
                    for i, comment in enumerate(unresolved_comments[:5], 1):
                        try:
                            # Safely get author information
                            author = comment.get('author', {})
                            if isinstance(author, dict):
                                author_name = author.get('displayName', author.get('emailAddress', 'Unknown'))
                            else:
                                author_name = 'Unknown'
                            
                            # Safely get content
                            content = comment.get('content', '')
                            if not isinstance(content, str):
                                content = str(content) if content else ''
                            
                            # Truncate content to 100 chars
                            if len(content) > 100:
                                content = content[:97] + '...'
                            
                            # Safely get and format created time
                            created = comment.get('createdTime', '')
                            if created:
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                                    created_str = dt.strftime('%Y-%m-%d %H:%M')
                                except:
                                    created_str = created[:10] if len(created) >= 10 else 'Unknown date'
                            else:
                                created_str = 'Unknown date'
                            
                            logger.warning(f"  {i}. [{author_name}, {created_str}]")
                            logger.warning(f"     \"{content}\"")
                            
                            # Safely check for replies
                            replies = comment.get('replies', [])
                            if isinstance(replies, list) and len(replies) > 0:
                                logger.warning(f"     ({len(replies)} replies in thread)")
                            logger.warning("")
                        except Exception as e:
                            # If we can't process a comment, skip it rather than crash
                            logger.debug(f"Error processing comment {i}: {e}")
                            logger.warning(f"  {i}. [Error reading comment details]")
                            logger.warning("")
                    
                    if len(unresolved_comments) > 5:
                        logger.warning(f"  ... and {len(unresolved_comments) - 5} more comment(s)")
                        logger.warning("")
                    
                    logger.warning("Note: These are discussion comments, not suggested edits.")
                    logger.warning("Review these comments to ensure all feedback is addressed.")
                    logger.warning("=" * 70)
                    logger.warning("")
                    
            except Exception as e:
                # Comments API failed, skip the check silently
                logger.debug(f"Could not check for comments: {e}")
                pass
                
        except Exception as e:
            # Don't fail the download if the check fails, just log a debug message
            logger.debug(f"Could not check for active changes: {e}")
    
    # ====================
    # Changes API Implementation
    # ====================
    
    def check_for_changes_via_changes_api(self, doc_id: str) -> bool:
        """
        Check if a document has changed using the Google Drive Changes API.
        
        Args:
            doc_id: The ID of the document to check
            
        Returns:
            True if the document has changed, False if not
        """
        try:
            # Load metadata to get stored change token
            metadata = self.cache_manager.load_metadata(doc_id)
            stored_token = metadata.get('change_token') if metadata else None
            
            if not stored_token:
                # No token means first run or cache was cleared
                logger.info("  No change token found - first time caching this document")
                return True
            
            # Use the stored token to check for changes
            try:
                # List changes since the stored token
                response = self.drive_service.changes().list(
                    pageToken=stored_token,
                    spaces='drive',
                    includeRemoved=True,
                    fields='nextPageToken, newStartPageToken, changes(fileId, removed)'
                ).execute()
                
                # Get the new/remote token
                remote_token = response.get('newStartPageToken') or response.get('nextPageToken')
                
                # Check if our document is in the changes list
                changes = response.get('changes', [])
                doc_changed = False
                for change in changes:
                    if change.get('fileId') == doc_id:
                        doc_changed = True
                        break
                
                # Display token info with clear context
                if remote_token and remote_token != stored_token:
                    logger.info(f"  Change tokens: {stored_token[:20]}... → {remote_token[:20]}...")
                    if doc_changed:
                        logger.info(f"  ✗ This document was modified - downloading fresh copy")
                    else:
                        logger.info(f"  ✓ This document unchanged (other Drive files changed) - using cached version")
                else:
                    logger.info(f"  Change token: {stored_token[:20]}... (no Drive activity)")
                    logger.info(f"  ✓ No changes detected - using cached version")
                
                if doc_changed:
                    return True
                
                # Update the token to the latest (for next check)
                if remote_token and remote_token != stored_token:
                    # Save the new token for next time
                    self.cache_manager.save_metadata(doc_id, {
                        'doc_id': doc_id,
                        'change_token': remote_token
                    })
                
                return False
                
            except Exception as e:
                # Token might be invalid/expired
                if 'Invalid pageToken' in str(e) or 'invalid' in str(e).lower():
                    logger.warning(f"  Change token is invalid or expired")
                    logger.info("  Will download fresh copy and get new token")
                else:
                    logger.warning(f"  Error with change detection: {str(e)[:100]}")
                    logger.info("  Falling back to re-download for safety")
                return True
                
        except Exception as e:
            logger.error(f"Error checking for changes via Changes API: {str(e)[:200]}")
            logger.info("  Falling back to re-download for safety")
            # On error, be safe and assume changed
            return True
    
    def get_current_change_token(self) -> Optional[str]:
        """
        Get a fresh change token for the current state of the drive.
        
        Returns:
            The current change token or None if error
        """
        try:
            response = self.drive_service.changes().getStartPageToken(
                supportsAllDrives=False
            ).execute()
            return response.get('startPageToken')
        except Exception as e:
            logger.error(f"Error getting change token: {e}")
            return None
    
    # ====================
    # Disk Cache Operations
    # ====================
    
    def _get_doc_filename(self, doc_id: str) -> str:
        """Generate a filename for saving a document to disk."""
        try:
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            
            # Ensure doc_name is a string before passing to sanitize_filename
            if not isinstance(doc_name, str):
                logger.warning(f"Document name is not a string: {type(doc_name)} - {doc_name}")
                doc_name = str(doc_name) if doc_name else doc_id
            
            safe_name = sanitize_filename(doc_name)
        except Exception as e:
            logger.warning(f"Could not get metadata for doc {doc_id}: {e}")
            # Ensure doc_id is a string
            safe_name = str(doc_id) if not isinstance(doc_id, str) else doc_id
        
        # Ensure safe_name is a string before calling endswith
        if not isinstance(safe_name, str):
            logger.error(f"safe_name is not a string: {type(safe_name)} - {safe_name}")
            safe_name = str(safe_name)
        
        if not safe_name.endswith('.md'):
            safe_name += '.md'
        
        return safe_name
    
    def _get_doc_path(self, doc_id: str) -> Path:
        """Get the full path where a document would be saved on disk."""
        return self.cache_manager.get_cache_path(doc_id, 'docs', self._get_doc_filename(doc_id))
    
    def _load_from_disk(self, doc_id: str) -> Optional[str]:
        """Try to load a document from disk cache."""
        if not self.save_to_disk:
            return None
        
        doc_path = self.cache_manager.get_cache_path(doc_id, 'docs', self._get_doc_filename(doc_id))
        if not doc_path.exists():
            return None
            
        logger.info(f"Checking for changes in document {doc_id}...")
        
        # Use Changes API to check if document has changed
        has_changed = self.check_for_changes_via_changes_api(doc_id)
        
        if not has_changed:
            # Document hasn't changed, load from cache
            try:
                content = doc_path.read_text(encoding='utf-8')
                
                # Handle legacy cached files with HTML comments (migration)
                if content.startswith("<!-- gdrive-modified:"):
                    lines = content.split('\n')
                    content = '\n'.join(lines[1:])
                    if content.startswith('\n'):
                        content = content[1:]
                    # Migrate by re-saving without the comment
                    doc_path.write_text(content, encoding='utf-8')
                    logger.debug("  Migrated legacy cached file (removed HTML comment)")
                
                return content
            except Exception as e:
                logger.error(f"Error loading from disk cache: {e}")
                return None
        else:
            # Document has changed, will need to re-download
            logger.info("  Document has changed - will download fresh copy")
            return None
    
    def _save_to_disk(self, doc_id: str, content: str, is_cleaned: bool = False):
        """Save document content to disk and update metadata."""
        if not self.save_to_disk:
            return
        
        doc_path = self._get_doc_path(doc_id)
        try:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save clean content without HTML comments
            doc_path.write_text(content, encoding='utf-8')
            logger.info(f"Saved to disk: {doc_path}")
            
            # Get current change token and save metadata
            try:
                # Get document metadata
                doc_metadata = self.get_metadata(doc_id)
                
                # Get current change token
                change_token = self.get_current_change_token()

                # Load existing metadata or create new v3.0 structure
                metadata = self.cache_manager.load_metadata(doc_id)
                if not metadata:
                    metadata = {
                        'document': self.cache_manager._init_document_metadata(),
                        'figures': [],
                        'csvs': [],
                        'cache_stats': self.cache_manager._init_cache_stats(),
                        'cache_version': '3.0'
                    }

                # Update document metadata
                parents = doc_metadata.get('parents', [])
                metadata['document'].update({
                    'doc_id': doc_id,
                    'doc_name': doc_metadata.get('name', 'Unknown'),
                    'change_token': change_token,
                    'cleaned_state': 'cleaned' if is_cleaned else 'raw',
                    'modified_time': doc_metadata.get('modifiedTime', ''),
                    'folder_id': parents[0] if parents else None,
                    'filename': doc_path.name,
                    'source_path': f"docs/{doc_path.name}",
                    'size': doc_path.stat().st_size,
                    'downloaded_at': datetime.now().isoformat(),
                    'digest': self.cache_manager.compute_md5(doc_path)
                })

                # Update stats and save
                self.cache_manager._update_cache_stats(metadata)
                self.cache_manager.save_metadata(doc_id, metadata)
                
                if change_token:
                    logger.info(f"  Saved change token: {change_token[:20]}...")
                
            except Exception as e:
                logger.debug(f"Error saving metadata: {e}")
                
        except Exception as e:
            logger.error(f"Error saving to disk: {e}")
    
    # ====================
    # SVG Processing
    # ====================
    
    # Note: Legacy SVG folder processing methods have been removed
    # Use process_document_figures() for document-driven figure processing
    # ====================
    # Digest Management (path-based only)
    # ====================
    
    def load_local_digest(self, file_identifier: str, doc_id: str) -> Optional[str]:
        """
        Load stored digest from local filesystem.
        Delegates to CloudCacheManager.
        
        Args:
            file_identifier: The file identifier/path
            doc_id: Document ID for cache context
        """
        return self.cache_manager.load_digest(doc_id, file_identifier)
    
    def save_local_digest(self, file_identifier: str, digest: str, doc_id: str):
        """
        Save digest to local filesystem.
        Delegates to CloudCacheManager.
        
        Args:
            file_identifier: The file identifier/path
            digest: The digest to save
            doc_id: Document ID for cache context
        """
        self.cache_manager.save_digest(doc_id, file_identifier, digest)
    
    # ====================
    # Document-Driven Figure Processing
    # ====================
    
    def parse_figure_parameters(self, param_string: str) -> dict:
        """
        Parse figure parameters from markdown syntax.
        Delegates to FigureConverter.
        """
        return self.figure_converter.parse_figure_parameters(param_string)
    
    def extract_figure_paths(self, markdown_content: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract all figure paths and their parameters from markdown content.
        Delegates to FigureConverter.
        """
        return self.figure_converter.extract_figure_paths(markdown_content)
    
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
    
    def _prepare_document_and_folder(self, doc_id: str, folder_id: Optional[str]) -> tuple[str, list, str]:
        """Prepare document content and determine folder ID."""
        # Download and read the document (with cleaning to remove embedded images)
        doc_content = self.download_doc(doc_id, clean=True, parse_frontmatter=False, update_figure_paths=False)
        
        # Extract figure paths with parameters
        figure_data = self.extract_figure_paths(doc_content)
        logger.info(f"Found {len(figure_data)} figure references in document")
        
        # If no folder_id provided, try to find the parent folder of the document
        if not folder_id:
            try:
                doc_metadata = self.get_metadata(doc_id)
                parents = doc_metadata.get('parents', [])
                if parents:
                    folder_id = parents[0]
                    logger.info(f"Using document's parent folder: {folder_id}")
                    
                    # Save folder_id to document metadata for future use
                    self.cache_manager.save_metadata(doc_id, {
                        'doc_id': doc_id,
                        'folder_id': folder_id,
                        'doc_name': doc_metadata.get('name', 'Unknown')
                    })
                else:
                    logger.warning("No parent folder found for document")
            except Exception as e:
                logger.error(f"Error getting document parent folder: {e}")
        
        return doc_content, figure_data, folder_id
    
    def _log_figure_processing_summary(self, results: dict):
        """Log summary of figure processing results."""
        logger.info(f"\n=== Figure Processing Complete ===")
        logger.info(f"✓ Processed: {len(results['processed'])} figures")
        logger.info(f"⏭ Skipped: {len(results['skipped'])} unchanged figures")
        logger.info(f"✗ Failed: {len(results['failed'])} figures")
        
        # List failed conversions for clarity
        if results['failed']:
            logger.warning(f"\n⚠️  The following {len(results['failed'])} files FAILED to convert to PDF:")
            for failed_file in results['failed']:
                logger.warning(f"   - {failed_file}")
            logger.warning(f"   Check the error messages above for details on each failure.")
    
    def _get_cached_file_or_download(self, fig_path: str, file_info: dict, doc_id: str, figure_type: str) -> Path:
        """Get cached file or download if needed. Returns Path to source file."""
        if figure_type == 'csv':
            # Remove 'csv/' prefix from path since we're already in csv subdirectory
            filename = fig_path.replace('csv/', '') if fig_path.startswith('csv/') else fig_path
            cached_path = self.cache_manager.get_cache_path(doc_id, 'csv', filename)
        elif figure_type == 'svg':
            # Remove 'fig/' prefix from path since we're already in fig subdirectory
            filename = fig_path.replace('fig/', '') if fig_path.startswith('fig/') else fig_path
            cached_path = self.cache_manager.get_cache_path(doc_id, 'fig', filename)
        else:
            # Other types - use temp file
            temp_dir = self.cache_manager.get_cache_dir(doc_id, 'converted')
            cached_path = temp_dir / f".temp_{Path(fig_path).stem}_{os.getpid()}"
        
        # Check if cached file exists and is current
        if cached_path.exists() and file_info and 'md5Checksum' in file_info:
            stored_digest = self.figure_converter._load_digest(fig_path, doc_id, 'file')
            if stored_digest == file_info['md5Checksum']:
                logger.info(f"  Using cached {figure_type.upper()}: {cached_path}")
                return cached_path
        
        # Need to download
        logger.info(f"  Downloading {figure_type.upper()}: {fig_path}")
        self.download_file(file_info['id'], str(cached_path))

        # Record the cached file in metadata
        if cached_path.exists():
            self.cache_manager.record_cached_file(
                doc_id=doc_id,
                filename=cached_path.name,
                source_path=fig_path,
                size=cached_path.stat().st_size,
                drive_file_id=file_info['id'],
                digest=file_info.get('md5Checksum')
            )

        return cached_path
    
    def _convert_file(self, fig_path: str, source_file: Path, file_info: dict, params: dict, doc_id: str, figure_type: str, output_path: Path) -> str:
        """Convert file and return converted path, or None if failed."""
        # Determine the relative path for the output
        relative_output_path = f"converted/{fig_path.replace('fig/', '').replace('csv/', '')}"
        if figure_type == 'svg':
            relative_output_path = relative_output_path.replace('.svg', '.pdf')
        elif figure_type == 'csv':
            relative_output_path = relative_output_path.replace('.csv', '.pdf')

        if figure_type == 'svg':
            # For SVG, convert directly
            success = self.figure_converter.convert_svg(str(source_file), output_path)
            if success:
                # Save digest for original path
                if file_info and 'md5Checksum' in file_info:
                    self.figure_converter.save_digest(fig_path, file_info['md5Checksum'], doc_id, 'file')

                # Record successful conversion in metadata
                self.cache_manager.record_conversion(
                    doc_id=doc_id,
                    filename=source_file.name,
                    output_path=relative_output_path,
                    output_size=output_path.stat().st_size if output_path.exists() else None,
                    status='success'
                )

                # Return absolute path
                return str(output_path.resolve() if hasattr(output_path, 'resolve') else output_path)
            else:
                logger.warning(f"⚠️  PDF CONVERSION FAILED for {fig_path}")
                logger.warning(f"    SVG file exists at: {source_file}")
                logger.warning(f"    Expected PDF output: {output_path}")
                logger.warning(f"    Check inkscape installation and SVG file validity")

                # Record failed conversion in metadata
                self.cache_manager.record_conversion(
                    doc_id=doc_id,
                    filename=source_file.name,
                    status='failed',
                    error="Inkscape conversion failed"
                )
                return None

        elif figure_type == 'csv':
            # For CSV, use convert_figure which handles digest saving properly
            converted_path = self.figure_converter.convert_figure(
                str(source_file), params, doc_id, file_info, original_path=fig_path
            )
            if converted_path:
                # Record successful conversion in metadata
                output_file = Path(converted_path)
                self.cache_manager.record_conversion(
                    doc_id=doc_id,
                    filename=source_file.name,
                    output_path=relative_output_path,
                    output_size=output_file.stat().st_size if output_file.exists() else None,
                    status='success'
                )
            else:
                logger.warning(f"⚠️  PDF CONVERSION FAILED for {fig_path}")
                logger.warning(f"    CSV file exists at: {source_file}")
                logger.warning(f"    Check table_pdf_builder installation")

                # Record failed conversion in metadata
                self.cache_manager.record_conversion(
                    doc_id=doc_id,
                    filename=source_file.name,
                    status='failed',
                    error="table_pdf_builder conversion failed"
                )

            return converted_path

        else:
            # Clean up temp files for other types
            if source_file.name.startswith('.temp_') and source_file.exists():
                source_file.unlink()
            return None

    def process_document_figures(self, doc_id: str, folder_id: Optional[str] = None, 
                                skip_unchanged: bool = True) -> Dict[str, Any]:
        """
        Process all figures referenced in the document including SVG, CSV, and Google Sheets.
        
        This method processes:
        - SVG files -> PDF conversion
        - CSV files -> PDF table conversion
        - Google Sheets -> PDF table conversion
        - PDF files -> direct download
        """
        logger.info(f"Processing figures for document: {doc_id}")
        
        # Prepare document and determine folder
        doc_content, figure_data, folder_id = self._prepare_document_and_folder(doc_id, folder_id)
        
        # Prepare list of paths for batch fetching and optimize API calls
        figure_paths = [path for path, _ in figure_data]
        folder_file_cache = self._batch_fetch_folder_metadata(figure_paths, folder_id)
        
        # Process each figure
        results = {'processed': [], 'skipped': [], 'failed': [], 'mapping': {}}
        
        for fig_path, params in figure_data:
            logger.info(f"Processing: {fig_path}")
            
            # Determine figure type and skip unknown
            figure_type = self.figure_converter.get_figure_type(fig_path)
            if figure_type == 'unknown':
                logger.info(f"  Skipping unknown file type: {fig_path}")
                continue
            
            # Handle Google Sheets separately
            if figure_type == 'sheet':
                converted_path = self.figure_converter.convert_figure(fig_path, params, doc_id, None)
                if converted_path:
                    logger.info(f"  Converted: {fig_path} -> {converted_path}")
                    results['processed'].append(fig_path)
                    results['mapping'][fig_path] = converted_path
                else:
                    logger.error(f"  Failed to convert Google Sheet")
                    results['failed'].append(fig_path)
                continue
            
            # Find file in Drive (skip if not found)
            file_info = self._find_file_in_cache(fig_path, folder_file_cache) if folder_id else None
            if not file_info:
                logger.error(f"  Failed: File not found in Google Drive")
                results['failed'].append(fig_path)
                continue
            
            # Handle PDF files - direct download
            if figure_type == 'pdf':
                try:
                    output_path = Path(fig_path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    self.download_file(file_info['id'], str(output_path))
                    logger.info(f"  Downloaded: {fig_path}")
                    results['processed'].append(fig_path)
                except Exception as e:
                    logger.error(f"  Error downloading PDF: {e}")
                    results['failed'].append(fig_path)
                continue
            
            # Handle SVG and CSV files - download and convert
            try:
                output_path = self.figure_converter.get_output_path(fig_path, doc_id, figure_type)
                
                # Check if conversion needed (skip if cached)
                if not self.figure_converter.needs_conversion(fig_path, doc_id, output_path, file_info, params):
                    logger.info(f"  Using cached: {output_path}")
                    results['skipped'].append(fig_path)
                    # Ensure path is absolute before storing in mapping
                    absolute_path = str(output_path.resolve() if hasattr(output_path, 'resolve') else output_path)
                    results['mapping'][fig_path] = absolute_path
                    logger.info(f"  Added to mapping: {fig_path} -> {absolute_path}")
                    continue
                
                # Get source file (cached or download)
                source_file = self._get_cached_file_or_download(fig_path, file_info, doc_id, figure_type)
                
                # Convert file
                converted_path = self._convert_file(fig_path, source_file, file_info, params, doc_id, figure_type, output_path)
                
                if converted_path:
                    logger.info(f"  Converted: {fig_path} -> {converted_path}")
                    results['processed'].append(fig_path)
                    results['mapping'][fig_path] = converted_path
                else:
                    logger.error(f"  Failed to convert {figure_type} file")
                    results['failed'].append(fig_path)
                    
            except Exception as e:
                logger.error(f"  Error processing {fig_path}: {str(e)[:200]}")
                results['failed'].append(fig_path)
        
        # Update document with new paths and check for remaining SVGs
        logger.info(f"DEBUG: Mapping has {len(results['mapping'])} entries:")
        for old_p, new_p in results['mapping'].items():
            logger.info(f"  {old_p} -> {new_p}")
        updated_content = self._update_figure_paths(doc_content, results['mapping'])
        
        import re
        remaining_svgs = re.findall(r'[^)]+\.svg\)', updated_content)
        if remaining_svgs:
            logger.warning(f"WARNING: {len(remaining_svgs)} SVG paths remain after replacement!")
            for svg in remaining_svgs[:5]:  # Show first 5
                logger.warning(f"  Still has: {svg}")
        
        # Log processing summary
        self._log_figure_processing_summary(results)
        
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
                    
                    # Save folder_id to document metadata for future use
                    self.cache_manager.save_metadata(doc_id, {
                        'doc_id': doc_id,
                        'folder_id': folder_id,
                        'doc_name': doc_metadata.get('name', 'Unknown')
                    })
                else:
                    logger.warning("No parent folder found for document")
            except Exception as e:
                logger.error(f"Error getting document parent folder: {e}")
        
        # Batch fetch metadata
        folder_cache = self._batch_fetch_folder_metadata([], folder_id, csv_paths=csv_paths)
        
        # Process CSVs with doc_id for cache context
        results = self._process_csv_files(csv_paths, folder_cache, skip_unchanged, doc_id)
        
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
                          skip_unchanged: bool = True, doc_id: str = None) -> Dict[str, Any]:
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
            
            # Create local path structure using cache manager
            if doc_id:
                local_path = self.cache_manager.get_cache_path(doc_id, 'csv', csv_path)
            else:
                local_path = Path(csv_path)
                local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if unchanged (using digest)
            remote_digest = file_info.get('md5Checksum', '')
            if skip_unchanged and remote_digest:
                local_digest = self.load_local_digest(csv_path, doc_id) if doc_id else self.load_local_digest(csv_path, 'default')
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
                    self.save_local_digest(csv_path, remote_digest, doc_id) if doc_id else self.save_local_digest(csv_path, remote_digest, 'default')
                    
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
        """Replace figure paths in document with converted paths while preserving parameters."""
        logger.debug(f"_update_figure_paths called with {len(path_mapping)} mappings")
        updated = markdown_content
        
        # First, handle paths with parameters - preserve the parameters
        # Pattern to match figure references with parameters
        param_pattern = r'(!\[[^\]]*\]\()([^)]+)(\))(\{[^}]*\})'
        
        def replace_with_mapping(match):
            prefix = match.group(1)  # ![alt](
            path = match.group(2)     # the path
            suffix = match.group(3)   # )
            params = match.group(4)   # {parameters} - now preserved
            
            # Check if this path has a mapping
            if path in path_mapping:
                return f"{prefix}{path_mapping[path]}{suffix}{params}"
            return f"{prefix}{path}{suffix}{params}"
        
        # Replace figures with parameters
        updated = re.sub(param_pattern, replace_with_mapping, updated)
        
        # Then handle regular path replacements for paths without parameters
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
        figure_data = self.extract_figure_paths(markdown_content)
        
        if not figure_data:
            return markdown_content
        
        # Extract just the paths from the (path, params) tuples
        figure_paths = [path for path, _ in figure_data]
        
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
