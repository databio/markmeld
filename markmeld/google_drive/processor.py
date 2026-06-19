"""Google Drive Processor for markmeld.

This module provides the GoogleDriveProcessor class for unified Google Drive
file operations, including:
- Downloading and cleaning Google Docs as markdown
- Processing SVG and CSV files with PDF conversion
- Managing disk cache for efficient re-downloads
- Detecting document changes by comparing Drive modifiedTime
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
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Suppress the 403 Forbidden warnings from googleapiclient
# These are misleading as the download actually succeeds
logging.getLogger('googleapiclient.http').setLevel(logging.ERROR)

# Import utility functions from parent package
from ..utilities import sanitize_filename, write_to_file
from .markdown_clean import clean_markdown
from .doc_to_markdown import doc_to_markdown
from .figure_paths import extract_csv_paths, update_figure_paths, create_figure_path_mapping

# Import cache manager and figure converter from this subpackage
from .cache_manager import CloudCacheManager
from .figure_converter import FigureConverter

_LOGGER = logging.getLogger(__name__)


def handle_drive_errors(func: Any) -> Any:
    """Decorator for common Google Drive API error handling.

    Wraps functions that make Drive API calls to log errors before re-raising.

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function with error handling.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _LOGGER.error(f"Error in {func.__name__}: {e}")
            raise
    return wrapper


class GoogleDriveProcessor:
    """Processor for Google Drive documents and figure files.

    Provides unified functionality for:
    - Downloading Google Docs and converting them to clean markdown
    - Processing SVG/CSV files from Google Drive and converting them to PDFs
    - Disk caching of documents to avoid redundant downloads
    - Change detection by comparing the Doc's Drive modifiedTime

    Attributes:
        credentials: Google service account credentials.
        credentials_path: Path to credentials file (if file-based).
        scopes: List of Google API scopes.
        save_to_disk: Whether to save downloaded documents to disk.
        cache_manager: CloudCacheManager instance for cache operations.
        drive_service: Google Drive API service instance.
        figure_converter: FigureConverter instance for figure processing.
        service_account_email: Email of the service account.
        inkscape_command: Command to run inkscape for SVG conversion.
    """

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        credentials_dict: Optional[Dict[str, Any]] = None,
        cache_root: Union[str, Path] = ".cache",
        scopes: Optional[List[str]] = None,
        save_to_disk: bool = True
    ) -> None:
        """Initialize the Google Drive Processor.

        Args:
            credentials_path: Path to the service account credentials JSON file.
            credentials_dict: Dictionary containing service account credentials.
            cache_root: Root directory for the centralized cache.
            scopes: List of Google API scopes.
            save_to_disk: Whether to save downloaded documents to disk.

        Raises:
            ValueError: If no credentials are provided.

        Note:
            Credentials can be provided in three ways (in order of precedence):
            1. credentials_dict parameter
            2. MM_GOOGLE_DRIVE_CREDENTIALS environment variable (JSON string or file path)
            3. credentials_path parameter
        """
        # Set default scopes
        if scopes is None:
            scopes = [
                'https://www.googleapis.com/auth/drive.readonly',
                'https://www.googleapis.com/auth/documents.readonly',
            ]
        
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
        self.drive_service = build('drive', 'v3', credentials=self.credentials, cache_discovery=False)
        
        # Initialize figure converter
        self.figure_converter = FigureConverter(self.cache_manager, self.drive_service)

        # Get service account email
        try:
            self.service_account_email = self.credentials.service_account_email
        except Exception:
            self.service_account_email = "unknown"
        
        # SVG processing configuration
        self.inkscape_command = "inkscape"
        
        # Log credentials information
        self._log_credentials_info()
    
    def _extract_credentials_info(self, creds_dict: Dict[str, Any]) -> Dict[str, str]:
        """Extract key information from credentials dictionary.

        Args:
            creds_dict: Service account credentials dictionary.

        Returns:
            Dict with 'type', 'project_id', and 'client_email' keys.
        """
        return {
            'type': creds_dict.get('type', 'unknown'),
            'project_id': creds_dict.get('project_id', 'unknown'),
            'client_email': creds_dict.get('client_email', 'unknown')
        }

    def _log_credentials_info(self) -> None:
        """Log information about the credentials being used."""
        _LOGGER.info(f"Google Drive Processor initialized: {self._credentials_info.get('client_email', 'unknown')} ({self._credentials_info.get('project_id', 'unknown')})")

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
    def download_file(self, file_id: str, destination_path: str) -> None:
        """Download any file from Google Drive to a local path.

        Args:
            file_id: The Google Drive file ID.
            destination_path: Local path to save the file.
        """
        request = self.drive_service.files().get_media(fileId=file_id)
        
        with io.FileIO(destination_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
    
    @handle_drive_errors
    def get_metadata(self, file_id: str) -> Dict[str, Any]:
        """Get metadata about any Google Drive file.

        Args:
            file_id: The Google Drive file ID.

        Returns:
            Dict containing file metadata (id, name, mimeType, size, modifiedTime,
            createdTime, owners, md5Checksum, parents).
        """
        file_metadata = self.drive_service.files().get(
            fileId=file_id,
            fields='id, name, mimeType, size, modifiedTime, createdTime, owners, md5Checksum, parents'
        ).execute()
        return file_metadata

    @handle_drive_errors
    def update_file(
        self,
        file_id: str,
        content: Union[str, bytes],
        mime_type: str = "text/plain",
        access_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update a file on Google Drive with new content.

        This method can use either service account credentials (default) or
        a user OAuth token when access_token is provided.

        Args:
            file_id: The ID of the file to update.
            content: The new content (string or bytes).
            mime_type: MIME type of the content.
            access_token: Optional OAuth access token for user-based updates.

        Returns:
            Dict containing updated file metadata (id, name, modifiedTime, md5Checksum).

        Raises:
            Exception: If update fails due to auth, network, or permission issues.
        """
        # Convert string content to bytes if needed
        if isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = content

        # Create media upload object
        media_body = MediaIoBaseUpload(
            io.BytesIO(content_bytes),
            mimetype=mime_type,
            resumable=True
        )

        # Use appropriate service (OAuth or service account)
        if access_token:
            # Build temporary drive service with OAuth token
            from google.oauth2.credentials import Credentials
            user_credentials = Credentials(token=access_token)
            user_drive_service = build('drive', 'v3', credentials=user_credentials, cache_discovery=False)
            drive_service = user_drive_service
            _LOGGER.info(f"Updating file {file_id} using user OAuth token")
        else:
            # Use existing service account credentials
            drive_service = self.drive_service
            _LOGGER.info(f"Updating file {file_id} using service account")

        # Update the file
        updated_file = drive_service.files().update(
            fileId=file_id,
            media_body=media_body,
            fields='id, name, modifiedTime, md5Checksum, size, mimeType'
        ).execute()

        _LOGGER.info(f"File updated successfully: {updated_file['name']} (ID: {file_id})")
        _LOGGER.info(f"  Modified time: {updated_file.get('modifiedTime', 'N/A')}")
        _LOGGER.info(f"  MD5 checksum: {updated_file.get('md5Checksum', 'N/A')}")
        _LOGGER.info(f"  Size: {updated_file.get('size', 'N/A')} bytes")

        return updated_file

    def download_doc(
        self,
        doc_id: str,
        clean: bool = True,
        output_path: Optional[Union[str, Path]] = None,
        parse_frontmatter: bool = True,
        update_figure_paths: bool = True,
        folder_id: Optional[str] = None
    ) -> Any:
        """Download a Google Doc and optionally clean it and save to disk.

        Args:
            doc_id: The ID of the Google Doc to download.
            clean: Whether to apply all cleaning operations.
            output_path: Optional path to save the markdown file.
            parse_frontmatter: Whether to parse frontmatter.
            update_figure_paths: Whether to update SVG paths to converted PDFs.
            folder_id: Optional folder ID to search for figures (uses doc's parent if not provided).

        Returns:
            frontmatter.Post object if parse_frontmatter is True,
            cleaned markdown string otherwise.
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
            _LOGGER.info(f"Also saved to: {output_path}")
        
        # Parse or return raw
        if parse_frontmatter:
            return frontmatter.loads(markdown_content)
        else:
            return markdown_content
    
    def _download_raw_markdown(
        self, doc_id: str, skip_disk_save: bool = False, apply_cleaning: bool = True
    ) -> str:
        """Download markdown from Google Drive with disk caching.

        Internal method that handles caching logic. Caches cleaned content
        by default instead of raw content.

        When the document has suggestions, uses the Docs API with
        suggestionsViewMode='SUGGESTIONS_INLINE' to produce markdown with
        [text]{.changed} markers instead of the standard Drive export.

        Args:
            doc_id: The Google Doc ID.
            skip_disk_save: Whether to skip saving to disk.
            apply_cleaning: Whether to apply cleaning before caching.

        Returns:
            Markdown content as string.
        """
        # Check if document has suggestions — use Docs API path if so
        has_suggestions = self._document_has_suggestions(doc_id)

        # Check disk cache
        disk_content = self._load_from_disk(doc_id, changed=has_suggestions)
        if disk_content is not None:
            return disk_content

        # Need to download from Google Drive. Distinguish a cache miss (no
        # cached copy yet) from an actual change since the last build.
        doc_path = self._get_doc_path(doc_id, changed=has_suggestions)
        if doc_path.exists():
            _LOGGER.info(f"✗ Doc changed since last build - downloading fresh content from Google Drive...")
        else:
            _LOGGER.info(f"⬇ No cached copy yet - downloading content from Google Drive...")
        _LOGGER.info(f"  Document ID: {doc_id}")

        if has_suggestions:
            _LOGGER.info("Document has suggestions — using Docs API with change markers")
            content = self._download_with_changes(doc_id)
        else:
            content = self._download_first_tab(doc_id)


        if apply_cleaning:
            content = clean_markdown(content)
            _LOGGER.info(f"Applied cleaning to document {doc_id} before caching")

        if not skip_disk_save and self.save_to_disk:
            self._save_to_disk(doc_id, content, is_cleaned=apply_cleaning, changed=has_suggestions)

        return content
    
    def _remove_auto_title(self, content: str, doc_id: str) -> str:
        """Remove auto-added document title if present.

        Google Docs export sometimes adds the document title as an H1 heading.
        This method removes it if it matches the document name.

        Args:
            content: The markdown content.
            doc_id: The Google Doc ID for fetching metadata.

        Returns:
            Markdown content with auto-title removed if applicable.
        """
        lines = content.split('\n') if content else []
        if len(lines) >= 2 and lines[0].startswith('# '):
            if lines[1].strip() in ['---', '']:
                metadata = self.get_metadata(doc_id)
                doc_title = metadata.get('name', '')
                first_line_title = lines[0][2:].strip()
                
                if first_line_title == doc_title:
                    _LOGGER.info(f"Removing auto-added title: '{first_line_title}'")
                    if lines[1].strip() == '---':
                        _LOGGER.info("Frontmatter block detected")
                    content = '\n'.join(lines[1:])
                    if content.startswith('\n'):
                        content = content[1:]
        elif content.strip().startswith('---'):
            _LOGGER.info("Frontmatter block detected")
        
        return content


    def _download_first_tab(self, doc_id: str) -> str:
        """Download a Google Doc via the Docs API, first tab only.

        Uses documents.get() which returns only the first tab in the body field,
        then converts to markdown via doc_to_markdown.

        Args:
            doc_id: The Google Doc ID.

        Returns:
            Markdown string.
        """
        if not hasattr(self, 'docs_service'):
            self.docs_service = build('docs', 'v1', credentials=self.credentials, cache_discovery=False)

        _LOGGER.info(f"Fetching document via Docs API (first tab only)...")
        doc = self.docs_service.documents().get(documentId=doc_id).execute()

        content = doc_to_markdown(doc)
        content = self._remove_auto_title(content, doc_id)

        return content

    def _download_with_changes(self, doc_id: str) -> str:
        """Download a Google Doc via the Docs API and convert to markdown with change markers.

        Uses documents.get(suggestionsViewMode='SUGGESTIONS_INLINE') to get structured
        JSON, then converts to markdown where suggested insertions become [text]{.changed}
        and suggested deletions are dropped.

        Args:
            doc_id: The Google Doc ID.

        Returns:
            Markdown string with change markers.
        """
        # Build Google Docs service if not already available
        if not hasattr(self, 'docs_service'):
            self.docs_service = build('docs', 'v1', credentials=self.credentials, cache_discovery=False)

        _LOGGER.info(f"Fetching document via Docs API with inline suggestions...")
        doc = self.docs_service.documents().get(
            documentId=doc_id,
            suggestionsViewMode='SUGGESTIONS_INLINE'
        ).execute()

        content = doc_to_markdown(doc)

        # Remove auto-added title (same logic as the export path)
        content = self._remove_auto_title(content, doc_id)

        return content


    def _document_has_suggestions(self, doc_id: str) -> bool:
        """Check if a Google Doc has any suggested edits.

        Uses the Google Docs API to fetch the document with suggestions inline
        and checks for suggestion markers in the content.

        Args:
            doc_id: The Google Doc ID.

        Returns:
            True if document has suggestions, False otherwise.
        """
        try:
            # Build Google Docs service if not already available
            if not hasattr(self, 'docs_service'):
                self.docs_service = build('docs', 'v1', credentials=self.credentials, cache_discovery=False)
            
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
            _LOGGER.warning(f"Could not check for suggestions using Docs API: {e}")
            _LOGGER.warning("Falling back to standard export (suggestions will not be marked).")
            _LOGGER.warning("Ensure the Google Docs API is enabled and documents.readonly scope is included.")
            return False
    
    def _check_element_for_suggestions(self, element: Dict[str, Any]) -> bool:
        """Recursively check a document element for suggestion markers.

        Args:
            element: A Google Docs API element dict.

        Returns:
            True if any suggestions are found.
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
    
    def _check_for_active_changes(self, doc_id: str) -> None:
        """Check for active suggestions and unresolved comments, warning the user.

        Uses the Google Docs API to check if the document contains suggested edits
        that haven't been accepted or rejected. Also checks for unresolved comments.

        Args:
            doc_id: The Google Doc ID to check.
        """
        try:
            # Get document metadata first
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            
            # Check for suggestions using Google Docs API
            if self._document_has_suggestions(doc_id):
                _LOGGER.info("")
                _LOGGER.info("=" * 70)
                _LOGGER.info("Document has suggested edits — using Docs API with change markers")
                _LOGGER.info(f"Document: {doc_name}")
                _LOGGER.info("Suggested insertions will be marked with [text]{.changed}")
                _LOGGER.info("Suggested deletions will be omitted")
                _LOGGER.info("=" * 70)
                _LOGGER.info("")
            
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
                    _LOGGER.warning("")
                    _LOGGER.warning("=" * 70)
                    _LOGGER.warning("📝 NOTICE: DOCUMENT HAS UNRESOLVED DISCUSSION COMMENTS")
                    _LOGGER.warning("=" * 70)
                    _LOGGER.warning(f"Document: {doc_name}")
                    _LOGGER.warning(f"")
                    _LOGGER.warning(f"Found {len(unresolved_comments)} unresolved comment(s):")
                    _LOGGER.warning("")
                    
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
                                except Exception:
                                    created_str = created[:10] if len(created) >= 10 else 'Unknown date'
                            else:
                                created_str = 'Unknown date'
                            
                            _LOGGER.warning(f"  {i}. [{author_name}, {created_str}]")
                            _LOGGER.warning(f"     \"{content}\"")
                            
                            # Safely check for replies
                            replies = comment.get('replies', [])
                            if isinstance(replies, list) and len(replies) > 0:
                                _LOGGER.warning(f"     ({len(replies)} replies in thread)")
                            _LOGGER.warning("")
                        except Exception as e:
                            # If we can't process a comment, skip it rather than crash
                            _LOGGER.debug(f"Error processing comment {i}: {e}")
                            _LOGGER.warning(f"  {i}. [Error reading comment details]")
                            _LOGGER.warning("")
                    
                    if len(unresolved_comments) > 5:
                        _LOGGER.warning(f"  ... and {len(unresolved_comments) - 5} more comment(s)")
                        _LOGGER.warning("")
                    
                    _LOGGER.warning("Note: These are discussion comments, not suggested edits.")
                    _LOGGER.warning("Review these comments to ensure all feedback is addressed.")
                    _LOGGER.warning("=" * 70)
                    _LOGGER.warning("")
                    
            except Exception as e:
                # Comments API failed, skip the check silently
                _LOGGER.debug(f"Could not check for comments: {e}")
                pass
                
        except Exception as e:
            # Don't fail the download if the check fails, just log a debug message
            _LOGGER.debug(f"Could not check for active changes: {e}")
    
    # ====================
    # Change Detection (modifiedTime)
    # ====================

    def _document_has_changed(self, doc_id: str) -> bool:
        """Check if a Google Doc has changed since it was last cached.

        Compares the document's Drive ``modifiedTime`` against the value stored
        in cache metadata. Unlike the Drive Changes API, ``modifiedTime``
        reflects ANY edit to the file regardless of who made it or whether the
        file lives in the service account's own change feed — which is exactly
        what is needed for docs owned by the user and merely shared with the
        service account.

        Args:
            doc_id: The ID of the document to check.

        Returns:
            True if the document has changed (or we cannot tell), False if the
            cached copy is still current. Fails open: any API error returns True
            so we re-download rather than serve stale content.
        """
        metadata = self.cache_manager.load_metadata(doc_id)
        stored_mtime = metadata.get('document', {}).get('modified_time') if metadata else None

        if not stored_mtime:
            # No stored metadata / no modifiedTime: first run or cleared cache.
            _LOGGER.info("  No stored modifiedTime - treating as changed (first build or cleared cache)")
            return True

        try:
            live_mtime = self.get_metadata(doc_id).get('modifiedTime')
        except Exception as e:
            # Fail open: re-download rather than risk serving a stale copy.
            _LOGGER.warning(f"  Could not fetch modifiedTime ({str(e)[:100]}) - assuming changed (fail open)")
            return True

        changed = live_mtime != stored_mtime
        if changed:
            _LOGGER.info(f"  modifiedTime changed: stored {stored_mtime} -> live {live_mtime} - will re-download")
        else:
            _LOGGER.info(f"  modifiedTime unchanged ({stored_mtime}) - using cached version")
        return changed

    # ====================
    # Disk Cache Operations
    # ====================
    
    def _get_doc_filename(self, doc_id: str, changed: bool = False) -> str:
        """Generate a filename for saving a document to disk.

        Args:
            doc_id: The Google Doc ID.
            changed: If True, return the change-tracked variant filename.

        Returns:
            Sanitized filename with .md extension (or .changed.md for change-tracked).
        """
        _LOGGER.debug(f"_get_doc_filename called with doc_id type={type(doc_id)}, value={doc_id}")

        try:
            metadata = self.get_metadata(doc_id)
            doc_name = metadata.get('name', doc_id)
            _LOGGER.debug(f"Got doc_name type={type(doc_name)}, value={doc_name}")

            # Ensure doc_name is a string before passing to sanitize_filename
            if not isinstance(doc_name, str):
                _LOGGER.warning(f"Document name is not a string: {type(doc_name)} - {doc_name}")
                doc_name = str(doc_name) if doc_name else doc_id

            safe_name = sanitize_filename(doc_name)
            _LOGGER.debug(f"After sanitize_filename: type={type(safe_name)}, value={safe_name}")
        except Exception as e:
            _LOGGER.warning(f"Could not get metadata for doc {doc_id}: {e}")
            # Ensure doc_id is a string
            safe_name = str(doc_id) if not isinstance(doc_id, str) else doc_id
            _LOGGER.debug(f"Exception path - safe_name type={type(safe_name)}, value={safe_name}")

        # Ensure safe_name is a string before calling endswith
        if not isinstance(safe_name, str):
            _LOGGER.error(f"safe_name is not a string: {type(safe_name)} - {safe_name}")
            safe_name = str(safe_name)

        _LOGGER.debug(f"Before endswith check: type={type(safe_name)}, value={repr(safe_name)}")
        if changed:
            if safe_name.endswith('.md'):
                safe_name = safe_name[:-3] + '.changed.md'
            else:
                safe_name += '.changed.md'
        else:
            if not safe_name.endswith('.md'):
                safe_name += '.md'

        _LOGGER.debug(f"_get_doc_filename returning: {safe_name}")
        return safe_name

    def _get_doc_path(self, doc_id: str, changed: bool = False) -> Path:
        """Get the full path where a document would be saved on disk.

        Args:
            doc_id: The Google Doc ID.
            changed: If True, return the change-tracked variant path.

        Returns:
            Full Path to the document cache location.
        """
        return self.cache_manager.get_cache_path(doc_id, 'docs', self._get_doc_filename(doc_id, changed=changed))

    def _load_from_disk(self, doc_id: str, changed: bool = False) -> Optional[str]:
        """Try to load a document from disk cache.

        Checks if the cached version is still valid by comparing the Doc's
        Drive ``modifiedTime`` against the cached value.

        Args:
            doc_id: The Google Doc ID.
            changed: If True, look for the change-tracked variant.

        Returns:
            Cached content if valid, None if cache miss or document changed.
        """
        if not self.save_to_disk:
            return None

        doc_path = self.cache_manager.get_cache_path(doc_id, 'docs', self._get_doc_filename(doc_id, changed=changed))
        if not doc_path.exists():
            return None

        _LOGGER.info(f"Checking for changes in document {doc_id}...")

        # Compare Drive modifiedTime against the cached value
        has_changed = self._document_has_changed(doc_id)
        
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
                    _LOGGER.debug("  Migrated legacy cached file (removed HTML comment)")
                
                return content
            except Exception as e:
                _LOGGER.error(f"Error loading from disk cache: {e}")
                return None
        else:
            # Document has changed, will need to re-download
            _LOGGER.info("  Document has changed - will download fresh copy")
            return None
    
    def _save_to_disk(self, doc_id: str, content: str, is_cleaned: bool = False, changed: bool = False) -> None:
        """Save document content to disk and update metadata.

        Args:
            doc_id: The Google Doc ID.
            content: The markdown content to save.
            is_cleaned: Whether the content has been cleaned.
            changed: If True, save as the change-tracked variant (.changed.md).
        """
        if not self.save_to_disk:
            return

        doc_path = self._get_doc_path(doc_id, changed=changed)
        try:
            doc_path.parent.mkdir(parents=True, exist_ok=True)

            # Save clean content without HTML comments
            doc_path.write_text(content, encoding='utf-8')
            _LOGGER.info(f"Saved to disk: {doc_path}")
            
            # Record modifiedTime and save metadata. The cached modifiedTime is
            # the change-detection signal: a later build compares it against the
            # Doc's live modifiedTime to decide whether to re-download.
            try:
                # Get document metadata
                doc_metadata = self.get_metadata(doc_id)

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
                modified_time = doc_metadata.get('modifiedTime', '')
                metadata['document'].update({
                    'doc_id': doc_id,
                    'doc_name': doc_metadata.get('name', 'Unknown'),
                    'cleaned_state': 'cleaned' if is_cleaned else 'raw',
                    'modified_time': modified_time,
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

                if modified_time:
                    _LOGGER.info(f"  Saved modifiedTime: {modified_time}")
                else:
                    _LOGGER.warning(f"  No modifiedTime from Google Drive API - cache invalidation may not work correctly")

            except Exception as e:
                _LOGGER.warning(f"Error saving metadata (modifiedTime may be lost): {e}")
                
        except Exception as e:
            _LOGGER.error(f"Error saving to disk: {e}")
    
    # ====================
    # SVG Processing
    # ====================
    
    # Note: Legacy SVG folder processing methods have been removed
    # Use process_document_figures() for document-driven figure processing
    # ====================
    # Digest Management (path-based only)
    # ====================
    
    def load_local_digest(self, file_identifier: str, doc_id: str) -> Optional[str]:
        """Load stored digest from local filesystem.

        Delegates to CloudCacheManager.

        Args:
            file_identifier: The file identifier/path.
            doc_id: Document ID for cache context.

        Returns:
            The stored digest, or None if not found.
        """
        return self.cache_manager.load_digest(doc_id, file_identifier)

    def save_local_digest(self, file_identifier: str, digest: str, doc_id: str) -> None:
        """Save digest to local filesystem.

        Delegates to CloudCacheManager.

        Args:
            file_identifier: The file identifier/path.
            digest: The digest to save.
            doc_id: Document ID for cache context.
        """
        self.cache_manager.save_digest(doc_id, file_identifier, digest)
    
    # ====================
    # Document-Driven Figure Processing
    # ====================
    
    def extract_figure_paths(self, markdown_content: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract all figure paths and their parameters from markdown content.

        Delegates to FigureConverter.

        Args:
            markdown_content: The markdown content to parse.

        Returns:
            List of (path, params) tuples for each figure reference.
        """
        return self.figure_converter.extract_figure_paths(markdown_content)

    def _resolve_folder_id(self, doc_id: str, folder_id: Optional[str] = None) -> Optional[str]:
        """Get folder ID from parameter, cache, or document parents.

        Args:
            doc_id: The document ID to resolve folder for.
            folder_id: Optional folder ID if already known.

        Returns:
            The resolved folder ID, or None if not found.
        """
        if folder_id:
            return folder_id

        # Check cached metadata first
        folder_id = self.cache_manager.get_folder_id(doc_id)
        if folder_id:
            return folder_id

        # Fall back to looking up from document parents
        try:
            doc_metadata = self.get_metadata(doc_id)
            parents = doc_metadata.get('parents', [])
            if parents:
                _LOGGER.info(f"Using document's parent folder: {parents[0]}")
                return parents[0]
            else:
                _LOGGER.warning("No parent folder found for document")
        except Exception as e:
            _LOGGER.error(f"Error getting document parent folder: {e}")

        return None

    def find_file_in_drive(self, file_path: str, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find a file by path in a Google Drive folder.

        Args:
            file_path: The file path/name to search for.
            folder_id: The Google Drive folder ID to search in.

        Returns:
            File metadata dict if found, None otherwise.
        """
        filename = Path(file_path).name
        
        try:
            response = self.drive_service.files().list(
                q=f"'{folder_id}' in parents and name='{filename}' and trashed=false",
                fields="files(id, name, mimeType)"
            ).execute()
            
            files = response.get('files', [])
            return files[0] if files else None
        except Exception as e:
            _LOGGER.error(f"Error searching for file {filename}: {e}")
            return None
    
    def _prepare_document_and_folder(
        self, doc_id: str, folder_id: Optional[str]
    ) -> Tuple[str, List, str, Dict]:
        """Prepare document content, determine folder ID, and process bibliography.

        Args:
            doc_id: The Google Doc ID.
            folder_id: Optional folder ID (resolved from doc parents if not provided).

        Returns:
            Tuple of (doc_content, figure_data, folder_id, bibliography_info).
        """
        # Download and read the document (with cleaning to remove embedded images)
        doc_content = self.download_doc(doc_id, clean=True, parse_frontmatter=False, update_figure_paths=False)

        # Extract figure paths with parameters
        figure_data = self.extract_figure_paths(doc_content)
        _LOGGER.info(f"Found {len(figure_data)} figure references in document")

        # Resolve folder ID
        folder_id = self._resolve_folder_id(doc_id, folder_id)

        # Extract bibliography from frontmatter (already unescaped by clean=True)
        bibliography_info = {'bibliography_path': None, 'results': {'processed': [], 'skipped': [], 'failed': []}}
        if folder_id:
            import frontmatter
            doc_post = frontmatter.loads(doc_content)
            bibliography = doc_post.metadata.get('bibliography')

            if bibliography:
                _LOGGER.info(f"Processing bibliography files from frontmatter")
                bibliography_info = self._process_bibliography_files(doc_id, bibliography, folder_id)

        return doc_content, figure_data, folder_id, bibliography_info
    
    def _log_figure_processing_summary(self, results: Dict[str, Any]) -> None:
        """Log summary of figure processing results.

        Args:
            results: Dict with 'processed', 'skipped', and 'failed' lists.
        """
        _LOGGER.info(f"\n=== Figure Processing Complete ===")
        _LOGGER.info(f"✓ Processed: {len(results['processed'])} figures")
        _LOGGER.info(f"⏭ Skipped: {len(results['skipped'])} unchanged figures")
        _LOGGER.info(f"✗ Failed: {len(results['failed'])} figures")
        
        # List failed conversions for clarity
        if results['failed']:
            _LOGGER.warning(f"\n⚠️  The following {len(results['failed'])} files FAILED to convert to PDF:")
            for failed_file in results['failed']:
                _LOGGER.warning(f"   - {failed_file}")
            _LOGGER.warning(f"   Check the error messages above for details on each failure.")
    
    def _get_cached_file_or_download(
        self,
        fig_path: str,
        file_info: Dict[str, Any],
        doc_id: str,
        figure_type: str,
        reference_order: int,
        legend: Optional[str] = None,
        label: Optional[str] = None
    ) -> Path:
        """Get cached file or download if needed.

        Args:
            fig_path: The figure path from the document.
            file_info: File metadata from Google Drive.
            doc_id: The document ID for cache context.
            figure_type: Type of figure ('svg', 'csv', etc.).
            reference_order: Order of appearance in document.
            legend: Figure caption (markdown image alt-text).
            label: Figure id from \\label{...} in the alt-text.

        Returns:
            Path to the source file (cached or newly downloaded).
        """
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
        use_cached = False
        if cached_path.exists() and file_info and 'md5Checksum' in file_info:
            stored_digest = self.figure_converter._load_digest(fig_path, doc_id, 'file')
            if stored_digest == file_info['md5Checksum']:
                _LOGGER.info(f"  Using cached {figure_type.upper()}: {cached_path}")
                use_cached = True

        if not use_cached:
            # Need to download
            _LOGGER.info(f"  Downloading {figure_type.upper()}: {fig_path}")
            self.download_file(file_info['id'], str(cached_path))

        # Record the cached file in metadata (whether newly downloaded or already cached)
        if cached_path.exists():
            self.cache_manager.record_cached_file(
                doc_id=doc_id,
                filename=cached_path.name,
                source_path=fig_path,
                size=cached_path.stat().st_size,
                drive_file_id=file_info['id'],
                digest=file_info.get('md5Checksum'),
                reference_order=reference_order,
                legend=legend,
                label=label
            )

        return cached_path
    
    def _convert_file(
        self,
        fig_path: str,
        source_file: Path,
        file_info: Dict[str, Any],
        params: Dict[str, Any],
        doc_id: str,
        figure_type: str,
        output_path: Path
    ) -> Optional[str]:
        """Convert a file and return the converted path.

        Args:
            fig_path: Original figure path from document.
            source_file: Path to the source file.
            file_info: File metadata from Google Drive.
            params: Conversion parameters from document.
            doc_id: The document ID for cache context.
            figure_type: Type of figure ('svg', 'csv', etc.).
            output_path: Destination path for converted file.

        Returns:
            Path to converted file, or None if conversion failed.
        """
        # Determine the relative path for the output, preserving directory structure
        relative_output_path = f"converted/{fig_path}"
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

                # Return relative path (preserving directory structure from fig_path)
                return fig_path.replace('.svg', '.pdf')
            else:
                _LOGGER.warning(f"⚠️  PDF CONVERSION FAILED for {fig_path}")
                _LOGGER.warning(f"    SVG file exists at: {source_file}")
                _LOGGER.warning(f"    Expected PDF output: {output_path}")
                _LOGGER.warning(f"    Check inkscape installation and SVG file validity")

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
                _LOGGER.warning(f"⚠️  PDF CONVERSION FAILED for {fig_path}")
                _LOGGER.warning(f"    CSV file exists at: {source_file}")
                _LOGGER.warning(f"    Check table_pdf_builder installation")

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

    def process_document_figures(
        self,
        doc_id: str,
        folder_id: Optional[str] = None,
        skip_unchanged: bool = True
    ) -> Dict[str, Any]:
        """Process all figures and bibliography referenced in the document.

        This method processes:
        - SVG files -> PDF conversion
        - CSV files -> PDF table conversion
        - Google Sheets -> PDF table conversion
        - PDF files -> direct download
        - Bibliography files (.bib) -> cache for citation processing

        Args:
            doc_id: The Google Doc ID.
            folder_id: Optional folder ID (uses doc's parent if not provided).
            skip_unchanged: Whether to skip unchanged files based on MD5 checksum.

        Returns:
            Dict with 'document' (updated content), 'results' (processing summary),
            and 'bibliography_info' (bibliography path and results).
        """
        _LOGGER.info(f"Processing figures for document: {doc_id}")

        # Prepare document and determine folder (also processes bibliography during same download)
        doc_content, figure_data, folder_id, bibliography_info = self._prepare_document_and_folder(doc_id, folder_id)
        
        # Prepare list of paths for batch fetching and optimize API calls
        figure_paths = [path for path, _ in figure_data]
        folder_file_cache = self._batch_fetch_folder_metadata(figure_paths, folder_id)
        
        # Process each figure
        results = {'processed': [], 'skipped': [], 'failed': [], 'mapping': {}}

        # Enumerate to track order of appearance (1-indexed)
        for reference_order, (fig_path, params) in enumerate(figure_data, start=1):

            # Legend (caption) and label (\label{...} id) travel inside params
            legend = params.get('legend')
            label = params.get('label')

            # Determine figure type and skip unknown
            figure_type = self.figure_converter.get_figure_type(fig_path)
            if figure_type == 'unknown':
                _LOGGER.info(f"  Skipping unknown file type: {fig_path}")
                continue
            
            # Handle Google Sheets separately
            if figure_type == 'sheet':
                converted_path = self.figure_converter.convert_figure(fig_path, params, doc_id, None)
                if converted_path:
                    _LOGGER.info(f"Converted: {fig_path} -> {converted_path}")
                    results['processed'].append(fig_path)
                    results['mapping'][fig_path] = converted_path
                else:
                    _LOGGER.error(f"  Failed to convert Google Sheet")
                    results['failed'].append(fig_path)
                continue
            
            # Find file in Drive (skip if not found)
            file_info = self._find_file_in_cache(fig_path, folder_file_cache) if folder_id else None
            if not file_info:
                _LOGGER.error(f"  Failed: File not found in Google Drive")
                results['failed'].append(fig_path)
                continue
            
            # Handle PDF files - direct download
            if figure_type == 'pdf':
                try:
                    output_path = Path(fig_path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    self.download_file(file_info['id'], str(output_path))
                    _LOGGER.info(f"  Downloaded: {fig_path}")
                    results['processed'].append(fig_path)
                except Exception as e:
                    _LOGGER.error(f"  Error downloading PDF: {e}")
                    results['failed'].append(fig_path)
                continue
            
            # Handle SVG and CSV files - download and convert
            try:
                output_path = self.figure_converter.get_output_path(fig_path, doc_id, figure_type)
                
                # Check if conversion needed (skip if cached)
                if not self.figure_converter.needs_conversion(fig_path, doc_id, output_path, file_info, params):
                    # Use relative path (preserving directory structure from fig_path)
                    relative_path = fig_path.replace('.svg', '.pdf').replace('.csv', '.pdf')
                    _LOGGER.info(f"Cached: {fig_path} -> {relative_path}")
                    results['skipped'].append(fig_path)
                    results['mapping'][fig_path] = relative_path

                    # Ensure cached figures are recorded in metadata
                    # Record source file if it exists
                    source_file_path = self.cache_manager.cache_root / doc_id / fig_path
                    _LOGGER.info(f"  Checking source file: {source_file_path} exists={source_file_path.exists()}")
                    if source_file_path.exists():
                        self.cache_manager.record_cached_file(
                            doc_id=doc_id,
                            filename=source_file_path.name,
                            source_path=fig_path,
                            size=source_file_path.stat().st_size,
                            drive_file_id=file_info.get('id') if file_info else None,
                            digest=file_info.get('md5Checksum') if file_info else None,
                            reference_order=reference_order,
                            legend=legend,
                            label=label
                        )

                    # Record conversion if it exists
                    if output_path.exists():
                        relative_output_path = f"converted/{fig_path}"
                        if figure_type == 'svg':
                            relative_output_path = relative_output_path.replace('.svg', '.pdf')
                        elif figure_type == 'csv':
                            relative_output_path = relative_output_path.replace('.csv', '.pdf')

                        self.cache_manager.record_conversion(
                            doc_id=doc_id,
                            filename=source_file_path.name if source_file_path.exists() else output_path.name,
                            output_path=relative_output_path,
                            output_size=output_path.stat().st_size,
                            status='success'
                        )

                    continue
                
                # Get source file (cached or download)
                source_file = self._get_cached_file_or_download(fig_path, file_info, doc_id, figure_type, reference_order, legend=legend, label=label)
                
                # Convert file
                converted_path = self._convert_file(fig_path, source_file, file_info, params, doc_id, figure_type, output_path)
                
                if converted_path:
                    _LOGGER.info(f"Converted: {fig_path} -> {converted_path}")
                    results['processed'].append(fig_path)
                    results['mapping'][fig_path] = converted_path
                else:
                    _LOGGER.error(f"  Failed to convert {figure_type} file")
                    results['failed'].append(fig_path)
                    
            except Exception as e:
                _LOGGER.error(f"  Error processing {fig_path}: {str(e)[:200]}")
                results['failed'].append(fig_path)
        
        # Update document with new paths and check for remaining SVGs
        _LOGGER.info(f"DEBUG: Mapping has {len(results['mapping'])} entries:")
        for old_p, new_p in results['mapping'].items():
            _LOGGER.info(f"  {old_p} -> {new_p}")
        updated_content = update_figure_paths(doc_content, results['mapping'])

        import re
        # Match markdown image syntax: ![alt](path.svg) or ![alt](path.svg){params}
        # This captures only actual image paths, not parameter blocks
        remaining_svgs = re.findall(r'!\[[^\]]*\]\(([^)]+\.svg)\)', updated_content)
        if remaining_svgs:
            # Check which are from known failures vs unknown
            failed_set = set(results['failed'])
            unreplaced_from_failures = [svg for svg in remaining_svgs if svg in failed_set]
            unreplaced_unknown = [svg for svg in remaining_svgs if svg not in failed_set]

            if unreplaced_from_failures:
                _LOGGER.warning(f"WARNING: {len(unreplaced_from_failures)} SVG path(s) not replaced due to conversion failures:")
                for svg in unreplaced_from_failures[:5]:
                    _LOGGER.warning(f"  Failed: {svg}")
                if len(unreplaced_from_failures) > 5:
                    _LOGGER.warning(f"  ... and {len(unreplaced_from_failures) - 5} more")

            if unreplaced_unknown:
                _LOGGER.warning(f"WARNING: {len(unreplaced_unknown)} SVG path(s) not replaced for unknown reasons:")
                for svg in unreplaced_unknown[:5]:
                    _LOGGER.warning(f"  Unknown: {svg}")
                if len(unreplaced_unknown) > 5:
                    _LOGGER.warning(f"  ... and {len(unreplaced_unknown) - 5} more")
        
        # Log processing summary
        self._log_figure_processing_summary(results)

        # Enrich metadata with figure reference order
        try:
            doc_path = self._get_doc_path(doc_id)
            if doc_path.exists():
                self.cache_manager.enrich_with_figure_references(doc_id, doc_path)
        except Exception as e:
            _LOGGER.warning(f"Failed to enrich metadata with figure references: {e}")

        return {
            'document': updated_content,
            'results': results,
            'bibliography_info': bibliography_info  # Includes bibliography_path and processing results
        }
    
    def process_document_csvs(
        self,
        doc_id: str,
        folder_id: Optional[str] = None,
        skip_unchanged: bool = True
    ) -> Dict[str, Any]:
        """Download raw CSV data files referenced with {csv/...} syntax.

        This handles CSV files used as data sources (e.g., for jinja templates),
        NOT figure tables. For CSV tables rendered as PDF images, see
        process_document_figures() which handles ![caption](fig/table.csv) syntax.

        Args:
            doc_id: The ID of the Google Doc to process.
            folder_id: Optional folder ID to search for CSV files (uses doc's parent if not provided).
            skip_unchanged: Whether to skip unchanged files based on MD5 checksum.

        Returns:
            Dict with 'csvs' (list of paths found) and 'results' containing
            'processed', 'skipped', and 'failed' lists.
        """
        _LOGGER.info(f"Processing CSV files for document: {doc_id}")
        
        # Download and read the document
        doc_content = self.download_doc(doc_id, clean=False, parse_frontmatter=False, 
                                       update_figure_paths=False)
        
        # Extract CSV paths
        csv_paths = extract_csv_paths(doc_content)
        _LOGGER.info(f"Found {len(csv_paths)} CSV file references in document")
        
        if not csv_paths:
            _LOGGER.info("No CSV files to process")
            return {'csvs': [], 'results': {'processed': [], 'skipped': [], 'failed': []}}

        # Resolve folder ID
        folder_id = self._resolve_folder_id(doc_id, folder_id)

        # Batch fetch metadata
        folder_cache = self._batch_fetch_folder_metadata([], folder_id, csv_paths=csv_paths)
        
        # Process CSVs with doc_id for cache context
        results = self._process_csv_files(csv_paths, folder_cache, skip_unchanged, doc_id)
        
        # Summary
        _LOGGER.info(f"\n=== CSV Processing Complete ===")
        _LOGGER.info(f"✓ Processed: {len(results['processed'])} CSV files")
        _LOGGER.info(f"⏭ Skipped: {len(results['skipped'])} unchanged CSV files")
        _LOGGER.info(f"✗ Failed: {len(results['failed'])} CSV files")
        
        return {
            'csvs': csv_paths,
            'results': results
        }
    
    def _process_csv_files(
        self,
        csv_paths: List[str],
        folder_file_cache: Dict[str, Any],
        skip_unchanged: bool = True,
        doc_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process CSV files referenced in the document.

        Args:
            csv_paths: List of CSV paths to process.
            folder_file_cache: Pre-fetched folder metadata cache.
            skip_unchanged: Whether to skip unchanged files.
            doc_id: Optional document ID for cache context.

        Returns:
            Dict with 'processed', 'skipped', and 'failed' lists.
        """
        results = {'processed': [], 'skipped': [], 'failed': []}
        
        for csv_path in csv_paths:
            _LOGGER.info(f"Processing CSV: {csv_path}")
            
            # Find file in cache
            file_info = self._find_file_in_cache(csv_path, folder_file_cache)
            
            if not file_info:
                _LOGGER.error(f"  Failed: CSV file not found in Google Drive")
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
                    _LOGGER.info(f"  Skipping (unchanged): {csv_path}")
                    results['skipped'].append(csv_path)
                    continue
            
            # Download CSV file
            try:
                self.download_file(file_info['id'], str(local_path))
                _LOGGER.info(f"  Downloaded: {csv_path}")
                results['processed'].append(csv_path)
                
                # Save digest for future cache checks
                if skip_unchanged and remote_digest:
                    self.save_local_digest(csv_path, remote_digest, doc_id) if doc_id else self.save_local_digest(csv_path, remote_digest, 'default')
                    
            except Exception as e:
                _LOGGER.error(f"  Error downloading {csv_path}: {str(e)}")
                results['failed'].append(csv_path)
        
        return results

    def process_document_bibliography(
        self,
        doc_id: str,
        folder_id: Optional[str] = None,
        skip_unchanged: bool = True
    ) -> Dict[str, Any]:
        """Process bibliography files referenced in the document's frontmatter.

        NOTE: This is now a wrapper around process_document_figures() which processes
        bibliography during the same document download. For efficiency, prefer calling
        process_document_figures() directly which returns both figures AND bibliography.

        Args:
            doc_id: The ID of the Google Doc to process.
            folder_id: Optional folder ID to search for bibliography files.
            skip_unchanged: Whether to skip unchanged files based on MD5 checksum.

        Returns:
            Dict with 'bibliography_path' (cached path) and 'results' containing processing outcome.
        """
        # Call process_document_figures which now handles bibliography too
        result = self.process_document_figures(doc_id, folder_id, skip_unchanged)
        # Return just the bibliography info for backwards compatibility
        return result.get('bibliography_info', {'bibliography_path': None, 'results': {'processed': [], 'skipped': [], 'failed': []}})

    def _process_bibliography_files(
        self,
        doc_id: str,
        bibliography: Union[str, List[str]],
        folder_id: str,
        skip_unchanged: bool = True
    ) -> Dict[str, Any]:
        """Process bibliography files (called during document preparation).

        Args:
            doc_id: The ID of the Google Doc.
            bibliography: Bibliography field from frontmatter (string or list).
            folder_id: Folder ID to search for bibliography files.
            skip_unchanged: Whether to skip unchanged files based on MD5 checksum.

        Returns:
            Dict with 'bibliography_path' (cached path or list) and 'results' containing
            processing outcome.
        """
        # Support both string and list of bibliography files
        if isinstance(bibliography, str):
            bib_files = [bibliography]
        elif isinstance(bibliography, list):
            bib_files = bibliography
        else:
            _LOGGER.warning(f"Unexpected bibliography type: {type(bibliography)}")
            return {'bibliography_path': None, 'results': {'processed': [], 'skipped': [], 'failed': []}}

        _LOGGER.info(f"Found {len(bib_files)} bibliography file(s) in frontmatter")

        # Process bibliography files (folder_id already determined by caller)
        results = {'processed': [], 'skipped': [], 'failed': []}
        cached_bib_paths = []

        for bib_path in bib_files:
            _LOGGER.info(f"Processing bibliography: {bib_path}")

            # Search for the bibliography file in the folder
            file_info = self.find_file_in_drive(bib_path, folder_id) if folder_id else None

            if not file_info:
                _LOGGER.error(f"  Failed: Bibliography file not found in Google Drive: {bib_path}")
                results['failed'].append(bib_path)
                continue

            # Create local cache path for the bibliography
            cached_path = self.cache_manager.get_cache_path(doc_id, 'bib', Path(bib_path).name)

            # Ensure the parent directory exists
            cached_path.parent.mkdir(parents=True, exist_ok=True)

            # Store relative path for frontmatter (e.g., "bib/references.bib")
            # This matches the directory structure created by symlinks in build directory
            relative_bib_path = f"bib/{Path(bib_path).name}"

            # Check if unchanged (using MD5 checksum)
            remote_digest = file_info.get('md5Checksum', '')
            if skip_unchanged and remote_digest and cached_path.exists():
                # Check if local file has same digest
                local_digest = self.cache_manager.compute_md5(cached_path)
                if local_digest == remote_digest:
                    _LOGGER.info(f"  Using cached: {relative_bib_path}")
                    results['skipped'].append(bib_path)
                    cached_bib_paths.append(relative_bib_path)

                    # Record in metadata even if skipped
                    self.cache_manager.record_cached_file(
                        doc_id=doc_id,
                        filename=Path(bib_path).name,
                        source_path=f"bib/{Path(bib_path).name}",
                        size=cached_path.stat().st_size,
                        drive_file_id=file_info.get('id'),
                        digest=remote_digest
                    )
                    continue

            # Download bibliography file
            try:
                self.download_file(file_info['id'], str(cached_path))
                _LOGGER.info(f"  Downloaded: {bib_path} -> {cached_path}")
                results['processed'].append(bib_path)
                cached_bib_paths.append(relative_bib_path)

                # Record in cache metadata
                self.cache_manager.record_cached_file(
                    doc_id=doc_id,
                    filename=Path(bib_path).name,
                    source_path=f"bib/{Path(bib_path).name}",
                    size=cached_path.stat().st_size,
                    drive_file_id=file_info.get('id'),
                    digest=remote_digest
                )

            except Exception as e:
                _LOGGER.error(f"  Error downloading {bib_path}: {str(e)}")
                results['failed'].append(bib_path)

        # Summary
        _LOGGER.info(f"\n=== Bibliography Processing Complete ===")
        _LOGGER.info(f"✓ Processed: {len(results['processed'])} bibliography files")
        _LOGGER.info(f"⏭ Skipped: {len(results['skipped'])} unchanged bibliography files")
        _LOGGER.info(f"✗ Failed: {len(results['failed'])} bibliography files")

        # Return the first successful cached path (or list if multiple)
        if len(cached_bib_paths) == 1:
            bibliography_path = cached_bib_paths[0]
        elif len(cached_bib_paths) > 1:
            bibliography_path = cached_bib_paths
        else:
            bibliography_path = None

        return {
            'bibliography_path': bibliography_path,
            'results': results
        }

    def _batch_fetch_folder_metadata(
        self,
        figure_paths: List[str],
        parent_folder_id: str,
        csv_paths: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Pre-fetch metadata for all files in referenced folders.

        Minimizes API calls by fetching all files in each folder once.

        Args:
            figure_paths: List of figure paths to fetch metadata for.
            parent_folder_id: The parent folder ID to search in.
            csv_paths: Optional list of CSV paths to fetch metadata for.

        Returns:
            Dict mapping folder_path -> {filename -> file_info}.
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
        
        folder_cache = {}
        folder_counts = []

        for folder_name in folders_to_fetch:
            if folder_name == '':
                # Root folder
                target_folder_id = parent_folder_id
                cache_key = ''
            else:
                # Find subfolder ID
                subfolder_id = self._find_subfolder_by_name(parent_folder_id, folder_name)
                if not subfolder_id:
                    _LOGGER.warning(f"Subfolder '{folder_name}' not found")
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
            folder_counts.append(f"{folder_name or 'root'} ({len(file_map)})")

        _LOGGER.info(f"Pre-fetched metadata: {', '.join(folder_counts)}")

        return folder_cache
    
    def _list_all_files_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all files (not folders) in a Google Drive folder.

        Args:
            folder_id: The Google Drive folder ID.

        Returns:
            List of file metadata dicts.
        """
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
                _LOGGER.error(f"Error listing files in folder {folder_id}: {e}")
                break
        
        return files
    
    def _find_file_in_cache(
        self, file_path: str, folder_cache: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Find a file in the pre-fetched folder cache.

        Args:
            file_path: The file path to look up.
            folder_cache: Pre-fetched folder metadata cache.

        Returns:
            File metadata dict if found, None otherwise.
        """
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

    def _find_subfolder_by_name(self, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
        """Find a subfolder by name within a parent folder.

        Args:
            parent_folder_id: The parent folder ID.
            subfolder_name: Name of the subfolder to find.

        Returns:
            Subfolder ID if found, None otherwise.
        """
        try:
            response = self.drive_service.files().list(
                q=f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' "
                  f"and name='{subfolder_name}' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            folders = response.get('files', [])
            return folders[0]['id'] if folders else None
        except Exception as e:
            _LOGGER.error(f"Error searching for subfolder {subfolder_name}: {e}")
            return None
    
    def _update_document_figure_paths(
        self,
        markdown_content: str,
        doc_id: str,
        folder_id: Optional[str] = None
    ) -> str:
        """Update figure paths in document content to point to converted PDFs.

        This is a lighter-weight version that just updates paths without processing files.

        Args:
            markdown_content: The markdown content to update.
            doc_id: The document ID (used to find parent folder if needed).
            folder_id: Optional folder ID where figures are located.

        Returns:
            Updated markdown content with figure paths replaced.
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
                _LOGGER.debug(f"Could not get parent folder for doc {doc_id}: {e}")
        
        # Create the path mapping
        path_mapping = create_figure_path_mapping(figure_paths)

        # Update the content with the new paths
        if path_mapping:
            return update_figure_paths(markdown_content, path_mapping)
        
        return markdown_content
    
    def process_document_assets(
        self,
        doc_id: str,
        folder_id: Optional[str] = None,
        skip_unchanged: bool = True
    ) -> Dict[str, Any]:
        """Process all assets (figures and CSV files) referenced in a document.

        This is a wrapper function that handles both figure processing
        (SVG to PDF conversion, PDF downloads) and CSV file downloads.

        Args:
            doc_id: The ID of the Google Doc to process.
            folder_id: Optional folder ID to search for assets (uses doc's parent if not provided).
            skip_unchanged: Whether to skip unchanged files based on MD5 checksum.

        Returns:
            Dict containing:
            - 'document': Updated document content with figure paths replaced
            - 'figures': Results from figure processing
            - 'csvs': Results from CSV processing
            - 'summary': Overall summary statistics
        """
        _LOGGER.info(f"Processing all assets for document: {doc_id}")

        # Resolve folder ID
        folder_id = self._resolve_folder_id(doc_id, folder_id)

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
        _LOGGER.info("\n=== Processing Figures ===")
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
            _LOGGER.error(f"Error processing figures: {e}")
            results['figures'] = {'error': str(e)}
        
        # Process CSV files
        _LOGGER.info("\n=== Processing CSV Files ===")
        try:
            csv_results = self.process_document_csvs(doc_id, folder_id, skip_unchanged)
            results['csvs'] = csv_results['results']
            
            # Update summary
            results['summary']['total_csvs'] = len(csv_results.get('csvs', []))
            results['summary']['csvs_processed'] = len(csv_results['results'].get('processed', []))
            results['summary']['csvs_skipped'] = len(csv_results['results'].get('skipped', []))
            results['summary']['csvs_failed'] = len(csv_results['results'].get('failed', []))
            
        except Exception as e:
            _LOGGER.error(f"Error processing CSV files: {e}")
            results['csvs'] = {'error': str(e)}
        
        # Print summary
        _LOGGER.info("\n" + "=" * 50)
        _LOGGER.info("ASSET PROCESSING COMPLETE")
        _LOGGER.info("=" * 50)
        
        if results['summary']['total_figures'] > 0:
            _LOGGER.info(f"📊 Figures:")
            _LOGGER.info(f"   ✓ Processed: {results['summary']['figures_processed']}")
            _LOGGER.info(f"   ⏭ Skipped: {results['summary']['figures_skipped']}")
            _LOGGER.info(f"   ✗ Failed: {results['summary']['figures_failed']}")
            _LOGGER.info(f"   Total: {results['summary']['total_figures']}")
        
        if results['summary']['total_csvs'] > 0:
            _LOGGER.info(f"📁 CSV Files:")
            _LOGGER.info(f"   ✓ Downloaded: {results['summary']['csvs_processed']}")
            _LOGGER.info(f"   ⏭ Skipped: {results['summary']['csvs_skipped']}")
            _LOGGER.info(f"   ✗ Failed: {results['summary']['csvs_failed']}")
            _LOGGER.info(f"   Total: {results['summary']['total_csvs']}")
        
        if results['summary']['total_figures'] == 0 and results['summary']['total_csvs'] == 0:
            _LOGGER.info("No assets found to process.")
        
        _LOGGER.info("=" * 50)
        
        return results
