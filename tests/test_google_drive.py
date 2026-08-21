"""
Test suite for GoogleDriveProcessor integration in markmeld package.
These tests verify the optional Google Drive functionality works correctly
when the google extras are installed.
"""

from unittest.mock import patch

import pytest

from markmeld.google_drive.figure_paths import extract_csv_paths, update_figure_paths


@pytest.mark.parametrize(
    "input_md,mapping,expected",
    [
        (
            "![Figure 1](figure1.svg){width=174mm}",
            {"figure1.svg": "figure1.pdf"},
            "![Figure 1](figure1.pdf){width=174mm}",
        ),
        (
            "![Table](data.csv){width=174mm font-size=6pt}",
            {"data.csv": "data.pdf"},
            "![Table](data.pdf){width=174mm font-size=6pt}",
        ),
        (
            '![Complex](chart.svg){col-widths="20,5,8" col-align="left,center,right"}',
            {"chart.svg": "chart.pdf"},
            '![Complex](chart.pdf){col-widths="20,5,8" col-align="left,center,right"}',
        ),
        (
            "![Empty params](image.png){}",
            {"image.png": "image.pdf"},
            "![Empty params](image.pdf){}",
        ),
        (
            "![No params](regular.jpg) and ![With params](special.svg){width=100px}",
            {"regular.jpg": "regular.pdf", "special.svg": "special.pdf"},
            "![No params](regular.pdf) and ![With params](special.pdf){width=100px}",
        ),
        (
            "Some text before ![Figure](fig.svg){width=50%} and after",
            {"fig.svg": "fig.pdf"},
            "Some text before ![Figure](fig.pdf){width=50%} and after",
        ),
        (
            "Multiple: ![A](a.svg){width=10} ![B](b.svg){height=20} ![C](c.svg){}",
            {"a.svg": "a.pdf", "b.svg": "b.pdf", "c.svg": "c.pdf"},
            "Multiple: ![A](a.pdf){width=10} ![B](b.pdf){height=20} ![C](c.pdf){}",
        ),
    ],
)
def test_update_figure_paths_preserves_parameters(input_md, mapping, expected):
    """_update_figure_paths preserves figure attribute blocks while swapping paths."""
    assert update_figure_paths(input_md, mapping) == expected


@pytest.mark.parametrize(
    "content,expected",
    [
        (
            """
            # Document with CSV files

            Here's a data file: {csv/data.csv}
            Another one: {csv/subfolder/metrics.csv}

            Some text with {csv/results.csv} inline.

            Duplicate reference: {csv/data.csv}
            """,
            ["csv/data.csv", "csv/subfolder/metrics.csv", "csv/results.csv"],
        ),
        (
            """
            # Document without CSV files

            Just regular text here.
            Maybe an image: ![alt](fig/image.png)
            """,
            [],
        ),
        ("{csv/simple.csv}", ["csv/simple.csv"]),
        ("{csv/path/to/file.csv}", ["csv/path/to/file.csv"]),
        ("{csv/file-with-dashes.csv}", ["csv/file-with-dashes.csv"]),
        ("{csv/file_with_underscores.csv}", ["csv/file_with_underscores.csv"]),
        ("{csv/2024_data.csv}", ["csv/2024_data.csv"]),
        ("{notcsv/file.csv}", []),
        ("{csv/file.txt}", []),
        ("csv/file.csv", []),  # Missing braces
        ("{csv/file.csv", []),  # Missing closing brace
    ],
)
def test_extract_csv_paths(content, expected):
    """extract_csv_paths finds unique {csv/...} references and rejects near-misses."""
    assert extract_csv_paths(content) == expected


def test_google_drive_processor_initialization(google_drive_processor):
    """GoogleDriveProcessor resolves cache_root and reports credentials correctly."""
    services = google_drive_processor(cache_root="test_cache")
    processor = services.processor

    assert processor.credentials_path is None  # No path when using dict
    assert processor.cache_manager.cache_root.is_absolute()
    assert processor.cache_manager.cache_root.name == "test_cache"
    assert processor.service_account_email == "test@example.com"


def test_cleaned_content_is_cached(google_drive_processor):
    """_download_raw_markdown caches the cleaned markdown, not the raw export."""
    services = google_drive_processor()
    processor = services.processor

    raw_content = "# Test\\-Title\n\nContent with \\*escaped\\* characters"

    with (
        patch.object(processor, "_download_first_tab", return_value=raw_content),
        patch.object(processor, "_document_has_suggestions", return_value=False),
        patch.object(processor, "_load_from_disk", return_value=None),
        patch.object(processor, "_save_to_disk"),
    ):
        result = processor._download_raw_markdown("test_doc_id")

    assert "\\*" not in result
    assert "\\-" not in result
    assert "*escaped*" in result
    assert "Test-Title" in result
