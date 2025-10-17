"""
Tests for Google Drive document disk caching functionality.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from pathlib import Path
import tempfile

# Try to import Google Drive dependencies
try:
    from markmeld.google_drive import GoogleDriveProcessor
    from markmeld.cloud_cache_manager import CloudCacheManager
    GOOGLE_DEPS_AVAILABLE = True
except ImportError:
    GOOGLE_DEPS_AVAILABLE = False


@pytest.mark.skipif(not GOOGLE_DEPS_AVAILABLE, reason="Google Drive dependencies not available")
class TestGoogleDriveDiskCache:
    """Test the disk cache functionality of GoogleDriveProcessor."""
    
    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_disk_cache_initialization(self, mock_build, mock_creds):
        """Test that disk cache is properly initialized through cache manager."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_build.return_value = MagicMock()
        
        processor = GoogleDriveProcessor(credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'})

        # Check that cache manager is initialized
        assert hasattr(processor, 'cache_manager')
        assert processor.cache_manager is not None
        # Cache root should be resolved to absolute path
        assert processor.cache_manager.cache_root.is_absolute()
        assert processor.cache_manager.cache_root.name == '.cache'
    
    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    @patch('markmeld.google_drive.MediaIoBaseDownload')
    def test_disk_cache_save_and_load(self, mock_downloader_class, mock_build, mock_creds):
        """Test that documents are saved to and loaded from disk cache."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock the download process
        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)
        mock_downloader_class.return_value = mock_downloader
        
        # Mock export_media to return bytes
        mock_request = MagicMock()
        mock_service.files().export_media.return_value = mock_request
        
        processor = GoogleDriveProcessor(
            credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
            save_to_disk=True
        )
        
        # Mock get_metadata
        processor.get_metadata = MagicMock(return_value={
            'name': 'test_document',
            'modifiedTime': '2024-01-01T10:00:00Z',
            'md5Checksum': 'abc123'
        })
        
        # First download - should save to disk
        with patch('io.BytesIO') as mock_bytesio:
            mock_file = MagicMock()
            mock_file.read.return_value = b"# Test\n\nContent"
            mock_file.seek = MagicMock()
            mock_bytesio.return_value = mock_file
            
            content1 = processor._download_raw_markdown('test_doc_id')
            
        # Check that the document was downloaded
        assert content1 is not None
        
        # Second download - should load from disk if cache is valid
        # Mock _load_from_disk to simulate loading from cache
        with patch.object(processor, '_load_from_disk', return_value="# Test\n\nContent"):
            content2 = processor._download_raw_markdown('test_doc_id')
            
        assert content1 == content2
    
    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_disk_cache_disabled(self, mock_build, mock_creds):
        """Test behavior when disk caching is disabled."""
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_build.return_value = MagicMock()
        
        processor = GoogleDriveProcessor(
            credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
            save_to_disk=False
        )
        
        assert processor.save_to_disk is False
        
        # _load_from_disk should return None when caching is disabled
        result = processor._load_from_disk('any_doc_id')
        assert result is None
    
    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    @patch('markmeld.google_drive.MediaIoBaseDownload')
    def test_disk_cache_invalidation_on_modification(self, mock_downloader_class, mock_build, mock_creds):
        """Test that disk cache is invalidated when document is modified."""
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)
        mock_downloader_class.return_value = mock_downloader
        
        mock_request = MagicMock()
        mock_service.files().export_media.return_value = mock_request
        
        processor = GoogleDriveProcessor(
            credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
            save_to_disk=True
        )
        
        # Initial metadata
        processor.get_metadata = MagicMock(return_value={
            'name': 'test_document',
            'modifiedTime': '2024-01-01T10:00:00Z',
            'md5Checksum': 'abc123'
        })
        
        # First download
        with patch('io.BytesIO') as mock_bytesio:
            mock_file = MagicMock()
            mock_file.read.return_value = b"# Original\n\nContent"
            mock_file.seek = MagicMock()
            mock_bytesio.return_value = mock_file
            
            content1 = processor._download_raw_markdown('test_doc_id')
        
        # Change metadata to simulate modification
        processor.get_metadata = MagicMock(return_value={
            'name': 'test_document',
            'modifiedTime': '2024-01-01T11:00:00Z',  # Changed time
            'md5Checksum': 'def456'  # Changed checksum
        })
        
        # Second download should re-download due to modification
        # The _load_from_disk method should detect the change and return None
        with patch('io.BytesIO') as mock_bytesio:
            mock_file = MagicMock()
            mock_file.read.return_value = b"# Modified\n\nContent"
            mock_file.seek = MagicMock()
            mock_bytesio.return_value = mock_file

            content2 = processor._download_raw_markdown('test_doc_id')

        # Content should be different after modification
        assert "Modified" in content2


def test_cache_manager_resolves_absolute_path():
    """Test that CloudCacheManager resolves cache_root to absolute path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with relative path
        relative_cache = Path("relative/.cache")
        manager = CloudCacheManager(cache_root=relative_cache, create_dirs=False)
        assert manager.cache_root.is_absolute(), "Cache root should be resolved to absolute path"

        # Test with absolute path
        absolute_cache = Path(tmpdir) / ".cache"
        manager = CloudCacheManager(cache_root=str(absolute_cache), create_dirs=False)
        assert manager.cache_root.is_absolute(), "Cache root should remain absolute"
        assert manager.cache_root == absolute_cache.resolve()

        # Test with string path
        string_cache = "test/.cache"
        manager = CloudCacheManager(cache_root=string_cache, create_dirs=False)
        assert manager.cache_root.is_absolute(), "Cache root from string should be resolved to absolute path"