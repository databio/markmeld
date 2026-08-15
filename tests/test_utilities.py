"""Test suite for markmeld.utilities functions."""

from markmeld.utilities import sanitize_filename


def test_sanitize_filename():
    """Test filename sanitization."""
    assert sanitize_filename("file<>name.txt") == "file__name.txt"
    assert sanitize_filename("path/to/file.txt") == "path_to_file.txt"

    # Preservation of extension
    assert sanitize_filename("document.md") == "document.md"

    # Length limiting
    long_name = "a" * 300 + ".txt"
    sanitized = sanitize_filename(long_name)
    assert len(sanitized) <= 255
    assert sanitized.endswith(".txt")
