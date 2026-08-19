"""
Unit tests for the Google Drive active changes detection feature.
"""

from unittest.mock import patch


class TestActiveChangesDetection:
    """Test the active changes detection functionality."""

    def test_check_for_active_changes_with_suggestions(self, google_drive_processor):
        """Test warning when document has suggested edits."""
        services = google_drive_processor()

        services.drive.files().get().execute.return_value = {
            "id": "test_doc_id",
            "name": "Test Document",
            "modifiedTime": "2024-01-01T00:00:00Z",
        }

        # Mock document with suggestions
        services.docs.documents().get().execute.return_value = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {
                                    "textRun": {
                                        "content": "Some text",
                                        "suggestedDeletionIds": ["suggestion1"],
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }

        services.drive.comments().list().execute.return_value = {"comments": []}

        with patch("markmeld.google_drive.processor._LOGGER") as mock_logger:
            services.processor._check_for_active_changes("test_doc_id")

            info_calls = [
                call
                for call in mock_logger.info.call_args_list
                if "suggested edits" in str(call) or "change markers" in str(call)
            ]
            assert (
                len(info_calls) > 0
            ), "Expected info about using Docs API with change markers"

    def test_check_for_active_changes_with_unresolved_comments(
        self, google_drive_processor
    ):
        """Test warning when document has unresolved comments."""
        services = google_drive_processor()

        services.drive.files().get().execute.return_value = {
            "id": "test_doc_id",
            "name": "Test Document",
            "modifiedTime": "2024-01-01T00:00:00Z",
        }

        services.docs.documents().get().execute.return_value = {
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "Some text"}}]}}
                ]
            }
        }

        services.drive.comments().list().execute.return_value = {
            "comments": [
                {
                    "resolved": False,
                    "content": "First comment text",
                    "author": {"displayName": "User 1"},
                },
                {
                    "resolved": False,
                    "content": "Second comment text",
                    "author": {"displayName": "User 2"},
                },
                {
                    "resolved": True,
                    "content": "Resolved comment",
                    "author": {"displayName": "User 3"},
                },
            ]
        }

        with patch("markmeld.google_drive.processor._LOGGER") as mock_logger:
            services.processor._check_for_active_changes("test_doc_id")

            warning_calls = [
                call
                for call in mock_logger.warning.call_args_list
                if "DISCUSSION COMMENTS" in str(call)
            ]
            assert (
                len(warning_calls) > 0
            ), "Expected warning about unresolved discussion comments"

    def test_check_for_active_changes_no_issues(self, google_drive_processor):
        """Test no warning when document has no active changes."""
        services = google_drive_processor()

        services.drive.files().get().execute.return_value = {
            "id": "test_doc_id",
            "name": "Test Document",
            "modifiedTime": "2024-01-01T00:00:00Z",
        }

        services.docs.documents().get().execute.return_value = {
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "Some text"}}]}}
                ]
            }
        }

        services.drive.comments().list().execute.return_value = {"comments": []}

        with patch("markmeld.google_drive.processor._LOGGER") as mock_logger:
            services.processor._check_for_active_changes("test_doc_id")

            warning_calls = [
                call
                for call in mock_logger.warning.call_args_list
                if "WARNING" in str(call)
            ]
            assert len(warning_calls) == 0, "Should not warn when no active changes"

    def test_check_continues_on_api_failure(self, google_drive_processor):
        """Test that document download continues even if change detection fails."""
        services = google_drive_processor()

        services.drive.files().get().execute.side_effect = Exception("API error")

        services.processor._check_for_active_changes("test_doc_id")

    def test_filters_original_content_deleted_comments(self, google_drive_processor):
        """Test that comments with 'Original content deleted' are filtered out."""
        services = google_drive_processor()

        services.drive.files().get().execute.return_value = {
            "id": "test_doc_id",
            "name": "Test Document",
            "modifiedTime": "2024-01-01T00:00:00Z",
        }

        services.docs.documents().get().execute.return_value = {"body": {"content": []}}

        services.drive.comments().list().execute.return_value = {
            "comments": [
                {
                    "resolved": False,
                    "content": "Original content deleted",
                    "author": {"displayName": "User 1"},
                },
                {
                    "resolved": False,
                    "content": "[Original content deleted]",
                    "author": {"displayName": "User 2"},
                },
                {
                    "resolved": False,
                    "content": "This is a real comment that should be shown",
                    "author": {"displayName": "User 3"},
                    "quotedFileContent": {"value": "Some quoted text"},
                },
                {
                    "resolved": False,
                    "content": "Comment with empty quoted content",
                    "author": {"displayName": "User 4"},
                    "quotedFileContent": {"value": ""},
                },
            ]
        }

        with patch("markmeld.google_drive.processor._LOGGER") as mock_logger:
            services.processor._check_for_active_changes("test_doc_id")

            warning_calls = [str(call) for call in mock_logger.warning.call_args_list]

            has_discussion_warning = any(
                "DISCUSSION COMMENTS" in call for call in warning_calls
            )
            has_one_comment = any(
                "Found 1 unresolved comment" in call for call in warning_calls
            )
            has_real_comment = any(
                "real comment that should be shown" in call for call in warning_calls
            )
            has_deleted_content = any(
                "Original content deleted" in call
                for call in warning_calls
                if "real comment" not in call
            )

            assert has_discussion_warning, "Should warn about discussion comments"
            assert has_one_comment, "Should report only 1 unresolved comment"
            assert has_real_comment, "Should show the real comment"
            assert (
                not has_deleted_content
            ), "Should NOT show 'Original content deleted' comments"
