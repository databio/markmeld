"""
Test suite for GoogleDriveProcessor integration in markmeld package.
These tests verify the optional Google Drive functionality works correctly
when the google extras are installed.
"""

import pytest
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import importlib

from markmeld.google_drive.figure_paths import extract_csv_paths, update_figure_paths


class TestGoogleDriveModuleStructure:
    """Test module structure and imports for Google Drive integration."""

    def test_module_structure(self):
        """Test that markmeld module structure is correct with or without Google deps."""
        import markmeld

        # Core functionality should always be available
        assert hasattr(markmeld, 'MarkdownMelder')
        assert hasattr(markmeld, 'load_config_file')
        assert hasattr(markmeld, 'load_config_wrapper')
        assert hasattr(markmeld, '__all__')
        assert 'MarkdownMelder' in markmeld.__all__

        # GoogleDriveProcessor availability depends on deps
        try:
            import google.auth
            import googleapiclient
            # Deps installed - should be available
            assert "GoogleDriveProcessor" in markmeld.__all__
            from markmeld import GoogleDriveProcessor
            assert GoogleDriveProcessor is not None
            # Check expected methods exist
            for method in ['download_doc', 'process_document_figures',
                          'process_document_assets', 'get_metadata',
                          'download_file', 'extract_figure_paths']:
                assert hasattr(GoogleDriveProcessor, method), f"Missing method: {method}"
        except ImportError:
            # Deps not installed - should not be in __all__
            assert "GoogleDriveProcessor" not in markmeld.__all__


class TestGoogleDriveProcessorFunctionality:
    """Test GoogleDriveProcessor functionality when it's available."""

    @pytest.fixture
    def mock_google_deps(self):
        """Mock Google dependencies for testing."""
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:

            # Mock credentials
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_file.return_value = mock_creds

            # Mock drive service
            mock_service = Mock()
            mock_build.return_value = mock_service

            yield {
                'service_account': mock_sa,
                'build': mock_build,
                'credentials': mock_creds,
                'service': mock_service
            }

    def test_google_drive_processor_initialization(self, mock_google_deps):
        """Test GoogleDriveProcessor initialization with mocked dependencies."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Mock credentials from dict
        mock_google_deps['service_account'].Credentials.from_service_account_info.return_value = mock_google_deps['credentials']
        
        # Initialize with test credentials dict
        test_creds = {
            'type': 'service_account',
            'project_id': 'test-project',
            'client_email': 'test@example.com'
        }
        
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            cache_root="test_cache"
        )

        # Verify initialization
        assert processor.credentials_path is None  # No path when using dict
        # Cache root should be resolved to absolute path
        assert processor.cache_manager.cache_root.is_absolute()
        assert processor.cache_manager.cache_root.name == "test_cache"
        assert processor.service_account_email == "test@example.com"
    
    def test_clean_markdown_functionality(self):
        """Test markdown cleaning functions work correctly."""
        try:
            from markmeld.google_drive.markdown_clean import clean_escape_characters, strip_bold_from_headings, remove_embedded_images
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test escape character cleaning
        test_markdown = "This is \\[escaped\\] and \\_underscore\\_ text"
        cleaned = clean_escape_characters(test_markdown)
        assert cleaned == "This is [escaped] and _underscore_ text"
        
        # Test bold stripping from headings
        test_markdown = "## **Bold Heading**\nNormal text with **bold**"
        cleaned = strip_bold_from_headings(test_markdown)
        assert "## Bold Heading" in cleaned
        assert "Normal text with **bold**" in cleaned
        
        # Test embedded image removal
        test_markdown = "Text before\n![][image1]\n[image1]: <data:image/png;base64,abc>\nText after"
        cleaned = remove_embedded_images(test_markdown)
        assert "![][image1]" not in cleaned
        assert "[image1]:" not in cleaned
        assert "Text before" in cleaned
        assert "Text after" in cleaned
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        try:
            from markmeld.utilities import sanitize_filename
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test removal of invalid characters
        assert sanitize_filename('file<>name.txt') == 'file__name.txt'
        assert sanitize_filename('path/to/file.txt') == 'path_to_file.txt'
        
        # Test preservation of extension
        assert sanitize_filename('document.md') == 'document.md'
        
        # Test length limiting
        long_name = "a" * 300 + ".txt"
        sanitized = sanitize_filename(long_name)
        assert len(sanitized) <= 255
        assert sanitized.endswith(".txt")


class TestGoogleDriveIntegrationWithMarkmeld:
    """Test that GoogleDriveProcessor doesn't interfere with core markmeld."""

    def test_markmeld_basic_functionality_unchanged(self):
        """Test that basic markmeld functionality still works with Google module present."""
        import markmeld

        # Test loading a config file
        cfg = markmeld.load_config_file("tests/test_data/_markmeld_basic.yaml")
        assert cfg is not None

        # Test creating a MarkdownMelder instance
        melder = markmeld.MarkdownMelder(cfg)
        assert melder is not None

        # Test building a target
        result = melder.build_target("default", print_only=True)
        assert result is not None
        assert hasattr(result, 'melded_output')


class TestGoogleDriveProcessorMocked:
    """Test GoogleDriveProcessor with fully mocked Google API calls."""
    
    @pytest.fixture
    def mock_drive_service(self):
        """Create a mock Google Drive service."""
        mock_service = Mock()
        
        # Mock files().export_media() for document downloads
        mock_export = Mock()
        mock_service.files().export_media.return_value = mock_export
        
        # Mock files().get() for metadata
        mock_get = Mock()
        mock_get.execute.return_value = {
            'id': 'test_id',
            'name': 'Test Document',
            'mimeType': 'application/vnd.google-apps.document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        mock_service.files().get.return_value = mock_get
        
        # Mock files().list() for listing files
        mock_list = Mock()
        mock_list.execute.return_value = {
            'files': [
                {'id': 'svg1', 'name': 'figure1.svg', 'md5Checksum': 'abc123'},
                {'id': 'svg2', 'name': 'figure2.svg', 'md5Checksum': 'def456'}
            ]
        }
        mock_service.files().list.return_value = mock_list
        
        return mock_service
    
    def test_download_doc_clean_logic(self):
        """Test the markdown cleaning logic without mocking Google APIs."""
        try:
            from markmeld.google_drive.markdown_clean import clean_escape_characters
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test the cleaning methods directly
        raw_content = "# Test\\nContent with \\[escapes\\] and \\*bold\\*"
        
        # Clean escape characters
        cleaned = clean_escape_characters(raw_content)
        assert "\\[" not in cleaned
        assert "[escapes]" in cleaned
        assert "*bold*" in cleaned
    
    def test_processor_properties(self):
        """Test GoogleDriveProcessor properties and info methods."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_build.return_value = Mock()
            
            # Create processor
            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)
            
            # Test properties
            assert processor.service_account_email == "test@example.com"
    
    def test_update_figure_paths_preserves_parameters(self):
        """Test that _update_figure_paths preserves figure parameters during path updates."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_build.return_value = Mock()
            
            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)
            
            # Test cases with various parameter formats
            test_cases = [
                # (input_markdown, path_mapping, expected_output)
                (
                    "![Figure 1](figure1.svg){width=174mm}",
                    {"figure1.svg": "figure1.pdf"},
                    "![Figure 1](figure1.pdf){width=174mm}"
                ),
                (
                    "![Table](data.csv){width=174mm font-size=6pt}",
                    {"data.csv": "data.pdf"},
                    "![Table](data.pdf){width=174mm font-size=6pt}"
                ),
                (
                    '![Complex](chart.svg){col-widths="20,5,8" col-align="left,center,right"}',
                    {"chart.svg": "chart.pdf"},
                    '![Complex](chart.pdf){col-widths="20,5,8" col-align="left,center,right"}'
                ),
                (
                    "![Empty params](image.png){}",
                    {"image.png": "image.pdf"},
                    "![Empty params](image.pdf){}"
                ),
                (
                    "![No params](regular.jpg) and ![With params](special.svg){width=100px}",
                    {"regular.jpg": "regular.pdf", "special.svg": "special.pdf"},
                    "![No params](regular.pdf) and ![With params](special.pdf){width=100px}"
                ),
                (
                    "Some text before ![Figure](fig.svg){width=50%} and after",
                    {"fig.svg": "fig.pdf"},
                    "Some text before ![Figure](fig.pdf){width=50%} and after"
                ),
                (
                    "Multiple: ![A](a.svg){width=10} ![B](b.svg){height=20} ![C](c.svg){}",
                    {"a.svg": "a.pdf", "b.svg": "b.pdf", "c.svg": "c.pdf"},
                    "Multiple: ![A](a.pdf){width=10} ![B](b.pdf){height=20} ![C](c.pdf){}"
                )
            ]
            
            for input_md, mapping, expected in test_cases:
                result = update_figure_paths(input_md, mapping)
                assert result == expected, f"Failed for input: {input_md}"


class TestGoogleDriveCSVFunctionality:
    """Test CSV file handling functionality in GoogleDriveProcessor."""
    
    def test_extract_csv_paths(self):
        """Test extraction of CSV paths from markdown content."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_build.return_value = Mock()
            
            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)
            
            # Test content with CSV references
            markdown_content = """
            # Document with CSV files
            
            Here's a data file: {csv/data.csv}
            Another one: {csv/subfolder/metrics.csv}
            
            Some text with {csv/results.csv} inline.
            
            Duplicate reference: {csv/data.csv}
            """
            
            csv_paths = extract_csv_paths(markdown_content)

            # Should find unique CSV paths
            assert len(csv_paths) == 3
            assert 'csv/data.csv' in csv_paths
            assert 'csv/subfolder/metrics.csv' in csv_paths
            assert 'csv/results.csv' in csv_paths

    def test_extract_csv_paths_no_csvs(self):
        """Test extraction when no CSV files are referenced."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")

        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:

            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_build.return_value = Mock()

            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)

            # Test content without CSV references
            markdown_content = """
            # Document without CSV files

            Just regular text here.
            Maybe an image: ![alt](fig/image.png)
            """

            csv_paths = extract_csv_paths(markdown_content)
            
            # Should find no CSV paths
            assert len(csv_paths) == 0
    
    def test_process_document_csvs_exists(self):
        """Test that process_document_csvs method exists."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")

        # Check for expected CSV-related methods on processor
        processor_methods = [
            'process_document_csvs',
            '_process_csv_files'
        ]

        for method in processor_methods:
            assert hasattr(GoogleDriveProcessor, method), f"Missing CSV method: {method}"

        # Check for extract_csv_paths in google_drive subpackage
        from markmeld.google_drive import figure_paths
        assert hasattr(figure_paths, 'extract_csv_paths'), "Missing extract_csv_paths in figure_paths"
    
    def test_csv_pattern_matching(self):
        """Test various CSV reference patterns."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_build.return_value = Mock()
            
            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)
            
            # Test various patterns
            test_cases = [
                ("{csv/simple.csv}", ['csv/simple.csv']),
                ("{csv/path/to/file.csv}", ['csv/path/to/file.csv']),
                ("{csv/file-with-dashes.csv}", ['csv/file-with-dashes.csv']),
                ("{csv/file_with_underscores.csv}", ['csv/file_with_underscores.csv']),
                ("{csv/2024_data.csv}", ['csv/2024_data.csv']),
                # Should not match these
                ("{notcsv/file.csv}", []),
                ("{csv/file.txt}", []),
                ("csv/file.csv", []),  # Missing braces
                ("{csv/file.csv", []),  # Missing closing brace
            ]
            
            for content, expected in test_cases:
                result = extract_csv_paths(content)
                assert result == expected, f"Failed for pattern: {content}"


class TestCleanedContentCaching(unittest.TestCase):
    """Test that cleaned content is cached instead of raw content."""
    
    def test_cleaned_content_is_cached(self):
        """Test that _download_raw_markdown caches cleaned content by default."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.processor.service_account') as mock_sa, \
             patch('markmeld.google_drive.processor.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            
            mock_drive_service = Mock()
            mock_files = Mock()
            mock_drive_service.files.return_value = mock_files
            mock_build.return_value = mock_drive_service
            
            test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
            processor = GoogleDriveProcessor(credentials_dict=test_creds)
            
            # Mock the document export with content that needs cleaning
            raw_content = "# Test\\-Title\n\nContent with \\*escaped\\* characters"
            cleaned_content = "# Test-Title\n\nContent with *escaped* characters"
            
            mock_export = Mock()
            mock_files.export_media.return_value = mock_export
            
            # Mock the download process
            mock_downloader = Mock()
            mock_downloader.next_chunk.side_effect = [(Mock(progress=lambda: 1.0), True)]
            
            with patch('markmeld.google_drive.processor.MediaIoBaseDownload') as mock_downloader_class:
                mock_downloader_class.return_value = mock_downloader

                with patch.object(processor, '_remove_auto_title', return_value=raw_content), \
                     patch.object(processor, '_document_has_suggestions', return_value=False):
                    with patch('markmeld.google_drive.processor.io.BytesIO') as mock_io:
                        mock_file = Mock()
                        mock_file.read.return_value = raw_content.encode('utf-8')
                        mock_file.seek = Mock()
                        mock_io.return_value = mock_file

                        # Call _download_raw_markdown with default apply_cleaning=True
                        result = processor._download_raw_markdown('test_doc_id')
                        
                        # Verify that the returned content is cleaned
                        # The result should have escape characters cleaned
                        assert '\\*' not in result
                        assert '\\-' not in result
                        assert '*escaped*' in result
                        assert 'Test-Title' in result


# Test runner
if __name__ == "__main__":
    pytest.main([__file__, "-v"])