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
    from markmeld.google_drive import CloudCacheManager
    GOOGLE_DEPS_AVAILABLE = True
except ImportError:
    GOOGLE_DEPS_AVAILABLE = False


@pytest.mark.skipif(not GOOGLE_DEPS_AVAILABLE, reason="Google Drive dependencies not available")
class TestGoogleDriveDiskCache:
    """Test the disk cache functionality of GoogleDriveProcessor."""
    
    @patch('markmeld.google_drive.processor.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.processor.build')
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
    
    @patch('markmeld.google_drive.processor.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.processor.build')
    @patch('markmeld.google_drive.processor.MediaIoBaseDownload')
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
    
    @patch('markmeld.google_drive.processor.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.processor.build')
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
    
    @patch('markmeld.google_drive.processor.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.processor.build')
    @patch('markmeld.google_drive.processor.MediaIoBaseDownload')
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


class TestCloudCacheManagerMetadataV3:
    """Test the v3.0 metadata functionality of CloudCacheManager."""

    def test_record_cached_file_svg(self):
        """Test recording a cached SVG file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            ccm.record_cached_file(
                doc_id='test_doc',
                filename='image.svg',
                source_path='fig/image.svg',
                size=1234,
                drive_file_id='file123',
                digest='abc123'
            )

            metadata = ccm.load_metadata('test_doc')
            assert metadata is not None
            assert metadata['cache_version'] == '3.2'
            assert 'figures' in metadata
            assert len(metadata['figures']) == 1

            fig = metadata['figures'][0]
            assert fig['filename'] == 'image.svg'
            assert fig['source_path'] == 'fig/image.svg'
            assert fig['size'] == 1234
            assert fig['drive_file_id'] == 'file123'
            assert fig['digest'] == 'abc123'
            assert fig['format'] == 'svg'
            assert fig['conversion']['status'] == 'pending'

    def test_record_cached_file_csv(self):
        """Test recording a cached CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            ccm.record_cached_file(
                doc_id='test_doc',
                filename='data.csv',
                source_path='csv/data.csv',
                size=5678,
                drive_file_id='file456'
            )

            metadata = ccm.load_metadata('test_doc')
            assert metadata is not None
            assert 'csvs' in metadata
            assert len(metadata['csvs']) == 1

            csv = metadata['csvs'][0]
            assert csv['filename'] == 'data.csv'
            assert csv['source_path'] == 'csv/data.csv'
            assert csv['size'] == 5678
            assert csv['conversion']['status'] == 'pending'

    def test_record_cached_file_png_no_conversion(self):
        """Test recording a PNG file that doesn't need conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            ccm.record_cached_file(
                doc_id='test_doc',
                filename='photo.png',
                source_path='fig/photo.png',
                size=9999
            )

            metadata = ccm.load_metadata('test_doc')
            fig = metadata['figures'][0]
            assert fig['conversion']['status'] == 'skipped'

    def test_record_conversion_success(self):
        """Test recording a successful conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # First record the source file
            ccm.record_cached_file(
                doc_id='test_doc',
                filename='image.svg',
                source_path='fig/image.svg',
                size=1234
            )

            # Then record successful conversion
            ccm.record_conversion(
                doc_id='test_doc',
                filename='image.svg',
                output_path='converted/fig/image.pdf',
                output_size=5678,
                status='success'
            )

            metadata = ccm.load_metadata('test_doc')
            fig = metadata['figures'][0]
            assert fig['conversion']['status'] == 'success'
            assert fig['conversion']['output_path'] == 'converted/fig/image.pdf'
            assert fig['conversion']['output_size'] == 5678
            assert fig['conversion']['converted_at'] is not None

    def test_record_conversion_failed(self):
        """Test recording a failed conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            ccm.record_cached_file(
                doc_id='test_doc',
                filename='broken.svg',
                source_path='fig/broken.svg',
                size=100
            )

            ccm.record_conversion(
                doc_id='test_doc',
                filename='broken.svg',
                status='failed',
                error='Inkscape conversion failed'
            )

            metadata = ccm.load_metadata('test_doc')
            fig = metadata['figures'][0]
            assert fig['conversion']['status'] == 'failed'
            assert fig['conversion']['error'] == 'Inkscape conversion failed'
            assert fig['conversion']['converted_at'] is None

    def test_cache_stats_update(self):
        """Test that cache statistics are updated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Add multiple files
            ccm.record_cached_file('test_doc', 'img1.svg', 'fig/img1.svg', 1000)
            ccm.record_cached_file('test_doc', 'img2.png', 'fig/img2.png', 2000)
            ccm.record_cached_file('test_doc', 'data.csv', 'csv/data.csv', 3000)

            # Record successful conversion for SVG
            ccm.record_conversion('test_doc', 'img1.svg', 'converted/fig/img1.pdf', 1500, 'success')

            metadata = ccm.load_metadata('test_doc')
            stats = metadata['cache_stats']

            assert stats['total_files'] == 3
            assert stats['figures_count'] == 2
            assert stats['csvs_count'] == 1
            assert stats['total_size'] == 1000 + 2000 + 3000 + 1500  # Including converted file
            assert stats['conversions_successful'] == 1
            assert stats['conversions_failed'] == 0
            assert stats['conversions_pending'] == 1  # CSV still pending

    def test_no_backward_compatibility_v2(self):
        """Test that v2.0 metadata format is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Create old format metadata (version 2.0)
            import json
            old_metadata = {
                'doc_id': 'test_doc_123',
                'doc_name': 'Test Document',
                'cache_version': '2.0'
            }

            # Manually save old format
            metadata_path = Path(tmpdir) / 'test_doc' / 'metadata.json'
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_path, 'w') as f:
                json.dump(old_metadata, f)

            # Should return None for unsupported version
            loaded = ccm.load_metadata('test_doc')
            assert loaded is None

    def test_corrupt_metadata_handling(self):
        """Test handling of corrupt metadata files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Create corrupt JSON
            metadata_path = Path(tmpdir) / 'test_doc' / 'metadata.json'
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_path, 'w') as f:
                f.write("{invalid json}")

            # Should return None for corrupt file
            loaded = ccm.load_metadata('test_doc')
            assert loaded is None

    def test_in_memory_cache_performance(self):
        """Test that in-memory caching works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Create and save metadata
            ccm.record_cached_file('test_doc', 'test.svg', 'fig/test.svg', 1000)

            # First load - from disk
            metadata1 = ccm.load_metadata('test_doc')

            # Second load - should be from memory cache
            metadata2 = ccm.load_metadata('test_doc')

            assert metadata1 == metadata2
            assert f'metadata_test_doc' in ccm._metadata_cache

    def test_get_cached_files_summary(self):
        """Test getting summary of cached files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Create some test files
            ccm.record_cached_file('test_doc', 'img1.svg', 'fig/img1.svg', 1000)
            ccm.record_cached_file('test_doc', 'data.csv', 'csv/data.csv', 2000)
            ccm.record_conversion('test_doc', 'img1.svg', 'converted/fig/img1.pdf', 1500, 'success')

            summary = ccm.get_cached_files_summary('test_doc')

            assert 'document' in summary
            assert 'figures' in summary
            assert 'csvs' in summary
            assert 'cache_stats' in summary
            assert len(summary['figures']) == 1
            assert len(summary['csvs']) == 1
            assert summary['cache_stats']['conversions_successful'] == 1

    def test_update_existing_file_record(self):
        """Test updating an existing file record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Record file first time
            ccm.record_cached_file('test_doc', 'img.svg', 'fig/img.svg', 1000, digest='old_digest')

            # Record same file again with new digest
            ccm.record_cached_file('test_doc', 'img.svg', 'fig/img.svg', 1100, digest='new_digest')

            metadata = ccm.load_metadata('test_doc')
            # Should have only one figure
            assert len(metadata['figures']) == 1
            # Should have updated values
            fig = metadata['figures'][0]
            assert fig['size'] == 1100
            assert fig['digest'] == 'new_digest'

    def test_get_folder_id_with_v3_metadata(self):
        """Test get_folder_id works with v3.0 metadata structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            # Create v3.0 metadata with folder_id in document section
            metadata = {
                'document': {
                    'doc_id': 'test_doc',
                    'folder_id': 'folder123'
                },
                'figures': [],
                'csvs': [],
                'cache_stats': ccm._init_cache_stats(),
                'cache_version': '3.0'
            }
            ccm.save_metadata('test_doc', metadata)

            folder_id = ccm.get_folder_id('test_doc')
            assert folder_id == 'folder123'

    def test_empty_summary_for_nonexistent_doc(self):
        """Test that get_cached_files_summary returns empty dict for nonexistent doc."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ccm = CloudCacheManager(cache_root=tmpdir)

            summary = ccm.get_cached_files_summary('nonexistent_doc')
            assert summary == {}