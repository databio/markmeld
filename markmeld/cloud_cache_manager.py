"""
Cloud Cache Manager - Centralized cache management for Google Drive documents and assets.

This module provides cache operations for the GoogleDriveProcessor and FigureConverter,
handling document-specific isolation and centralized management.
"""

import json
import logging
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
        self.cache_root = Path(cache_root)
        self.create_dirs = create_dirs
        
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
        
        return file_path
    
    def save_metadata(self, doc_id: str, metadata: Dict[str, Any]):
        """
        Save document metadata to cache.
        Merges new metadata with existing metadata to preserve fields.
        
        Args:
            doc_id: The document ID
            metadata: Metadata dictionary to save (will be merged with existing)
        """
        metadata_path = self.cache_root / doc_id / 'metadata.json'
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing metadata first
        existing = {}
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        # Merge with existing metadata (new values override)
        existing.update(metadata)
        metadata = existing
        
        # Add timestamp
        metadata['last_accessed'] = datetime.now().isoformat()
        if 'created_at' not in metadata:
            metadata['created_at'] = datetime.now().isoformat()
        if 'cache_version' not in metadata:
            metadata['cache_version'] = '2.0'  # Bump version for new changes API support
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def load_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Load document metadata from cache.
        
        Args:
            doc_id: The document ID
            
        Returns:
            Metadata dictionary or None if not found
        """
        metadata_path = self.cache_root / doc_id / 'metadata.json'
        
        if not metadata_path.exists():
            return None
        
        try:
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def get_folder_id(self, doc_id: str) -> Optional[str]:
        """
        Get the folder ID associated with a document from cached metadata.
        
        Args:
            doc_id: The document ID
            
        Returns:
            Folder ID or None if not found
        """
        metadata = self.load_metadata(doc_id)
        return metadata.get('folder_id') if metadata else None
    
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