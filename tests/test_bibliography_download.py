"""
Tests for bibliography download and caching functionality.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
import tempfile
import json

# Try to import Google Drive dependencies
try:
    from markmeld.google_drive import GoogleDriveProcessor
    from markmeld.cloud_cache_manager import CloudCacheManager
    GOOGLE_DEPS_AVAILABLE = True
except ImportError:
    GOOGLE_DEPS_AVAILABLE = False


@pytest.mark.skipif(not GOOGLE_DEPS_AVAILABLE, reason="Google Drive dependencies not available")
class TestBibliographyDownload:
    """Test the bibliography download functionality of GoogleDriveProcessor."""

    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_process_document_bibliography_no_frontmatter(self, mock_build, mock_creds):
        """Test processing when document has no bibliography in frontmatter."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            processor = GoogleDriveProcessor(
                credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
                cache_root=tmpdir
            )

            # Mock download_doc to return a document without bibliography
            with patch.object(processor, 'download_doc') as mock_download:
                mock_post = MagicMock()
                mock_post.metadata = {}  # No bibliography field
                mock_download.return_value = mock_post

                result = processor.process_document_bibliography('doc123')

                assert result['bibliography_path'] is None
                assert result['results']['processed'] == []
                assert result['results']['skipped'] == []
                assert result['results']['failed'] == []

    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_process_document_bibliography_with_single_bib(self, mock_build, mock_creds):
        """Test processing when document has a single bibliography file."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            processor = GoogleDriveProcessor(
                credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
                cache_root=tmpdir
            )

            # Mock download_doc to return a document with bibliography
            with patch.object(processor, 'download_doc') as mock_download:
                mock_post = MagicMock()
                mock_post.metadata = {'bibliography': 'references.bib'}
                mock_download.return_value = mock_post

                # Mock get_metadata to return parent folder
                with patch.object(processor, 'get_metadata') as mock_get_metadata:
                    mock_get_metadata.return_value = {'parents': ['folder123'], 'name': 'Test Doc'}

                    # Mock find_file_in_drive to find the bib file
                    with patch.object(processor, 'find_file_in_drive') as mock_find:
                        mock_find.return_value = {
                            'id': 'bib_file_id',
                            'name': 'references.bib',
                            'md5Checksum': 'abc123'
                        }

                        # Mock download_file to create a file when called
                        def download_side_effect(file_id, path):
                            Path(path).parent.mkdir(parents=True, exist_ok=True)
                            Path(path).write_text('@article{example2023}')

                        with patch.object(processor, 'download_file') as mock_download_file:
                            mock_download_file.side_effect = download_side_effect
                            result = processor.process_document_bibliography('doc123')

                            # Check that download was attempted
                            mock_download_file.assert_called_once()

                            # Check result structure
                            assert result['bibliography_path'] is not None
                            assert 'references.bib' in result['bibliography_path']
                            assert result['results']['processed'] == ['references.bib']
                            assert result['results']['failed'] == []

    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_process_document_bibliography_with_multiple_bibs(self, mock_build, mock_creds):
        """Test processing when document has multiple bibliography files."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            processor = GoogleDriveProcessor(
                credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
                cache_root=tmpdir
            )

            # Mock download_doc to return a document with multiple bibliographies
            with patch.object(processor, 'download_doc') as mock_download:
                mock_post = MagicMock()
                mock_post.metadata = {'bibliography': ['refs1.bib', 'refs2.bib']}
                mock_download.return_value = mock_post

                # Mock get_metadata to return parent folder
                with patch.object(processor, 'get_metadata') as mock_get_metadata:
                    mock_get_metadata.return_value = {'parents': ['folder123'], 'name': 'Test Doc'}

                    # Mock find_file_in_drive to find both bib files
                    with patch.object(processor, 'find_file_in_drive') as mock_find:
                        def find_side_effect(file_path, folder_id):
                            if 'refs1.bib' in file_path:
                                return {'id': 'bib1_id', 'name': 'refs1.bib', 'md5Checksum': 'hash1'}
                            elif 'refs2.bib' in file_path:
                                return {'id': 'bib2_id', 'name': 'refs2.bib', 'md5Checksum': 'hash2'}
                            return None

                        mock_find.side_effect = find_side_effect

                        # Mock download_file to create files when called
                        def download_side_effect(file_id, path):
                            Path(path).parent.mkdir(parents=True, exist_ok=True)
                            Path(path).write_text(f'@article{{example_{file_id}}}')

                        with patch.object(processor, 'download_file') as mock_download_file:
                            mock_download_file.side_effect = download_side_effect
                            result = processor.process_document_bibliography('doc123')

                            # Check that both downloads were attempted
                            assert mock_download_file.call_count == 2

                            # Check result structure
                            assert isinstance(result['bibliography_path'], list)
                            assert len(result['bibliography_path']) == 2
                            assert result['results']['processed'] == ['refs1.bib', 'refs2.bib']
                            assert result['results']['failed'] == []

    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_process_document_bibliography_file_not_found(self, mock_build, mock_creds):
        """Test processing when bibliography file is not found in Drive."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            processor = GoogleDriveProcessor(
                credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
                cache_root=tmpdir
            )

            # Mock download_doc to return a document with bibliography
            with patch.object(processor, 'download_doc') as mock_download:
                mock_post = MagicMock()
                mock_post.metadata = {'bibliography': 'missing.bib'}
                mock_download.return_value = mock_post

                # Mock get_metadata to return parent folder
                with patch.object(processor, 'get_metadata') as mock_get_metadata:
                    mock_get_metadata.return_value = {'parents': ['folder123'], 'name': 'Test Doc'}

                    # Mock find_file_in_drive to NOT find the bib file
                    with patch.object(processor, 'find_file_in_drive') as mock_find:
                        mock_find.return_value = None

                        result = processor.process_document_bibliography('doc123')

                        # Check result structure
                        assert result['bibliography_path'] is None
                        assert result['results']['processed'] == []
                        assert result['results']['failed'] == ['missing.bib']

    @patch('markmeld.google_drive.service_account.Credentials.from_service_account_info')
    @patch('markmeld.google_drive.build')
    def test_process_document_bibliography_uses_cache(self, mock_build, mock_creds):
        """Test that bibliography files are cached and reused when unchanged."""
        # Setup mocks
        mock_creds.return_value = MagicMock(service_account_email="test@example.com")
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            processor = GoogleDriveProcessor(
                credentials_dict={'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'},
                cache_root=tmpdir
            )

            # Create a cached bib file
            cache_dir = Path(tmpdir) / 'doc123' / 'bib'
            cache_dir.mkdir(parents=True)
            cached_bib = cache_dir / 'references.bib'
            cached_bib.write_text('@article{example2023}')

            # Mock download_doc to return a document with bibliography
            with patch.object(processor, 'download_doc') as mock_download:
                mock_post = MagicMock()
                mock_post.metadata = {'bibliography': 'references.bib'}
                mock_download.return_value = mock_post

                # Mock get_metadata to return parent folder
                with patch.object(processor, 'get_metadata') as mock_get_metadata:
                    mock_get_metadata.return_value = {'parents': ['folder123'], 'name': 'Test Doc'}

                    # Mock find_file_in_drive to find the bib file
                    with patch.object(processor, 'find_file_in_drive') as mock_find:
                        # Mock compute_md5 to return the same hash
                        with patch.object(processor.cache_manager, 'compute_md5') as mock_md5:
                            mock_md5.return_value = 'abc123'
                            mock_find.return_value = {
                                'id': 'bib_file_id',
                                'name': 'references.bib',
                                'md5Checksum': 'abc123'  # Same as computed MD5
                            }

                            # Mock download_file (should not be called)
                            with patch.object(processor, 'download_file') as mock_download_file:
                                result = processor.process_document_bibliography('doc123')

                                # Check that download was NOT attempted (file was cached)
                                mock_download_file.assert_not_called()

                                # Check result structure
                                assert result['bibliography_path'] is not None
                                assert result['results']['processed'] == []
                                assert result['results']['skipped'] == ['references.bib']
                                assert result['results']['failed'] == []


class TestCloudCacheManagerBibliography:
    """Test CloudCacheManager bibliography support."""

    def test_cache_version_updated(self):
        """Test that cache version is updated to 3.2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_manager = CloudCacheManager(cache_root=tmpdir)
            assert cache_manager.CACHE_VERSION == "3.2"

    def test_bibliography_file_category(self):
        """Test that .bib files are recognized as bibliography category."""
        cache_manager = CloudCacheManager(cache_root=".")

        assert cache_manager._get_file_category('references.bib') == 'bibliographies'
        assert cache_manager._get_file_category('paper.bib') == 'bibliographies'
        assert cache_manager._get_file_category('refs.BIB') == 'bibliographies'
        assert cache_manager._get_file_category('document.pdf') is None

    def test_bibliography_cache_subdir(self):
        """Test that bibliography cache subdirectory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_manager = CloudCacheManager(cache_root=tmpdir)

            bib_dir = cache_manager.get_cache_dir('doc123', 'bib')
            assert bib_dir.exists()
            assert bib_dir.name == 'bib'
            assert 'doc123' in str(bib_dir)

    def test_record_bibliography_in_metadata(self):
        """Test that bibliography files are recorded in metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_manager = CloudCacheManager(cache_root=tmpdir)

            # Record a bibliography file
            cache_manager.record_cached_file(
                doc_id='doc123',
                filename='references.bib',
                source_path='bib/references.bib',
                size=1024,
                drive_file_id='bib_id',
                digest='md5hash'
            )

            # Load metadata and check
            metadata = cache_manager.load_metadata('doc123')
            assert metadata is not None
            assert 'bibliographies' in metadata
            assert len(metadata['bibliographies']) == 1
            assert metadata['bibliographies'][0]['filename'] == 'references.bib'
            assert metadata['bibliographies'][0]['size'] == 1024
            assert metadata['cache_stats']['bibliographies_count'] == 1

    def test_get_cached_files_summary_includes_bibliographies(self):
        """Test that get_cached_files_summary includes bibliographies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_manager = CloudCacheManager(cache_root=tmpdir)

            # Record a bibliography file
            cache_manager.record_cached_file(
                doc_id='doc123',
                filename='refs.bib',
                source_path='bib/refs.bib',
                size=2048
            )

            # Get summary
            summary = cache_manager.get_cached_files_summary('doc123')
            assert 'bibliographies' in summary
            assert len(summary['bibliographies']) == 1
            assert summary['cache_stats']['bibliographies_count'] == 1