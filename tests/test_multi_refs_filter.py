"""
Test the multi-refs pandoc filter to ensure it works correctly regardless of
--citeproc flag placement (before filter, after filter, or not at all).
"""

import os
import pytest
import subprocess
import shutil
from pathlib import Path


# Check if pandoc is available
PANDOC_PATH = shutil.which("pandoc")
if not PANDOC_PATH:
    # Try bulker location
    bulker_pandoc = "/home/nsheff/bulker_crates/databio/nsheff/default/pandoc"
    if os.path.exists(bulker_pandoc):
        PANDOC_PATH = bulker_pandoc
    else:
        PANDOC_PATH = None

PANDOC_AVAILABLE = PANDOC_PATH is not None


@pytest.fixture
def test_dir():
    """Get the test data directory for multi-refs filter tests."""
    return Path(__file__).parent / "test_data" / "multi_refs_filter"


@pytest.fixture
def sample_files(test_dir):
    """Return paths to test files."""
    return {
        "sample": test_dir / "sample.md",
        "bib": test_dir / "bibliography.bib",
        "filter": test_dir / "multi-refs.lua"
    }


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_citeproc_before_filter(test_dir, sample_files, tmp_path):
    """Test with --citeproc BEFORE --lua-filter (traditional order)."""
    output = tmp_path / "output.md"

    cmd = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--citeproc",
        "--lua-filter", str(sample_files["filter"]),
        "-o", str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=test_dir)

    assert result.returncode == 0, f"Pandoc failed: {result.stderr}"
    assert output.exists(), "Output file was not created"

    content = output.read_text()

    # Check that multi-refs divs were replaced with references
    assert ".multi-refs" in content, "Multi-refs divs should be present (as class)"
    assert content.count("csl-entry") > 0, "Should have reference entries"

    # Check for section-specific references (not all refs in every section)
    # Output should be around 2300 chars if working correctly
    assert len(content) < 3000, "Output too large - likely dumping all refs in every section"


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_citeproc_after_filter(test_dir, sample_files, tmp_path):
    """Test with --citeproc AFTER --lua-filter (should work with fixed filter)."""
    output = tmp_path / "output.md"

    cmd = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--lua-filter", str(sample_files["filter"]),
        "--citeproc",
        "-o", str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=test_dir)

    assert result.returncode == 0, f"Pandoc failed: {result.stderr}"
    assert output.exists(), "Output file was not created"

    content = output.read_text()

    # Check that multi-refs divs were replaced with references
    assert ".multi-refs" in content, "Multi-refs divs should be present (as class)"
    assert content.count("csl-entry") > 0, "Should have reference entries"

    # This should produce the same output as citeproc-before-filter
    # (proving the fix works)
    assert len(content) < 3000, "Output too large - likely dumping all refs in every section"


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_no_citeproc_flag(test_dir, sample_files, tmp_path):
    """Test with NO --citeproc flag (filter handles it internally)."""
    output = tmp_path / "output.md"

    cmd = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--lua-filter", str(sample_files["filter"]),
        "-o", str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=test_dir)

    assert result.returncode == 0, f"Pandoc failed: {result.stderr}"
    assert output.exists(), "Output file was not created"

    content = output.read_text()

    # Check that multi-refs divs were replaced with references
    assert ".multi-refs" in content, "Multi-refs divs should be present (as class)"
    assert content.count("csl-entry") > 0, "Should have reference entries"

    assert len(content) < 3000, "Output too large - likely dumping all refs in every section"


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_all_orders_produce_identical_output(test_dir, sample_files, tmp_path):
    """
    Test that all three citeproc orderings produce identical output.
    This is the key test proving the filter is order-independent.
    """
    outputs = {}

    # Test 1: --citeproc before filter
    out1 = tmp_path / "output_citeproc_first.md"
    cmd1 = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--citeproc",
        "--lua-filter", str(sample_files["filter"]),
        "-o", str(out1)
    ]
    subprocess.run(cmd1, capture_output=True, text=True, cwd=test_dir)
    outputs["citeproc_first"] = out1.read_text()

    # Test 2: --citeproc after filter
    out2 = tmp_path / "output_citeproc_last.md"
    cmd2 = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--lua-filter", str(sample_files["filter"]),
        "--citeproc",
        "-o", str(out2)
    ]
    subprocess.run(cmd2, capture_output=True, text=True, cwd=test_dir)
    outputs["citeproc_last"] = out2.read_text()

    # Test 3: No --citeproc
    out3 = tmp_path / "output_no_citeproc.md"
    cmd3 = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--lua-filter", str(sample_files["filter"]),
        "-o", str(out3)
    ]
    subprocess.run(cmd3, capture_output=True, text=True, cwd=test_dir)
    outputs["no_citeproc"] = out3.read_text()

    # All three should be identical
    assert outputs["citeproc_first"] == outputs["citeproc_last"], \
        "Citeproc-first and citeproc-last should produce identical output"

    assert outputs["citeproc_first"] == outputs["no_citeproc"], \
        "Citeproc-first and no-citeproc should produce identical output"

    # Verify they all have the expected structure
    for name, content in outputs.items():
        assert content.count("csl-entry") >= 7, \
            f"{name}: Should have at least 7 reference entries (one per unique citation)"

        # Check that references are split by section
        # The sample has 3 multi-refs divs, so we should see references distributed
        assert len(content) < 3000, \
            f"{name}: Output too large ({len(content)} chars) - likely all refs in every section"

        print(f"{name}: {len(content)} chars, {content.count('csl-entry')} entries ✓")


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_multiref_no_duplicates_option(test_dir, sample_files, tmp_path):
    """
    Test that multiref_no_duplicates option is respected.
    The sample.md has this set to true, so repeated citations should only
    appear in the first multi-refs div where they occur.
    """
    output = tmp_path / "output.md"

    cmd = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography", str(sample_files["bib"]),
        "--lua-filter", str(sample_files["filter"]),
        "-o", str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=test_dir)
    assert result.returncode == 0

    content = output.read_text()

    # Count occurrences of specific reference (Dames appears in multiple sections)
    # With multiref_no_duplicates: true, it should only appear once
    dames_count = content.count("ref-dames:physiology")

    # It should appear exactly once (in the first section where it's cited)
    assert dames_count == 1, \
        f"Dames reference should appear once with multiref_no_duplicates: true, found {dames_count}"
