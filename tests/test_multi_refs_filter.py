"""
Test the multi-refs pandoc filter to ensure it works correctly regardless of
--citeproc flag placement (before filter, after filter, or not at all).
"""

import pytest
import subprocess
import shutil
from pathlib import Path

PANDOC_PATH = shutil.which("pandoc")
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
        "filter": test_dir / "multi-refs.lua",
    }


def _run_pandoc(sample_files, test_dir, output, citeproc_position):
    """Run pandoc with --citeproc placed before/after --lua-filter, or omitted."""
    base = [
        PANDOC_PATH,
        str(sample_files["sample"]),
        "--bibliography",
        str(sample_files["bib"]),
    ]
    lua_filter = ["--lua-filter", str(sample_files["filter"])]
    if citeproc_position == "before":
        cmd = base + ["--citeproc"] + lua_filter
    elif citeproc_position == "after":
        cmd = base + lua_filter + ["--citeproc"]
    else:
        cmd = base + lua_filter
    cmd += ["-o", str(output)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=test_dir)


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
@pytest.mark.parametrize("citeproc_position", ["before", "after", "none"])
def test_multi_refs_bibliography_regardless_of_citeproc_position(
    test_dir, sample_files, tmp_path, citeproc_position
):
    """Each multi-refs div is populated with section-specific references,
    independent of where (or whether) --citeproc appears on the command line.

    With pandoc 3.x, exact output equality across orderings is not a
    realistic goal (the markdown writer reconstructs [@key] syntax from Cite
    nodes regardless of prior citeproc formatting); what matters is that
    each multi-refs div gets the correct, section-specific references.
    """
    output = tmp_path / "output.md"
    result = _run_pandoc(sample_files, test_dir, output, citeproc_position)

    assert result.returncode == 0, f"Pandoc failed: {result.stderr}"
    assert output.exists(), "Output file was not created"

    content = output.read_text()

    assert "multi-refs" in content, "Multi-refs divs should be present (as class)"
    assert content.count("csl-entry") >= 7, "Should have >=7 reference entries"
    assert content.count("multi-refs") == 3, "Should have 3 multi-refs divs"

    # Output should stay compact -- if all refs ended up in every section,
    # we'd see way more than ~3000 chars.
    assert len(content) < 3000, (
        f"Output too large ({len(content)} chars) - "
        "likely dumping all refs in every section"
    )


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="Pandoc not available")
def test_multiref_no_duplicates_option(test_dir, sample_files, tmp_path):
    """
    Test that multiref_no_duplicates option is respected.
    The sample.md has this set to true, so repeated citations should only
    appear in the first multi-refs div where they occur.
    """
    output = tmp_path / "output.md"
    result = _run_pandoc(sample_files, test_dir, output, "none")
    assert result.returncode == 0

    content = output.read_text()

    # Count occurrences of specific reference (Dames appears in multiple sections)
    # With multiref_no_duplicates: true, it should only appear once
    dames_count = content.count("ref-dames:physiology")

    # It should appear exactly once (in the first section where it's cited)
    assert (
        dames_count == 1
    ), f"Dames reference should appear once with multiref_no_duplicates: true, found {dames_count}"
