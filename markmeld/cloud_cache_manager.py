"""
Cloud Cache Manager - Centralized cache management for Google Drive documents and assets.

This module provides cache operations for the GoogleDriveProcessor and FigureConverter,
handling document-specific isolation and centralized management.
"""

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class CloudCacheManager:
    """
    Manages centralized cache for Google Drive documents and assets.

    This class handles all cache operations for the GoogleDriveProcessor,
    providing document-specific isolation and centralized management.

    Cache Structure:
        {cache_root}/
        ├── {doc_id_1}/
        │   ├── metadata.json     # Document metadata including folder_id
        │   ├── docs/            # Downloaded markdown documents
        │   ├── converted/       # Modern: document-referenced figures
        │   ├── pdf/             # Legacy: bulk SVG→PDF conversion
        │   ├── digest/          # MD5 checksums for change detection
        │   └── csv/             # Downloaded CSV files
        └── {doc_id_2}/
            └── ...
    """

    CACHE_VERSION = "3.0"

    # File type categories
    FILE_CATEGORIES = {
        'figures': ['svg', 'png', 'jpg', 'jpeg', 'gif'],
        'csvs': ['csv']
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
        'fig': 'fig'              # Cached figure source files (SVG, etc.)
    }
    
    def __init__(self, cache_root: Union[str, Path] = ".cache", create_dirs: bool = True):
        """
        Initialize the CloudCacheManager.

        Args:
            cache_root: Path to the cache root directory (default: ".cache")
            create_dirs: Whether to auto-create directories (default: True)
        """
        # Ensure cache_root is resolved to absolute path
        self.cache_root = Path(cache_root).resolve()
        self.create_dirs = create_dirs
        self._metadata_cache = {}  # In-memory cache for performance
        self._cache_ttl = 300  # 5 minutes TTL
        logger.info(f"CloudCacheManager initialized with cache_root: {self.cache_root}")

        if self.create_dirs:
            self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Create a .gitignore file to prevent accidental commits
            gitignore_path = self.cache_root / '.gitignore'
            if not gitignore_path.exists():
                gitignore_path.write_text('# Ignore all cache contents\n*\n')
    
    def get_cache_dir(self, doc_id: str, subdir_type: str) -> Path:
        """
        Get the cache directory path for a specific document and subdirectory type.
        
        Args:
            doc_id: The document ID
            subdir_type: Type of subdirectory (from CACHE_SUBDIRS keys)
            
        Returns:
            Path to the cache subdirectory
            
        Example:
            get_cache_dir('doc123', 'docs') -> Path('.cache/doc123/docs')
        """
        if subdir_type not in self.CACHE_SUBDIRS:
            raise ValueError(f"Invalid subdir_type: {subdir_type}. Must be one of {list(self.CACHE_SUBDIRS.keys())}")
        
        cache_dir = self.cache_root / doc_id / self.CACHE_SUBDIRS[subdir_type]
        
        if self.create_dirs:
            cache_dir.mkdir(parents=True, exist_ok=True)
        
        return cache_dir
    
    def get_cache_path(self, doc_id: str, subdir_type: str, filename: Union[str, Path]) -> Path:
        """
        Get the full cache path for a specific file.

        Args:
            doc_id: The document ID
            subdir_type: Type of subdirectory (from CACHE_SUBDIRS keys)
            filename: Name of the file (can include subdirectories)

        Returns:
            Full path to the cached file

        Examples:
            get_cache_path('doc123', 'docs', 'manuscript.md')
            get_cache_path('doc123', 'converted', 'fig/image.pdf')
        """
        cache_dir = self.get_cache_dir(doc_id, subdir_type)
        file_path = cache_dir / filename

        # Ensure parent directory exists if we're creating nested paths
        if self.create_dirs and '/' in str(filename):
            file_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(f"get_cache_path() returning: {file_path} (is_absolute: {file_path.is_absolute()})")
        return file_path

    def _init_document_metadata(self) -> Dict[str, Any]:
        """Initialize empty document metadata structure."""
        return {
            'doc_id': None,
            'doc_name': None,
            'change_token': None,
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
        """Initialize empty cache stats."""
        return {
            'total_files': 0,
            'total_size': 0,
            'figures_count': 0,
            'csvs_count': 0,
            'conversions_successful': 0,
            'conversions_failed': 0,
            'conversions_pending': 0,
            'last_updated': datetime.now().isoformat()
        }

    def _get_file_category(self, filename: str) -> Optional[str]:
        """Determine which category a file belongs to based on extension."""
        ext = Path(filename).suffix[1:].lower()
        for category, extensions in self.FILE_CATEGORIES.items():
            if ext in extensions:
                return category
        return None

    def compute_md5(self, file_path: Path) -> str:
        """Compute MD5 hash of a file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _update_cache_stats(self, metadata: Dict[str, Any]) -> None:
        """Update the cache_stats section based on figures and csvs."""
        all_files = metadata.get('figures', []) + metadata.get('csvs', [])

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
                    # Add converted file size to total
                    total_size += f['conversion'].get('output_size', 0)
                elif status == 'failed':
                    conversions_failed += 1
                elif status == 'pending':
                    conversions_pending += 1

        metadata['cache_stats'] = {
            'total_files': total_files,
            'total_size': total_size,
            'figures_count': len(metadata.get('figures', [])),
            'csvs_count': len(metadata.get('csvs', [])),
            'conversions_successful': conversions_successful,
            'conversions_failed': conversions_failed,
            'conversions_pending': conversions_pending,
            'last_updated': datetime.now().isoformat()
        }

    def load_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Load document metadata from cache. ONLY supports v3.0 format.
        Includes in-memory caching for performance.
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
            logger.error(f"Corrupt metadata.json at {metadata_path}: {e}")
            return None
        except IOError as e:
            logger.error(f"Cannot read metadata.json at {metadata_path}: {e}")
            return None

        # REQUIRE v3.0 format - NO BACKWARD COMPATIBILITY
        if metadata.get('cache_version') != '3.0':
            logger.error(f"Unsupported metadata version for {doc_id}: {metadata.get('cache_version')}. Rebuild cache required.")
            return None

        # Validate required fields
        required = ['document', 'figures', 'csvs', 'cache_stats', 'cache_version']
        if not all(k in metadata for k in required):
            logger.error(f"Invalid metadata structure at {metadata_path}: missing required fields")
            return None

        # Cache the result in memory
        self._metadata_cache[cache_key] = (time.time(), metadata)

        return metadata

    def save_metadata(self, doc_id: str, metadata: Dict[str, Any]):
        """Save document metadata to cache. Always saves as v3.0 format."""
        # Ensure required structure exists
        if 'document' not in metadata:
            metadata['document'] = self._init_document_metadata()
        if 'figures' not in metadata:
            metadata['figures'] = []
        if 'csvs' not in metadata:
            metadata['csvs'] = []
        if 'cache_stats' not in metadata:
            metadata['cache_stats'] = self._init_cache_stats()

        # Always save as v3.0
        metadata['cache_version'] = self.CACHE_VERSION

        # Write to file
        metadata_path = self.cache_root / doc_id / 'metadata.json'
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2, sort_keys=True)
        except IOError as e:
            logger.error(f"Failed to save metadata for {doc_id}: {e}")
            raise

        # Update in-memory cache
        cache_key = f"metadata_{doc_id}"
        self._metadata_cache[cache_key] = (time.time(), metadata)

    def record_cached_file(
        self,
        doc_id: str,
        filename: str,
        source_path: str,
        size: int,
        drive_file_id: Optional[str] = None,
        digest: Optional[str] = None
    ) -> None:
        """
        Record that a file was downloaded and cached.

        Args:
            doc_id: Document ID
            filename: Name of the file
            source_path: Relative path within cache (e.g., "fig/image.svg")
            size: File size in bytes
            drive_file_id: Google Drive file ID (if from Drive)
            digest: MD5 hash of file content
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            # Initialize new metadata structure
            metadata = {
                'document': self._init_document_metadata(),
                'figures': [],
                'csvs': [],
                'cache_stats': self._init_cache_stats(),
                'cache_version': self.CACHE_VERSION
            }

        # Determine file category
        category = self._get_file_category(filename)
        if not category:
            logger.warning(f"Unknown file type for {filename}, skipping metadata")
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
            # Update existing record
            existing.update(file_record)
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

        logger.debug(f"Recorded cached file: {filename} in category {category}")

    def record_conversion(
        self,
        doc_id: str,
        filename: str,
        output_path: Optional[str] = None,
        output_size: Optional[int] = None,
        status: str = 'success',
        error: Optional[str] = None
    ) -> None:
        """
        Record the result of a file conversion (e.g., SVG → PDF).

        Args:
            doc_id: Document ID
            filename: Source filename that was converted
            output_path: Relative path to converted file
            output_size: Size of converted file in bytes
            status: Conversion status ('success', 'failed', 'skipped')
            error: Error message if conversion failed
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            logger.error(f"Cannot record conversion for {filename}: no metadata found")
            return

        # Find the file in metadata - check both figures and csvs
        file_record = None
        for category in ['figures', 'csvs']:
            if category in metadata:
                file_record = next((f for f in metadata[category] if f['filename'] == filename), None)
                if file_record:
                    break

        if not file_record:
            logger.warning(f"Cannot record conversion for {filename}: file not found in metadata")
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

        logger.debug(f"Recorded conversion for {filename}: {status}")

    def get_cached_files_summary(self, doc_id: str) -> Dict[str, Any]:
        """
        Get summary of all cached files for a document.

        Returns:
            Dictionary with document, figures, csvs, and cache_stats, or empty dict if no metadata
        """
        metadata = self.load_metadata(doc_id)
        if not metadata:
            return {}

        return {
            'document': metadata.get('document', {}),
            'figures': metadata.get('figures', []),
            'csvs': metadata.get('csvs', []),
            'cache_stats': metadata.get('cache_stats', self._init_cache_stats())
        }

    def get_folder_id(self, doc_id: str) -> Optional[str]:
        """
        Get the folder ID associated with a document from cached metadata.

        Args:
            doc_id: The document ID

        Returns:
            Folder ID or None if not found
        """
        metadata = self.load_metadata(doc_id)
        if metadata and 'document' in metadata:
            return metadata['document'].get('folder_id')
        return None
    
    def ensure_directories(self, doc_id: str, subdirs: Optional[List[str]] = None):
        """
        Ensure cache directories exist for a document.
        
        Args:
            doc_id: The document ID
            subdirs: List of subdirectory types to create (None = all)
        """
        if subdirs is None:
            subdirs = list(self.CACHE_SUBDIRS.keys())
        
        for subdir_type in subdirs:
            self.get_cache_dir(doc_id, subdir_type)
    
    def clear_cache(self, doc_id: Optional[str] = None, subdirs: Optional[List[str]] = None):
        """
        Clear cache for a specific document or all documents.
        
        Args:
            doc_id: Document ID to clear (None = clear all)
            subdirs: Specific subdirectories to clear (None = all)
        """
        import shutil
        
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
        """
        List all document IDs with cache.
        
        Returns:
            List of document IDs
        """
        if not self.cache_root.exists():
            return []
        
        doc_ids = []
        for item in self.cache_root.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                doc_ids.append(item.name)
        
        return sorted(doc_ids)
    
    def get_cache_size(self, doc_id: Optional[str] = None) -> int:
        """
        Get cache size in bytes for a document or all documents.
        
        Args:
            doc_id: Document ID (None = total cache size)
            
        Returns:
            Size in bytes
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
        """
        Remove cached documents older than specified days.
        
        Args:
            days_old: Remove documents not accessed in this many days
            
        Returns:
            List of pruned document IDs
        """
        import shutil
        from datetime import datetime, timedelta
        
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
        """
        Load stored digest from local filesystem.
        Automatically handles path structure based on whether file_identifier contains paths.
        
        Args:
            doc_id: Document ID for cache context
            file_identifier: The file identifier/path
        
        Returns:
            The digest string or None if not found
        """
        # Create digest path that mirrors the original structure
        # Don't use with_suffix as it replaces the last suffix, which breaks .params files
        digest_path = Path(str(file_identifier) + '.digest')
        digest_file = self.get_cache_path(doc_id, 'digest', digest_path)
        
        if digest_file.exists():
            try:
                return digest_file.read_text().strip()
            except Exception as e:
                logger.error(f"Error reading digest file {digest_file}: {str(e)}")
                return None
        
        return None
    
    def save_digest(self, doc_id: str, file_identifier: str, digest: str):
        """
        Save digest to local filesystem.
        Automatically handles path structure based on whether file_identifier contains paths.
        
        Args:
            doc_id: Document ID for cache context
            file_identifier: The file identifier/path
            digest: The digest to save
        """
        # Create digest path that mirrors the original structure
        # Don't use with_suffix as it replaces the last suffix, which breaks .params files
        digest_path = Path(str(file_identifier) + '.digest')
        digest_file = self.get_cache_path(doc_id, 'digest', digest_path)
        
        try:
            # Parent directories are created automatically by get_cache_path
            digest_file.write_text(digest)
            logger.debug(f"Saved digest to {digest_file}: {digest}")
        except Exception as e:
            logger.error(f"Error saving digest file {digest_file}: {str(e)}")