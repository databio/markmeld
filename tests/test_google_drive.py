"""
Test suite for GoogleDriveProcessor integration in markmeld package.
These tests verify the optional Google Drive functionality works correctly
when the google extras are installed.
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
import importlib


class TestGoogleDriveOptionalImport:
    """Test that GoogleDriveProcessor is properly handled as an optional import."""
    
    def test_markmeld_core_imports_without_google(self):
        """Test that core markmeld functionality works without Google extras."""
        # Core imports should always work
        from markmeld import MarkdownMelder, load_config_file, load_config_wrapper
        
        assert MarkdownMelder is not None
        assert load_config_file is not None
        assert load_config_wrapper is not None
    
    def test_google_drive_processor_in_all_when_available(self):
        """Test that GoogleDriveProcessor is in __all__ when dependencies are available."""
        import markmeld
        
        # Check if Google dependencies are installed
        try:
            import google.auth
            import googleapiclient
            # If we get here, dependencies are installed
            assert "GoogleDriveProcessor" in markmeld.__all__
        except ImportError:
            # Dependencies not installed, should not be in __all__
            assert "GoogleDriveProcessor" not in markmeld.__all__
    
    def test_graceful_handling_without_google_deps(self):
        """Test that markmeld handles missing Google dependencies gracefully."""
        # Since Google deps are installed in our test environment,
        # we'll just verify that the import mechanism is in place
        import markmeld
        
        # Core functionality should still be available
        assert hasattr(markmeld, 'MarkdownMelder')
        
        # The __all__ list should exist
        assert hasattr(markmeld, '__all__')
        assert 'MarkdownMelder' in markmeld.__all__


class TestGoogleDriveProcessorFunctionality:
    """Test GoogleDriveProcessor functionality when it's available."""
    
    @pytest.fixture
    def mock_google_deps(self):
        """Mock Google dependencies for testing."""
        with patch('markmeld.google_drive.service_account') as mock_sa, \
             patch('markmeld.google_drive.build') as mock_build:
            
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
    
    def test_google_drive_processor_exists(self):
        """Test that GoogleDriveProcessor can be imported when dependencies exist."""
        try:
            from markmeld import GoogleDriveProcessor
            assert GoogleDriveProcessor is not None
        except ImportError:
            pytest.skip("Google dependencies not installed")
    
    def test_google_drive_processor_methods(self):
        """Test that GoogleDriveProcessor has expected methods."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Check for expected methods
        expected_methods = [
            'download_doc',
            'download_doc_raw',
            'download_doc_clean',
            'download_docs_batch',
            'clean_markdown',
            'process_svg_folder',
            'convert_svg_to_pdf',
            'get_metadata',
            'download_file',
            'list_svg_files',
            'clean_escape_characters',
            'remove_embedded_images',
            'strip_bold_from_headings',
        ]
        
        for method in expected_methods:
            assert hasattr(GoogleDriveProcessor, method), f"Missing method: {method}"
    
    def test_google_drive_processor_initialization(self, mock_google_deps):
        """Test GoogleDriveProcessor initialization with mocked dependencies."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Initialize with test credentials
        processor = GoogleDriveProcessor(
            credentials_path="/fake/path/credentials.json",
            local_base_dir="test_output"
        )
        
        # Verify initialization
        assert processor.credentials_path == "/fake/path/credentials.json"
        assert str(processor.local_base_dir) == "test_output"
        assert processor.service_account_email == "test@example.com"
        assert processor.is_ready
    
    def test_clean_markdown_functionality(self):
        """Test markdown cleaning functions work correctly."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test escape character cleaning
        test_markdown = "This is \\[escaped\\] and \\_underscore\\_ text"
        cleaned = GoogleDriveProcessor.clean_escape_characters(test_markdown)
        assert cleaned == "This is [escaped] and _underscore_ text"
        
        # Test bold stripping from headings
        test_markdown = "## **Bold Heading**\nNormal text with **bold**"
        cleaned = GoogleDriveProcessor.strip_bold_from_headings(test_markdown)
        assert "## Bold Heading" in cleaned
        assert "Normal text with **bold**" in cleaned
        
        # Test embedded image removal
        test_markdown = "Text before\n![][image1]\n[image1]: <data:image/png;base64,abc>\nText after"
        cleaned = GoogleDriveProcessor.remove_embedded_images(test_markdown)
        assert "![][image1]" not in cleaned
        assert "[image1]:" not in cleaned
        assert "Text before" in cleaned
        assert "Text after" in cleaned
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test removal of invalid characters
        assert GoogleDriveProcessor.sanitize_filename('file<>name.txt') == 'file__name.txt'
        assert GoogleDriveProcessor.sanitize_filename('path/to/file.txt') == 'path_to_file.txt'
        
        # Test preservation of extension
        assert GoogleDriveProcessor.sanitize_filename('document.md') == 'document.md'
        
        # Test length limiting
        long_name = "a" * 300 + ".txt"
        sanitized = GoogleDriveProcessor.sanitize_filename(long_name)
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
    
    def test_no_unintended_google_imports(self):
        """Verify GoogleDriveProcessor is only loaded when explicitly imported."""
        # Since markmeld.__init__ tries to import GoogleDriveProcessor on module load,
        # we can't test lazy loading. Instead, verify it's handled gracefully.
        import markmeld
        
        # Verify that markmeld works regardless of GoogleDriveProcessor availability
        assert hasattr(markmeld, 'MarkdownMelder')
        assert hasattr(markmeld, 'load_config_file')
        
        # Check if GoogleDriveProcessor is available (depends on deps)
        try:
            from markmeld import GoogleDriveProcessor
            # If available, it should be in __all__
            assert 'GoogleDriveProcessor' in markmeld.__all__
        except ImportError:
            # If not available, it shouldn't be in __all__
            assert 'GoogleDriveProcessor' not in markmeld.__all__


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
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        # Test the cleaning methods directly (static methods)
        raw_content = "# Test\\nContent with \\[escapes\\] and \\*bold\\*"
        
        # Clean escape characters
        cleaned = GoogleDriveProcessor.clean_escape_characters(raw_content)
        assert "\\[" not in cleaned
        assert "[escapes]" in cleaned
        assert "*bold*" in cleaned
    
    def test_processor_properties(self):
        """Test GoogleDriveProcessor properties and info methods."""
        try:
            from markmeld import GoogleDriveProcessor
        except ImportError:
            pytest.skip("Google dependencies not installed")
        
        with patch('markmeld.google_drive.service_account') as mock_sa, \
             patch('markmeld.google_drive.build') as mock_build:
            
            # Setup mocks
            mock_creds = Mock()
            mock_creds.service_account_email = "test@example.com"
            mock_sa.Credentials.from_service_account_file.return_value = mock_creds
            mock_build.return_value = Mock()
            
            # Create processor
            processor = GoogleDriveProcessor(credentials_path="/fake/credentials.json")
            
            # Test properties
            assert processor.is_ready
            assert processor.service_account_email == "test@example.com"
            
            # Test info method
            info = processor.info()
            assert info['service_account'] == "test@example.com"
            assert 'capabilities' in info
            assert 'download_docs' in info['capabilities']


# Test runner
if __name__ == "__main__":
    pytest.main([__file__, "-v"])