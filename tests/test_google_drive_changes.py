"""
Unit tests for the Google Drive active changes detection feature.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from markmeld.google_drive import GoogleDriveProcessor

class TestActiveChangesDetection:
    """Test the active changes detection functionality."""
    
    @patch('markmeld.google_drive.service_account.Credentials')
    @patch('markmeld.google_drive.build')
    def test_check_for_active_changes_with_unpublished_revision(self, mock_build, mock_creds):
        """Test warning when document has unpublished revisions."""
        
        # Mock the Google Drive service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_file.return_value = mock_creds_instance
        
        # Create processor
        processor = GoogleDriveProcessor(
            credentials_path="dummy_path.json",
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock revisions response with unpublished revision
        mock_service.revisions().list().execute.return_value = {
            'revisions': [
                {'id': '1', 'published': True},
                {'id': '2', 'published': False}  # Unpublished revision
            ]
        }
        
        # Capture log output
        with patch('markmeld.google_drive.logger') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify warning was logged
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'DOCUMENT HAS ACTIVE CHANGES' in str(call)]
            assert len(warning_calls) > 0, "Expected warning about active changes"
    
    @patch('markmeld.google_drive.service_account.Credentials')
    @patch('markmeld.google_drive.build')
    def test_check_for_active_changes_with_unresolved_comments(self, mock_build, mock_creds):
        """Test warning when document has unresolved comments."""
        
        # Mock the Google Drive service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_file.return_value = mock_creds_instance
        
        # Create processor
        processor = GoogleDriveProcessor(
            credentials_path="dummy_path.json",
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock revisions to fail (simulating lack of permissions)
        mock_service.revisions().list().execute.side_effect = Exception("No permission")
        
        # Mock comments response with unresolved comments
        mock_service.comments().list().execute.return_value = {
            'comments': [
                {'resolved': False},
                {'resolved': False},
                {'resolved': True}
            ]
        }
        
        # Capture log output
        with patch('markmeld.google_drive.logger') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify warning was logged
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'UNRESOLVED COMMENTS' in str(call)]
            assert len(warning_calls) > 0, "Expected warning about unresolved comments"
    
    @patch('markmeld.google_drive.service_account.Credentials')
    @patch('markmeld.google_drive.build')
    def test_check_for_active_changes_no_issues(self, mock_build, mock_creds):
        """Test no warning when document has no active changes."""
        
        # Mock the Google Drive service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_file.return_value = mock_creds_instance
        
        # Create processor
        processor = GoogleDriveProcessor(
            credentials_path="dummy_path.json",
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock revisions response with all published
        mock_service.revisions().list().execute.return_value = {
            'revisions': [
                {'id': '1', 'published': True},
                {'id': '2', 'published': True}  # All published
            ]
        }
        
        # Capture log output
        with patch('markmeld.google_drive.logger') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify no warning was logged
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'WARNING' in str(call)]
            assert len(warning_calls) == 0, "Should not warn when no active changes"
    
    @patch('markmeld.google_drive.service_account.Credentials')
    @patch('markmeld.google_drive.build')
    def test_check_continues_on_api_failure(self, mock_build, mock_creds):
        """Test that document download continues even if change detection fails."""
        
        # Mock the Google Drive service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_file.return_value = mock_creds_instance
        
        # Create processor
        processor = GoogleDriveProcessor(
            credentials_path="dummy_path.json",
            save_to_disk=False
        )
        
        # Make metadata call fail
        mock_service.files().get().execute.side_effect = Exception("API error")
        
        # This should not raise an exception
        try:
            processor._check_for_active_changes('test_doc_id')
        except Exception:
            pytest.fail("Check for active changes should not raise exceptions")