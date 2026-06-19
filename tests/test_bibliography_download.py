"""
Tests for bibliography caching functionality.

Note: Tests for GoogleDriveProcessor.process_document_bibliography() were removed
as that method is just a thin wrapper around process_document_figures() and the
tests were only validating mock return values, not actual behavior.
"""

import pytest
from pathlib import Path
import tempfile

# Try to import Google Drive dependencies
try:
    from markmeld.google_drive import CloudCacheManager
    GOOGLE_DEPS_AVAILABLE = True
except ImportError:
    GOOGLE_DEPS_AVAILABLE = False


class TestCloudCacheManagerBibliography:
    """Test CloudCacheManager bibliography support."""

    def test_cache_version_updated(self):
        """Test that cache version is updated to 3.3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_manager = CloudCacheManager(cache_root=tmpdir)
            assert cache_manager.CACHE_VERSION == "3.3"

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