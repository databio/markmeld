"""
Unit tests for the Google Drive active changes detection feature.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from markmeld.google_drive import GoogleDriveProcessor

class TestActiveChangesDetection:
    """Test the active changes detection functionality."""
    
    @patch('markmeld.google_drive.processor.service_account.Credentials')
    @patch('markmeld.google_drive.processor.build')
    def test_check_for_active_changes_with_suggestions(self, mock_build, mock_creds):
        """Test warning when document has suggested edits."""
        
        # Mock the Google Drive and Docs services
        mock_drive_service = MagicMock()
        mock_docs_service = MagicMock()
        
        def build_side_effect(service_name, version, credentials=None, **kwargs):
            if service_name == 'drive':
                return mock_drive_service
            elif service_name == 'docs':
                return mock_docs_service
            return MagicMock()

        mock_build.side_effect = build_side_effect

        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance

        # Create processor
        test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            save_to_disk=False
        )

        # Mock metadata response
        mock_drive_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }

        # Mock document with suggestions
        mock_docs_service.documents().get().execute.return_value = {
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {
                                    'textRun': {
                                        'content': 'Some text',
                                        'suggestedDeletionIds': ['suggestion1']  # Has suggestions
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }

        # Mock comments (none in this case)
        mock_drive_service.comments().list().execute.return_value = {'comments': []}
        
        # Capture log output
        with patch('markmeld.google_drive.processor._LOGGER') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify info was logged about using Docs API with change markers
            info_calls = [call for call in mock_logger.info.call_args_list
                        if 'suggested edits' in str(call) or 'change markers' in str(call)]
            assert len(info_calls) > 0, "Expected info about using Docs API with change markers"
    
    @patch('markmeld.google_drive.processor.service_account.Credentials')
    @patch('markmeld.google_drive.processor.build')
    def test_check_for_active_changes_with_unresolved_comments(self, mock_build, mock_creds):
        """Test warning when document has unresolved comments."""
        
        # Mock the Google Drive and Docs services
        mock_drive_service = MagicMock()
        mock_docs_service = MagicMock()
        
        def build_side_effect(service_name, version, credentials=None, **kwargs):
            if service_name == 'drive':
                return mock_drive_service
            elif service_name == 'docs':
                return mock_docs_service
            return MagicMock()
        
        mock_build.side_effect = build_side_effect
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance
        
        # Create processor
        test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_drive_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock document without suggestions
        mock_docs_service.documents().get().execute.return_value = {
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {
                                    'textRun': {
                                        'content': 'Some text'
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
        # Mock comments response with unresolved comments
        mock_drive_service.comments().list().execute.return_value = {
            'comments': [
                {'resolved': False, 'content': 'First comment text', 'author': {'displayName': 'User 1'}},
                {'resolved': False, 'content': 'Second comment text', 'author': {'displayName': 'User 2'}},
                {'resolved': True, 'content': 'Resolved comment', 'author': {'displayName': 'User 3'}}
            ]
        }
        
        # Capture log output
        with patch('markmeld.google_drive.processor._LOGGER') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify warning was logged (checking for new message format)
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'DISCUSSION COMMENTS' in str(call)]
            assert len(warning_calls) > 0, "Expected warning about unresolved discussion comments"
    
    @patch('markmeld.google_drive.processor.service_account.Credentials')
    @patch('markmeld.google_drive.processor.build')
    def test_check_for_active_changes_no_issues(self, mock_build, mock_creds):
        """Test no warning when document has no active changes."""
        
        # Mock the Google Drive and Docs services
        mock_drive_service = MagicMock()
        mock_docs_service = MagicMock()
        
        def build_side_effect(service_name, version, credentials=None, **kwargs):
            if service_name == 'drive':
                return mock_drive_service
            elif service_name == 'docs':
                return mock_docs_service
            return MagicMock()
        
        mock_build.side_effect = build_side_effect
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance
        
        # Create processor
        test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_drive_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock document without suggestions
        mock_docs_service.documents().get().execute.return_value = {
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {
                                    'textRun': {
                                        'content': 'Some text'
                                        # No suggestedDeletionIds, suggestedInsertionIds, etc.
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
        # Mock comments response with no unresolved comments
        mock_drive_service.comments().list().execute.return_value = {
            'comments': []  # No comments at all
        }
        
        # Capture log output
        with patch('markmeld.google_drive.processor._LOGGER') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Verify no warning was logged
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'WARNING' in str(call)]
            assert len(warning_calls) == 0, "Should not warn when no active changes"
    
    @patch('markmeld.google_drive.processor.service_account.Credentials')
    @patch('markmeld.google_drive.processor.build')
    def test_check_continues_on_api_failure(self, mock_build, mock_creds):
        """Test that document download continues even if change detection fails."""
        
        # Mock the Google Drive service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance
        
        # Create processor
        test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            save_to_disk=False
        )
        
        # Make metadata call fail
        mock_service.files().get().execute.side_effect = Exception("API error")
        
        # This should not raise an exception
        try:
            processor._check_for_active_changes('test_doc_id')
        except Exception:
            pytest.fail("Check for active changes should not raise exceptions")
    
    @patch('markmeld.google_drive.processor.service_account.Credentials')
    @patch('markmeld.google_drive.processor.build')
    def test_filters_original_content_deleted_comments(self, mock_build, mock_creds):
        """Test that comments with 'Original content deleted' are filtered out."""
        
        # Mock the Google Drive and Docs services
        mock_drive_service = MagicMock()
        mock_docs_service = MagicMock()
        
        def build_side_effect(service_name, version, credentials=None, **kwargs):
            if service_name == 'drive':
                return mock_drive_service
            elif service_name == 'docs':
                return mock_docs_service
            return MagicMock()
        
        mock_build.side_effect = build_side_effect
        
        # Mock credentials
        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance
        
        # Create processor
        test_creds = {'type': 'service_account', 'project_id': 'test', 'client_email': 'test@example.com'}
        processor = GoogleDriveProcessor(
            credentials_dict=test_creds,
            save_to_disk=False
        )
        
        # Mock metadata response
        mock_drive_service.files().get().execute.return_value = {
            'id': 'test_doc_id',
            'name': 'Test Document',
            'modifiedTime': '2024-01-01T00:00:00Z'
        }
        
        # Mock document without suggestions
        mock_docs_service.documents().get().execute.return_value = {
            'body': {'content': []}
        }
        
        # Mock comments with "Original content deleted"
        mock_drive_service.comments().list().execute.return_value = {
            'comments': [
                {
                    'resolved': False, 
                    'content': 'Original content deleted',
                    'author': {'displayName': 'User 1'}
                },
                {
                    'resolved': False,
                    'content': '[Original content deleted]',
                    'author': {'displayName': 'User 2'}
                },
                {
                    'resolved': False,
                    'content': 'This is a real comment that should be shown',
                    'author': {'displayName': 'User 3'},
                    'quotedFileContent': {'value': 'Some quoted text'}
                },
                {
                    'resolved': False,
                    'content': 'Comment with empty quoted content',
                    'author': {'displayName': 'User 4'},
                    'quotedFileContent': {'value': ''}  # Empty quoted content
                }
            ]
        }
        
        # Capture log output
        with patch('markmeld.google_drive.processor._LOGGER') as mock_logger:
            processor._check_for_active_changes('test_doc_id')
            
            # Check that warning was logged with only 1 real comment
            warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
            
            # Should warn about discussion comments
            has_discussion_warning = any('DISCUSSION COMMENTS' in str(call) for call in warning_calls)
            
            # Should show only 1 unresolved comment (the real one)
            has_one_comment = any('Found 1 unresolved comment' in str(call) for call in warning_calls)
            
            # Should show the real comment content
            has_real_comment = any('real comment that should be shown' in str(call) for call in warning_calls)
            
            # Should NOT show "Original content deleted" comments
            has_deleted_content = any('Original content deleted' in str(call) for call in warning_calls 
                                     if 'real comment' not in str(call))
            
            assert has_discussion_warning, "Should warn about discussion comments"
            assert has_one_comment, "Should report only 1 unresolved comment"
            assert has_real_comment, "Should show the real comment"
            assert not has_deleted_content, "Should NOT show 'Original content deleted' comments"