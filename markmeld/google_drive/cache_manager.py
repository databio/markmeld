"""Cloud Cache Manager for Google Drive documents and assets.

This module provides centralized cache operations for GoogleDriveProcessor
and FigureConverter, handling document-specific isolation and management.
"""

import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

_LOGGER = logging.getLogger(__name__)


class CloudCacheManager:
    """Centralized cache manager for Google Drive documents and assets.

    Handles all cache operations for GoogleDriveProcessor, providing
    document-specific isolation and centralized management.

    Attributes:
        cache_root: Absolute path to the cache root directory.
        create_dirs: Whether to auto-create directories.
        CACHE_VERSION: Current cache format version ("3.2").
        FILE_CATEGORIES: Mapping of category names to file extensions.
        CONVERSION_TARGETS: Mapping of source extensions to target extensions.
        CACHE_SUBDIRS: Mapping of subdirectory type names to directory names.

    Cache Structure:
        {cache_root}/
        ├── {doc_id_1}/
        │   ├── metadata.json     # Document metadata including folder_id
        │   ├── docs/            # Downloaded markdown documents
        │   ├── converted/       # Document-referenced figures
        │   ├── pdf/             # Bulk SVG→PDF conversion
        │   ├── digest/          # MD5 checksums for change detection
        │   └── csv/             # Downloaded CSV files
        └── {doc_id_2}/
            └── ...
    """

    CACHE_VERSION = "3.2"

    # File type categories
    FILE_CATEGORIES = {
        'figures': ['svg', 'png', 'jpg', 'jpeg', 'gif'],
        'csvs': ['csv'],
        'bibliographies': ['bib']
    }

    # Conversion mappings
    CONVERSION_TARGETS = {
        'svg': 'pdf',
        'csv': 'pdf'
        # png, jpg, etc. don't need conversion
    }

    # Cache subdirectory types
    CACHE_SUBDIRS = {
        'docs': 'docs',           # Cached markdown documents
        'converted': 'converted',  # Modern: document-referenced figures
        'pdf': 'pdf',             # Legacy: bulk SVG folder processing
        'digest': 'digest',       # MD5 checksums for tracking changes
        'csv': 'csv',             # CSV data files
        'fig': 'fig',             # Cached figure source files (SVG, etc.)
        'bib': 'bib'              # Bibliography files
    }

    def __init__(
        self, cache_root: Union[str, Path] = ".cache", create_dirs: bool = True
    ) -> None:
        """Initialize the CloudCacheManager.

        Args:
            cache_root: Path to the cache root directory.
            create_dirs: Whether to auto-create directories.
        """
        # Ensure cache_root is resolved to absolute path
        self.cache_root = Path(cache_root).resolve()
        self.create_dirs = create_dirs
        self._metadata_cache = {}  # In-memory cache for performance
        self._cache_ttl = 300  # 5 minutes TTL
        _LOGGER.info(f"CloudCacheManager initialized with cache_root: {self.cache_root}")

        if self.create_dirs:
            self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Create a .gitignore file to prevent accidental commits
            gitignore_path = self.cache_root / '.gitignore'
            if not gitignore_path.exists():
                gitignore_path.write_text('# Ignore all cache contents\n*\n')

    def get_cache_dir(self, doc_id: str, subdir_type: str) -> Path:
        """Get the cache directory path for a document and subdirectory type.

        Args:
            doc_id: The document ID.
            subdir_type: Type of subdirectory (key from CACHE_SUBDIRS).

        Returns:
            Path to the cache subdirectory.

        Raises:
            ValueError: If subdir_type is not a valid CACHE_SUBDIRS key.

        Example:
            >>> get_cache_dir('doc123', 'docs')
            Path('.cache/doc123/docs')
        """
        if subdir_type not in self.CACHE_SUBDIRS:
            raise ValueError(f"Invalid subdir_type: {subdir_type}. Must be one of {list(self.CACHE_SUBDIRS.keys())}")

        cache_dir = self.cache_root / doc_id / self.CACHE_SUBDIRS[subdir_type]

        if self.create_dirs:
            cache_dir.mkdir(parents=True, exist_ok=True)

        return cache_dir

    def get_cache_path(
        self, doc_id: str, subdir_type: str, filename: Union[str, Path]
    ) -> Path:
        """Get the full cache path for a specific file.

        Args:
            doc_id: The document ID.
            subdir_type: Type of subdirectory (key from CACHE_SUBDIRS).
            filename: Name of the file (can include subdirectories).

        Returns:
            Full absolute path to the cached file.

        Example:
            >>> get_cache_path('doc123', 'docs', 'manuscript.md')
            >>> get_cache_path('doc123', 'converted', 'fig/image.pdf')
        """
        cache_dir = self.get_cache_dir(doc_id, subdir_type)
        file_path = cache_dir / filename

        # Ensure parent directory exists if we're creating nested paths
        if self.create_dirs and '/' in str(filename):
            file_path.parent.mkdir(parents=True, exist_ok=True)

        _LOGGER.debug(f"get_cache_path() returning: {file_path} (is_absolute: {file_path.is_absolute()})")
        return file_path

    def _init_document_metadata(self) -> Dict[str, Any]:
        """Initialize empty document metadata structure.

        Returns:
            Dictionary with all document metadata fields set to None.
        """
        return {
            'doc_id': None,
            'doc_name': None,
            'cleaned_state': None,
            'modified_time': None,
            'folder_id': None,
            'last_accessed': None,
            'created_at': None,
            'filename': None,
            'source_path': None,
            'size': None,
            'downloaded_at': None,
            'digest': None
        }

    def _init_cache_stats(self) -> Dict[str, Any]:
        """Initialize empty cache statistics.

        Returns:
            Dictionary with all cache statistics set to zero/now.
        """
        return {
            'total_files': 0,
            'total_size': 0,
            'figures_count': 0,
            'csvs_count': 0,
            'bibliographies_count': 0,
            'conversions_successful': 0,
            'conversions_failed': 0,
            'conversions_pending': 0,
            'last_updated': datetime.now().isoformat()
        }

    def _get_file_category(self, filename: str) -> Optional[str]:
        """Determine file category based on extension.

        Args:
            filename: Name of the file.

        Returns:
            Category name ('figures', 'csvs', 'bibliographies') or None.
        """
        ext = Path(filename).suffix[1:].lower()
        for category, extensions in self.FILE_CATEGORIES.items():
            if ext in extensions:
                return category
        return None


    def compute_md5(self, file_path: Path) -> str:
        """Compute MD5 hash of a file.

        Args:
            file_path: Path to the file.

        Returns:
            Hexadecimal MD5 digest string.
        """
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _update_cache_stats(self, metadata: Dict[str, Any]) -> None:
        """Update cache_stats section from figures, csvs, and bibliographies.

        Args:
            metadata: Metadata dictionary to update (modified in place).
        """
        all_files = metadata.get('figures', []) + metadata.get('csvs', []) + metadata.get('bibliographies', [])

        # Include document in total if it has size info
        if 'document' in metadata and metadata['document'].get('size'):
            total_size = metadata['document']['size']
            total_files = 1
        else:
            total_size = 0
            total_files = 0

        # Add figure and CSV sizes
        total_size += sum(f.get('size', 0) for f in all_files)
        total_files += len(all_files)

        # Count conversions
        conversions_successful = 0
        conversions_failed = 0
        conversions_pending = 0

        for f in all_files:
            if 'conversion' in f:
                status = f['conversion'].get('status', 'pending')
                if status == 'success':
                    conversions_successful += 1
                    # Add converted file size to total (handle None values)
                    total_size += f['conversion'].get('output_size') or 0
                elif status == 'failed':
                    conversions_failed += 1
                elif status == 'pending':
                    conversions_pending += 1

        metadata['cache_stats'] = {
            'total_files': total_files,
            'total_size': total_size,
            'figures_count': len(metadata.get('figures', [])),
            'csvs_count': len(metadata.get('csvs', [])),
            'bibliographies_count': len(metadata.get('bibliographies', [])),
            'conversions_successful': conversions_successful,
            'conversions_failed': conversions_failed,
            'conversions_pending': conversions_pending,
            'last_updated': datetime.now().isoformat()
        }

    def load_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Load document metadata from cache.

        Only supports v3.0+ format. Includes in-memory caching for performance.

        Args:
            doc_id: The document ID.

        Returns:
            Metadata dictionary, or None if not found or invalid format.
        """
        # Check in-memory cache first
        cache_key = f"metadata_{doc_id}"
        if cache_key in self._metadata_cache:
            cached_time, cached_data = self._metadata_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data

        metadata_path = self.cache_root / doc_id / 'metadata.json'

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Corrupt metadata.json at {metadata_path}: {e}")
            return None
        except IOError as e:
            _LOGGER.error(f"Cannot read metadata.json at {metadata_path}: {e}")
            return None

        # Only support v3.0, v3.1, and v3.2 formats
        cache_version = metadata.get('cache_version')
        if cache_version not in ['3.0', '3.1', '3.2']:
            _LOGGER.warning(f"  Old cache format (v{cache_version}) detected - will rebuild cache with fresh download")
            return None

        # Validate required fields
        required = ['document', 'figures', 'csvs', 'cache_stats', 'cache_version']
        if not all(k in metadata for k in required):
            _LOGGER.warning(f"  Invalid metadata structure - will rebuild cache")
            return None

        # Reject legacy root-level fields (should be nested in 'document')
        if any(k in metadata for k in ('doc_id', 'doc_name', 'folder_id')):
            _LOGGER.warning(f"  Legacy metadata format detected - will rebuild cache")
            return None

        # Cache the result in memory
        self._metadata_cache[cache_key] = (time.time(), metadata)

        return metadata

    def save_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> None:
        """Save document metadata to cache as v3.2 format.

        Merges provided metadata with existing cached metadata to prevent
        partial updates from corrupting existing data (like modified_time).

        Args:
            doc_id: The document ID.
            metadata: Metadata dictionary to save.

        Raises:
            IOError: If metadata file cannot be written.
        """
        metadata_path = self.cache_root / doc_id / 'metadata.json'

        # Load existing metadata from disk for merging
        existing = None
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = None

        # Merge with existing if both have proper v3.x structure
        if existing and 'document' in existing and 'document' in metadata:
            # Copy non-null document fields from metadata to existing
            for key, value in metadata['document'].items():
                if value is not None:
                    existing['document'][key] = value
            # Replace lists if metadata has content (preserves new items)
            for list_key in ('figures', 'csvs', 'bibliographies'):
                if list_key in metadata and metadata[list_key]:
                    existing[list_key] = metadata[list_key]
            # Update cache_stats
            if 'cache_stats' in metadata:
                existing['cache_stats'] = metadata['cache_stats']
            metadata = existing

        # Ensure required structure exists
        if 'document' not in metadata:
            metadata['document'] = self._init_document_metadata()
        if 'figures' not in metadata:
            metadata['figures'] = []
        if 'csvs' not in metadata:
            metadata['csvs'] = []
        if 'bibliographies' not in metadata:
            metadata['bibliographies'] = []
        if 'cache_stats' not in metadata:
            metadata['cache_stats'] = self._init_cache_stats()

        # Always save as v3.2
        metadata['cache_version'] = self.CACHE_VERSION

        # Clean up any legacy root-level fields (doc_id, doc_name, folder_id should be in 'document')
        for field in ('doc_id', 'doc_name', 'folder_id'):
            if field in metadata:
                del metadata[field]

        # Write to file
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2, sort_keys=True)
        except IOError as e:
            _LOGGER.error(f"Failed to save metadata for {doc_id}: {e}")
            raise

        # Update in-memory cache
        cache_key = f"metadata_{doc_id}"
        self._metadata_cache[cache_key] = (time.time(), metadata)

    def update_cached_file(
        self,
        file_path: Path,
        content: Union[str, bytes],
        drive_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update a cached file with new content and metadata.

        Writes new content to the cache file and updates metadata.json with
        new timestamp, MD5, and size. Preserves drive_file_id and source_path.

        Args:
            file_path: Full path to the cache file.
            content: New file content (string or bytes).
            drive_metadata: Optional Drive metadata (id, name, modifiedTime, etc.).
        """
        # Write content to file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = content

        file_path.write_bytes(content_bytes)

        # Calculate new MD5
        new_md5 = hashlib.md5(content_bytes).hexdigest()
        new_size = len(content_bytes)

        _LOGGER.info(f"Updated cache file: {file_path}")
        _LOGGER.info(f"  Size: {new_size} bytes")
        _LOGGER.info(f"  MD5: {new_md5}")

        # Parse cache path to extract doc_id and relative path
        # Expected structure: cache_root/doc_id/subdir/filename
        try:
            relative_to_cache = file_path.relative_to(self.cache_root)
            parts = relative_to_cache.parts

            if len(parts) < 2:
                _LOGGER.warning(f"Cannot update metadata: invalid cache path structure {file_path}")
                return

            doc_id = parts[0]
            source_path = str(Path(*parts[1:]))  # e.g., "bib/references.bib"
            filename = file_path.name

        except ValueError:
            _LOGGER.warning(f"File {file_path} is not in cache root {self.cache_root}")
            return

        # Update metadata
        metadata = self.load_metadata(doc_id)
        if not metadata:
            _LOGGER.warning(f"No metadata found for {doc_id}, cannot update file metadata")
            return

        # Determine file category
        category = self._get_file_category(filename)
        if not category:
            _LOGGER.warning(f"Unknown file type for {filename}, skipping metadata update")
            return

        # Find and update existing file record
        files_list = metadata[category]
        existing = next((f for f in files_list if f['filename'] == filename), None)

        if existing:
            # Update existing record
            existing['size'] = new_size
            existing['digest'] = new_md5
            existing['downloaded_at'] = datetime.now().isoformat()

            # Update Drive metadata if provided
            if drive_metadata:
                if 'id' in drive_metadata:
                    existing['drive_file_id'] = drive_metadata['id']
                if 'modifiedTime' in drive_metadata:
                    existing['modified_time'] = drive_metadata['modifiedTime']

            _LOGGER.info(f"Updated metadata for existing file: {filename}")
        else:
            # Create new record
            file_record = {
                'filename': filename,
                'source_path': source_path,
                'size': new_size,
                'digest': new_md5,
                'downloaded_at': datetime.now().isoformat(),
            }

            # Add Drive metadata if provided
            if drive_metadata:
                if 'id' in drive_metadata:
                    file_record['drive_file_id'] = drive_metadata['id']
                if 'modifiedTime' in drive_metadata:
                    file_record['modified_time'] = drive_metadata['modifiedTime']

            files_list.append(file_record)
            _LOGGER.info(f"Added new file record to metadata: {filename}")

        # Update cache stats
        self._update_cache_stats(metadata)

        # Save updated metadata
        self.save_metadata(doc_id, metadata)

        _LOGGER.info(f"Cache metadata updated for {doc_id}")

    def record_cached_file(
        self,
        doc_id: str,
        filename: str,
        source_path: str,
        size: int,
        drive_file_id: Optional[str] = None,
        digest: Optional[str] = None,
        reference_order: Optional[int] = None,
        first_reference_line: Optional[int] = None,
        reference_count: Optional[int] = None,
    ) -> None:
        """Record that a file was downloaded and cached.

        Args:
            doc_id: Document ID.
            filename: Name of the file.
            source_path: Relative path within cache (e.g., "fig/image.svg").
            size: File size in bytes.
            drive_file_id: Google Drive file ID (if from Drive).
            digest: MD5 hash of file content.
            reference_order: Order of first appearance in text.
            first_reference_line: Line number of first reference.
            reference_count: Total number of references.
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            # Initialize new metadata structure
            metadata = {
                'document': self._init_document_metadata(),
                'figures': [],
                'csvs': [],
                'bibliographies': [],
                'cache_stats': self._init_cache_stats(),
                'cache_version': self.CACHE_VERSION
            }

        # Determine file category
        category = self._get_file_category(filename)
        _LOGGER.info(f"Recording cached file: {filename} -> category: {category}")
        if not category:
            _LOGGER.warning(f"Unknown file type for {filename}, skipping metadata")
            return

        # Create file record
        file_record = {
            'filename': filename,
            'source_path': source_path,
            'size': size,
            'downloaded_at': datetime.now().isoformat(),
        }

        # Add optional fields
        if drive_file_id:
            file_record['drive_file_id'] = drive_file_id
        if digest:
            file_record['digest'] = digest
        if reference_order is not None:
            file_record['reference_order'] = reference_order
        if first_reference_line is not None:
            file_record['first_reference_line'] = first_reference_line
        if reference_count is not None:
            file_record['reference_count'] = reference_count

        # Add format field for figures
        if category == 'figures':
            file_record['format'] = Path(filename).suffix[1:].lower()

        # Add conversion placeholder if file type needs conversion
        ext = Path(filename).suffix[1:].lower()
        if ext in self.CONVERSION_TARGETS:
            file_record['conversion'] = {
                'status': 'pending',
                'output_path': None,
                'output_size': None,
                'converted_at': None,
                'error': None
            }
        else:
            file_record['conversion'] = {
                'status': 'skipped',
                'output_path': None,
                'output_size': None,
                'converted_at': None,
                'error': None
            }

        # Update or append to category
        existing_files = metadata[category]
        existing = next((f for f in existing_files if f['filename'] == filename), None)

        if existing:
            # Update existing record, but preserve downloaded_at if digest unchanged
            old_digest = existing.get('digest')
            old_downloaded_at = existing.get('downloaded_at')

            existing.update(file_record)

            # If digest unchanged, preserve original download timestamp
            if digest and old_digest and digest == old_digest and old_downloaded_at:
                existing['downloaded_at'] = old_downloaded_at
        else:
            # Append new record
            existing_files.append(file_record)

        # Update stats
        self._update_cache_stats(metadata)

        # Save metadata
        self.save_metadata(doc_id, metadata)

        # Clear in-memory cache for this doc
        cache_key = f"metadata_{doc_id}"
        if cache_key in self._metadata_cache:
            del self._metadata_cache[cache_key]

        _LOGGER.info(f"Successfully recorded cached file: {filename} in category {category}")

    def record_conversion(
        self,
        doc_id: str,
        filename: str,
        output_path: Optional[str] = None,
        output_size: Optional[int] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        """Record the result of a file conversion (e.g., SVG -> PDF).

        Args:
            doc_id: Document ID.
            filename: Source filename that was converted.
            output_path: Relative path to converted file.
            output_size: Size of converted file in bytes.
            status: Conversion status ('success', 'failed', 'skipped').
            error: Error message if conversion failed.
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            _LOGGER.error(f"Cannot record conversion for {filename}: no metadata found")
            return

        # Find the file in metadata - check figures, csvs, and bibliographies
        file_record = None
        for category in ['figures', 'csvs', 'bibliographies']:
            if category in metadata:
                file_record = next((f for f in metadata[category] if f['filename'] == filename), None)
                if file_record:
                    break

        if not file_record:
            # Debug: list what files ARE in metadata
            csv_files = [f['filename'] for f in metadata.get('csvs', [])]
            fig_files = [f['filename'] for f in metadata.get('figures', [])]
            _LOGGER.warning(f"Cannot record conversion for {filename}: file not found in metadata")
            _LOGGER.warning(f"  CSVs in metadata: {csv_files}")
            _LOGGER.warning(f"  Figures in metadata: {fig_files}")
            return

        # Update conversion record
        file_record['conversion'] = {
            'status': status,
            'output_path': output_path,
            'output_size': output_size,
            'converted_at': datetime.now().isoformat() if status != 'failed' else None,
            'error': error
        }

        # Update stats
        self._update_cache_stats(metadata)

        # Save metadata
        self.save_metadata(doc_id, metadata)

        # Clear in-memory cache
        cache_key = f"metadata_{doc_id}"
        if cache_key in self._metadata_cache:
            del self._metadata_cache[cache_key]

        _LOGGER.debug(f"Recorded conversion for {filename}: {status}")

    def enrich_with_figure_references(self, doc_id: str, doc_path: Path) -> None:
        """Enrich figure metadata with text reference information.

        Reads the cached markdown document and uses DocumentChecker to find
        where each figure is referenced in the text, then updates figure
        records with first_reference_line and reference_count.

        Matching strategy: figures are matched by reference_order (the Nth
        image definition) to figure_num (the N in "Figure N" in text).

        Args:
            doc_id: Document ID.
            doc_path: Path to the cached markdown document.
        """
        from markmeld.document_checker import DocumentChecker

        metadata = self.load_metadata(doc_id)
        if not metadata or not metadata.get('figures'):
            return

        markdown_content = doc_path.read_text()
        dc = DocumentChecker()
        references = dc.extract_figure_references(markdown_content)

        if not references:
            return

        # Group references by figure_num: {figure_num: [line_num, ...]}
        ref_lines = {}
        for ref in references:
            ref_lines.setdefault(ref.figure_num, []).append(ref.line_num)

        # Match figure records by reference_order to figure_num
        updated = False
        for fig_record in metadata['figures']:
            order = fig_record.get('reference_order')
            if order is None:
                continue

            figure_num = str(order)
            if figure_num not in ref_lines:
                continue

            lines = ref_lines[figure_num]
            fig_record['first_reference_line'] = min(lines)
            fig_record['reference_count'] = len(lines)
            updated = True

        if updated:
            self.save_metadata(doc_id, metadata)
            cache_key = f"metadata_{doc_id}"
            if cache_key in self._metadata_cache:
                del self._metadata_cache[cache_key]
            _LOGGER.debug("Enriched figure metadata with reference info for %s", doc_id)

    def get_cached_files_summary(self, doc_id: str) -> Dict[str, Any]:
        """Get summary of all cached files for a document.

        Args:
            doc_id: The document ID.

        Returns:
            Dictionary with document, figures, csvs, bibliographies,
            and cache_stats, or empty dict if no metadata.
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            return {}

        return {
            'document': metadata.get('document', {}),
            'figures': metadata.get('figures', []),
            'csvs': metadata.get('csvs', []),
            'bibliographies': metadata.get('bibliographies', []),
            'cache_stats': metadata.get('cache_stats', self._init_cache_stats())
        }

    def get_folder_id(self, doc_id: str) -> Optional[str]:
        """Get the folder ID associated with a document from cached metadata.

        Args:
            doc_id: The document ID.

        Returns:
            Folder ID or None if not found.
        """
        metadata = self.load_metadata(doc_id)
        if metadata and 'document' in metadata:
            return metadata['document'].get('folder_id')
        return None

    def ensure_directories(
        self, doc_id: str, subdirs: Optional[List[str]] = None
    ) -> None:
        """Ensure cache directories exist for a document.

        Args:
            doc_id: The document ID.
            subdirs: List of subdirectory types to create (None = all).
        """
        if subdirs is None:
            subdirs = list(self.CACHE_SUBDIRS.keys())

        for subdir_type in subdirs:
            self.get_cache_dir(doc_id, subdir_type)

    def clear_cache(
        self, doc_id: Optional[str] = None, subdirs: Optional[List[str]] = None
    ) -> None:
        """Clear cache for a specific document or all documents.

        Args:
            doc_id: Document ID to clear (None = clear all).
            subdirs: Specific subdirectories to clear (None = all).
        """

        if doc_id is None:
            # Clear entire cache
            if self.cache_root.exists():
                shutil.rmtree(self.cache_root)
                if self.create_dirs:
                    self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        else:
            # Clear specific document
            doc_cache_dir = self.cache_root / doc_id

            if subdirs is None:
                # Clear entire document cache
                if doc_cache_dir.exists():
                    shutil.rmtree(doc_cache_dir)
            else:
                # Clear specific subdirectories
                for subdir_type in subdirs:
                    subdir_path = doc_cache_dir / self.CACHE_SUBDIRS.get(subdir_type, subdir_type)
                    if subdir_path.exists():
                        shutil.rmtree(subdir_path)

    def list_cached_documents(self) -> List[str]:
        """List all document IDs with cache.

        Returns:
            Sorted list of document IDs.
        """
        if not self.cache_root.exists():
            return []

        doc_ids = []
        for item in self.cache_root.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                doc_ids.append(item.name)

        return sorted(doc_ids)

    def get_cache_size(self, doc_id: Optional[str] = None) -> int:
        """Get cache size in bytes for a document or all documents.

        Args:
            doc_id: Document ID (None = total cache size).

        Returns:
            Size in bytes.
        """
        def get_dir_size(path: Path) -> int:
            total = 0
            if path.exists():
                for item in path.rglob('*'):
                    if item.is_file():
                        total += item.stat().st_size
            return total

        if doc_id is None:
            return get_dir_size(self.cache_root)
        else:
            return get_dir_size(self.cache_root / doc_id)

    def prune_cache(self, days_old: int = 30) -> List[str]:
        """Remove cached documents older than specified days.

        Args:
            days_old: Remove documents not accessed in this many days.

        Returns:
            List of pruned document IDs.
        """

        cutoff_date = datetime.now() - timedelta(days=days_old)
        pruned = []

        for doc_id in self.list_cached_documents():
            metadata = self.load_metadata(doc_id)

            if metadata:
                last_accessed = metadata.get('last_accessed')
                if last_accessed:
                    try:
                        access_date = datetime.fromisoformat(last_accessed)
                        if access_date < cutoff_date:
                            doc_dir = self.cache_root / doc_id
                            if doc_dir.exists():
                                shutil.rmtree(doc_dir)
                                pruned.append(doc_id)
                    except (ValueError, TypeError):
                        pass

        return pruned

    def load_digest(self, doc_id: str, file_identifier: str) -> Optional[str]:
        """Load stored digest from local filesystem.

        Automatically handles path structure based on whether file_identifier
        contains paths.

        Args:
            doc_id: Document ID for cache context.
            file_identifier: The file identifier/path.

        Returns:
            The digest string or None if not found.
        """
        # Create digest path that mirrors the original structure
        # Don't use with_suffix as it replaces the last suffix, which breaks .params files
        digest_path = Path(str(file_identifier) + '.digest')
        digest_file = self.get_cache_path(doc_id, 'digest', digest_path)

        if digest_file.exists():
            try:
                return digest_file.read_text().strip()
            except Exception as e:
                _LOGGER.error(f"Error reading digest file {digest_file}: {str(e)}")
                return None

        return None

    def save_digest(self, doc_id: str, file_identifier: str, digest: str) -> None:
        """Save digest to local filesystem.

        Automatically handles path structure based on whether file_identifier
        contains paths.

        Args:
            doc_id: Document ID for cache context.
            file_identifier: The file identifier/path.
            digest: The digest string to save.
        """
        # Create digest path that mirrors the original structure
        # Don't use with_suffix as it replaces the last suffix, which breaks .params files
        digest_path = Path(str(file_identifier) + '.digest')
        digest_file = self.get_cache_path(doc_id, 'digest', digest_path)

        try:
            # Parent directories are created automatically by get_cache_path
            digest_file.write_text(digest)
            _LOGGER.debug(f"Saved digest to {digest_file}: {digest}")
        except Exception as e:
            _LOGGER.error(f"Error saving digest file {digest_file}: {str(e)}")
