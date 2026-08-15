"""Tests for markmeld.google_drive.markdown_clean module.

Covers all cleaning functions used to process Google Docs exports
for LaTeX/pandoc processing.
"""

import pytest

from markmeld.google_drive.markdown_clean import (
    clean_markdown,
    clean_escape_characters,
    remove_embedded_images,
    strip_bold_from_headings,
    ensure_blank_lines_before_headings,
    replace_svg_extensions,
    check_and_fix_latex_incompatible_chars,
)

# ============================================================
# ensure_blank_lines_before_headings
# ============================================================


class TestEnsureBlankLinesBeforeHeadings:
    """Tests for the heading blank line fix.

    This was the bug: Google Docs exports omit blank lines before headings,
    causing markdown parsers to render them inline instead of as headings.
    """

    @pytest.mark.parametrize(
        "md, expected",
        [
            ("Some paragraph text.\n# Heading", "Some paragraph text.\n\n# Heading"),
            ("End of paragraph.\n## Section", "End of paragraph.\n\n## Section"),
            (
                "End of paragraph.\n### Subsection",
                "End of paragraph.\n\n### Subsection",
            ),
        ],
    )
    def test_missing_blank_line_before_heading(self, md, expected):
        assert ensure_blank_lines_before_headings(md) == expected

    @pytest.mark.parametrize(
        "md",
        [
            "Some text.\n\n# Heading",
            "# Title\nSome text.",
            "# Methods\n\n## Components\n\n### Overview",
            "Text.\n\n# Heading\n\n## Sub",
            "Just a paragraph.\nAnother line.",
            "Text.\n\n\n# Heading",
            "",
        ],
    )
    def test_leaves_input_unchanged(self, md):
        assert ensure_blank_lines_before_headings(md) == md

    def test_consecutive_headings_no_blank_lines(self):
        """Google Docs often outputs consecutive headings without blanks."""
        md = "# Methods\n## Components\n### Overview"
        result = ensure_blank_lines_before_headings(md)
        assert result == "# Methods\n\n## Components\n\n### Overview"

    def test_figure_then_heading_no_blank(self):
        """Real-world pattern: figure reference immediately before heading."""
        md = '![Figure 1](fig/fig01.svg){fullwidth="t"}\n## Results'
        result = ensure_blank_lines_before_headings(md)
        assert result == '![Figure 1](fig/fig01.svg){fullwidth="t"}\n\n## Results'

    def test_long_paragraph_then_heading(self):
        """Reproduces the actual bug from the sequence collections paper."""
        md = (
            "Finally, m37 had the fewest sequences (Supplemental Figure 3E).\n"
            "## Implementations and use cases\n"
            "### Existing and planned implementations"
        )
        result = ensure_blank_lines_before_headings(md)
        assert result == (
            "Finally, m37 had the fewest sequences (Supplemental Figure 3E).\n"
            "\n## Implementations and use cases\n"
            "\n### Existing and planned implementations"
        )

    def test_hash_in_non_heading_context(self):
        """Lines starting with # inside code blocks shouldn't be affected,
        but since we don't track code block state, this is a known limitation.
        At minimum, verify normal # comments at line start get treated."""
        md = "some code\n# this is a comment"
        result = ensure_blank_lines_before_headings(md)
        # It will add a blank line — acceptable since outside code blocks
        assert "\n\n# this is a comment" in result


# ============================================================
# clean_escape_characters
# ============================================================


class TestCleanEscapeCharacters:
    @pytest.mark.parametrize(
        "md, expected",
        [
            ("\\[\\]", "[]"),
            ("some\\_var", "some_var"),
            ("\\(text\\)", "(text)"),
            ("\\*bold\\*", "*bold*"),
            # Double backslash before a LaTeX command/brace collapses to single,
            # so LaTeX escapes survive the markdown-escape cleanup.
            ("\\\\alpha", "\\alpha"),
            ("\\\\{x\\\\}", "\\{x\\}"),
            ("See \\[Figure 1\\] for \\*details\\*", "See [Figure 1] for *details*"),
        ],
    )
    def test_clean_escape_characters(self, md, expected):
        assert clean_escape_characters(md) == expected


# ============================================================
# remove_embedded_images
# ============================================================


class TestRemoveEmbeddedImages:
    @pytest.mark.parametrize(
        "md, removed, preserved",
        [
            (
                "[image1]: data:image/png;base64,abc123\nSome text.",
                "data:",
                "Some text.",
            ),
            ("![][image1]\nText after.", "image1", "Text after."),
        ],
    )
    def test_removes_reference_but_preserves_trailing_text(
        self, md, removed, preserved
    ):
        result = remove_embedded_images(md)
        assert removed not in result
        assert preserved in result

    def test_removes_inline_data_uri(self):
        md = "![alt](data:image/png;base64,abc123)"
        result = remove_embedded_images(md)
        assert "data:" not in result

    def test_preserves_file_images(self):
        """File-based images (not data URIs) should be preserved."""
        md = "![Figure 1](fig/figure1.svg)"
        result = remove_embedded_images(md)
        assert "![Figure 1](fig/figure1.svg)" in result

    def test_cleans_extra_blank_lines(self):
        md = "Before.\n\n\n\nAfter."
        result = remove_embedded_images(md)
        assert "\n\n\n" not in result


# ============================================================
# strip_bold_from_headings
# ============================================================


class TestStripBoldFromHeadings:
    @pytest.mark.parametrize(
        "md, expected",
        [
            ("# **Bold Title**", "# Bold Title"),
            ("## **Section Name**", "## Section Name"),
            ("### **Subsection**", "### Subsection"),
        ],
    )
    def test_removes_bold_from_heading(self, md, expected):
        assert strip_bold_from_headings(md) == expected

    def test_preserves_non_heading_bold(self):
        md = "This is **bold** text in a paragraph."
        result = strip_bold_from_headings(md)
        assert result == md

    def test_partial_bold_in_heading(self):
        """Heading with bold somewhere inside."""
        result = strip_bold_from_headings("## Introduction **and** Methods")
        assert "**" not in result
        assert "## Introduction and Methods" == result

    def test_no_bold_heading_unchanged(self):
        md = "## Regular Heading"
        assert strip_bold_from_headings(md) == md


# ============================================================
# replace_svg_extensions
# ============================================================


class TestReplaceSvgExtensions:
    def test_replaces_svg_with_pdf(self):
        md = "![Figure](fig/image.svg)"
        result = replace_svg_extensions(md)
        assert result == "![Figure](fig/image.pdf)"

    def test_multiple_images(self):
        md = "![A](a.svg)\n![B](b.svg)"
        result = replace_svg_extensions(md)
        assert "a.pdf" in result
        assert "b.pdf" in result
        assert ".svg" not in result

    @pytest.mark.parametrize(
        "md",
        [
            "![Figure](fig/image.png)",
            "The file format is .svg for vectors.",
        ],
    )
    def test_leaves_non_svg_syntax_unchanged(self, md):
        result = replace_svg_extensions(md)
        assert result == md

    def test_svg_with_attributes(self):
        """Image with pandoc-style attributes after closing paren."""
        md = '![Caption](fig/plot.svg){width="100%"}'
        result = replace_svg_extensions(md)
        # The attribute block is outside the image syntax, so the
        # svg->pdf replacement should still work on the image part
        assert "plot.pdf" in result


# ============================================================
# check_and_fix_latex_incompatible_chars
# ============================================================


class TestLatexIncompatibleChars:
    # (input, expected) -- one row per problematic character, plus a few
    # "stays unchanged" and "multiple replacements at once" cases.
    @pytest.mark.parametrize(
        "md, expected",
        [
            ("\u2018hello\u2019", "'hello'"),
            ("\u201chello\u201d", '"hello"'),
            ("pages 1\u20135", "pages 1--5"),
            ("word\u2014word", "word---word"),
            ("wait\u2026", "wait..."),
            ("before\x0bafter", "before\nafter"),  # broke the seq. collections paper
            ("hello\u00a0world", "hello world"),
            ("hel\u200blo", "hello"),
            ("\u03b1 and \u03b2", "$\\alpha$ and $\\beta$"),
            ("90\u00b0", "90$^\\circ$"),
            ("H\u2082O", "H$_2$O"),
            ("m\u00b2", "m$^2$"),
            ("A \u2192 B", "A $\\rightarrow$ B"),
            ("\u2010", "-"),
            ("\u00b1", "+/-"),
            ("Just ASCII 123 and symbols !@#.", "Just ASCII 123 and symbols !@#."),
            ("", ""),
            (
                "Text with  spaces\tand\ttabs\nand newlines",
                "Text with  spaces\tand\ttabs\nand newlines",
            ),
            ("   Multiple spaces ", "   Multiple spaces "),
            (
                "The \u03b1-value\u2014ranging from 1\u20135\u2014was \u2248 0.05",
                "The $\\alpha$-value---ranging from 1--5---was ~ 0.05",
            ),
        ],
    )
    def test_char_replacement(self, md, expected):
        assert check_and_fix_latex_incompatible_chars(md) == expected


# ============================================================
# clean_markdown (integration)
# ============================================================


class TestCleanMarkdownIntegration:
    def test_all_steps_applied(self):
        """Verify the full pipeline handles a realistic Google Docs export."""
        md = (
            "# **Introduction**\n"
            "This is a paragraph with \\[escaped brackets\\] "
            "and smart quotes “like this”.\n"
            "## **Methods**\n"
            "We used the \\*standard\\* approach."
        )
        result = clean_markdown(md)
        # Bold stripped from headings
        assert "**" not in result
        # Escapes cleaned
        assert "\\[" not in result
        assert "[escaped brackets]" in result
        # Smart quotes replaced
        assert "“" not in result
        assert "”" not in result
        # Blank line before ## Methods
        assert "\n\n## Methods" in result

    def test_heading_after_paragraph_in_full_pipeline(self):
        """The exact pattern that caused the original bug."""
        md = (
            "End of paragraph (Figure 3E).\n"
            '![Caption](fig/fig07.svg){fullwidth="t"}\n'
            "## Implementations\n"
            "### Existing implementations\n"
            "Several implementations exist."
        )
        result = clean_markdown(md)
        # Headings must have blank lines before them
        assert "\n\n## Implementations" in result
        assert "\n\n### Existing implementations" in result

    def test_disable_individual_steps(self):
        md = "\\[test\\] **# Bold**"
        result = clean_markdown(md, clean_escapes=False)
        assert "\\[" in result

        result = clean_markdown("# **Bold**", strip_heading_bold=False)
        assert "**Bold**" in result

    def test_svg_replacement_off_by_default(self):
        md = "![Fig](fig.svg)"
        result = clean_markdown(md)
        assert ".svg" in result

    def test_svg_replacement_when_enabled(self):
        md = "![Fig](fig.svg)"
        result = clean_markdown(md, replace_svg_with_pdf=True)
        assert ".pdf" in result
        assert ".svg" not in result

    def test_empty_input(self):
        assert clean_markdown("") == ""

    def test_vertical_tab_cleaned_and_heading_spaced(self):
        """Combined test: vertical tab creates missing newline before heading."""
        md = "End of section.\x0b## Next Section\nContent here."
        result = clean_markdown(md)
        # Vertical tab replaced with newline, then blank line ensured before heading
        assert "\x0b" not in result
        assert "\n\n## Next Section" in result
