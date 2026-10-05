"""A Google Doc's metadata block must be found wherever pandoc would find it.

Regression: a collaborator typed title notes above the Research Strategy's
metadata block, with a soft line break (Shift+Enter) before the opening
`---`. The Docs API returns that paragraph as "\\x0b---\\n". markmeld did not
see the block, and the miss flipped the closing `---` into an "opening"
delimiter, gluing every later paragraph of the document together. (The Drive
bibliography itself is now fetched from the target's `bib_source`/`bibliography`
settings, not from the Doc; see test_project_bibliography.py.)
"""

import pytest

from markmeld.google_drive.doc_to_markdown import doc_to_markdown
from markmeld.metadata_blocks import find_bibliography


def _para(*runs):
    return {"paragraph": {"elements": [{"textRun": {"content": r}} for r in runs]}}


# Paragraph shapes copied from the real Research Strategy Docs API response.
RS_DOC = {
    "body": {
        "content": [
            _para("Titles: ", "Attributing Uncertainty", " \n"),
            _para("Or\x0b", "Uncertainty Budget\n"),
            _para("\x0b---\n"),
            _para("bibliography: ref.bib\n"),
            _para("---\n"),
            _para("First paragraph [@a].\n"),
            _para("Second paragraph [@b].\n"),
        ]
    }
}


def test_soft_break_before_delimiter_still_opens_metadata_block():
    md = doc_to_markdown(RS_DOC)
    assert "\n\n---\nbibliography: ref.bib\n---\n" in md


def test_body_paragraphs_after_metadata_block_stay_separate():
    md = doc_to_markdown(RS_DOC)
    assert "First paragraph [@a].\n\nSecond paragraph [@b]." in md


def test_bibliography_found_in_block_below_leading_text():
    assert find_bibliography(doc_to_markdown(RS_DOC)) == "ref.bib"


@pytest.mark.parametrize(
    "content,expected",
    [
        ("---\nbibliography: ref.bib\n---\n\nBody\n", "ref.bib"),
        ("Notes\n\n---\nbibliography: ref.bib\n---\n\nBody\n", "ref.bib"),
        ("---\nbibliography: [a.bib, b.bib]\n---\n", ["a.bib", "b.bib"]),
        # pandoc: when blocks repeat a field, the later block wins
        ("---\nbibliography: a.bib\n---\n\nx\n\n---\nbibliography: b.bib\n---\n", "b.bib"),
        ("---\nbibliography: a.bib\n...\n\nBody\n", "a.bib"),
        # pandoc ignores these: no blank line before (setext heading),
        # blank line after the opener (horizontal rule)
        ("Notes\n---\nbibliography: ref.bib\n---\n", None),
        ("Notes\n\n---\n\nbibliography: ref.bib\n---\n", None),
        ("No metadata here.\n", None),
    ],
)
def test_find_bibliography_follows_pandoc_rules(content, expected):
    assert find_bibliography(content) == expected
