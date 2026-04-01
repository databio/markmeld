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

    def test_missing_blank_line_before_h1(self):
        md = "Some paragraph text.\n# Heading"
        result = ensure_blank_lines_before_headings(md)
        assert result == "Some paragraph text.\n\n# Heading"

    def test_missing_blank_line_before_h2(self):
        md = "End of paragraph.\n## Section"
        result = ensure_blank_lines_before_headings(md)
        assert result == "End of paragraph.\n\n## Section"

    def test_missing_blank_line_before_h3(self):
        md = "End of paragraph.\n### Subsection"
        result = ensure_blank_lines_before_headings(md)
        assert result == "End of paragraph.\n\n### Subsection"

    def test_already_has_blank_line(self):
        md = "Some text.\n\n# Heading"
        result = ensure_blank_lines_before_headings(md)
        assert result == md

    def test_heading_at_start_of_document(self):
        md = "# Title\nSome text."
        result = ensure_blank_lines_before_headings(md)
        assert result == md

    def test_consecutive_headings_no_blank_lines(self):
        """Google Docs often outputs consecutive headings without blanks."""
        md = "# Methods\n## Components\n### Overview"
        result = ensure_blank_lines_before_headings(md)
        assert result == "# Methods\n\n## Components\n\n### Overview"

    def test_consecutive_headings_already_spaced(self):
        md = "# Methods\n\n## Components\n\n### Overview"
        result = ensure_blank_lines_before_headings(md)
        assert result == md

    def test_figure_then_heading_no_blank(self):
        """Real-world pattern: figure reference immediately before heading."""
        md = "![Figure 1](fig/fig01.svg){fullwidth=\"t\"}\n## Results"
        result = ensure_blank_lines_before_headings(md)
        assert result == "![Figure 1](fig/fig01.svg){fullwidth=\"t\"}\n\n## Results"

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

    def test_does_not_add_extra_blank_lines(self):
        """Should not add blanks if one already exists."""
        md = "Text.\n\n# Heading\n\n## Sub"
        result = ensure_blank_lines_before_headings(md)
        assert result == md

    def test_empty_input(self):
        assert ensure_blank_lines_before_headings("") == ""

    def test_no_headings(self):
        md = "Just a paragraph.\nAnother line."
        result = ensure_blank_lines_before_headings(md)
        assert result == md

    def test_hash_in_non_heading_context(self):
        """Lines starting with # inside code blocks shouldn't be affected,
        but since we don't track code block state, this is a known limitation.
        At minimum, verify normal # comments at line start get treated."""
        md = "some code\n# this is a comment"
        result = ensure_blank_lines_before_headings(md)
        # It will add a blank line — acceptable since outside code blocks
        assert "\n\n# this is a comment" in result

    def test_multiple_blank_lines_preserved(self):
        """Don't collapse existing multiple blank lines."""
        md = "Text.\n\n\n# Heading"
        result = ensure_blank_lines_before_headings(md)
        # Last line before heading is empty, so no insertion needed
        assert result == md


# ============================================================
# clean_escape_characters
# ============================================================

class TestCleanEscapeCharacters:
    def test_removes_bracket_escapes(self):
        assert "[]" in clean_escape_characters("\\[\\]")

    def test_removes_underscore_escape(self):
        assert "some_var" in clean_escape_characters("some\\_var")

    def test_removes_paren_escapes(self):
        result = clean_escape_characters("\\(text\\)")
        assert result == "(text)"

    def test_removes_star_escapes(self):
        assert clean_escape_characters("\\*bold\\*") == "*bold*"

    def test_preserves_latex_commands(self):
        """Double backslash before LaTeX commands should become single."""
        result = clean_escape_characters("\\\\alpha")
        assert result == "\\alpha"

    def test_preserves_latex_braces(self):
        result = clean_escape_characters("\\\\{x\\\\}")
        assert result == "\\{x\\}"

    def test_mixed_escapes(self):
        md = "See \\[Figure 1\\] for \\*details\\*"
        result = clean_escape_characters(md)
        assert result == "See [Figure 1] for *details*"


# ============================================================
# remove_embedded_images
# ============================================================

class TestRemoveEmbeddedImages:
    def test_removes_data_uri_reference(self):
        md = "[image1]: data:image/png;base64,abc123\nSome text."
        result = remove_embedded_images(md)
        assert "data:" not in result
        assert "Some text." in result

    def test_removes_inline_data_uri(self):
        md = "![alt](data:image/png;base64,abc123)"
        result = remove_embedded_images(md)
        assert "data:" not in result

    def test_removes_image_references(self):
        md = "![][image1]\nText after."
        result = remove_embedded_images(md)
        assert "image1" not in result
        assert "Text after." in result

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
    def test_removes_bold_from_h1(self):
        result = strip_bold_from_headings("# **Bold Title**")
        assert result == "# Bold Title"

    def test_removes_bold_from_h2(self):
        result = strip_bold_from_headings("## **Section Name**")
        assert result == "## Section Name"

    def test_removes_bold_from_h3(self):
        result = strip_bold_from_headings("### **Subsection**")
        assert result == "### Subsection"

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

    def test_preserves_non_svg_images(self):
        md = "![Figure](fig/image.png)"
        result = replace_svg_extensions(md)
        assert result == md

    def test_preserves_svg_in_text(self):
        """SVG mentioned in text (not image syntax) should not change."""
        md = "The file format is .svg for vectors."
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
    def test_smart_quotes_replaced(self):
        result = check_and_fix_latex_incompatible_chars("\u2018hello\u2019")
        assert result == "'hello'"

    def test_double_smart_quotes_replaced(self):
        result = check_and_fix_latex_incompatible_chars("\u201Chello\u201D")
        assert result == '"hello"'

    def test_en_dash(self):
        result = check_and_fix_latex_incompatible_chars("pages 1\u20135")
        assert result == "pages 1--5"

    def test_em_dash(self):
        result = check_and_fix_latex_incompatible_chars("word\u2014word")
        assert result == "word---word"

    def test_ellipsis(self):
        result = check_and_fix_latex_incompatible_chars("wait\u2026")
        assert result == "wait..."

    def test_vertical_tab(self):
        """The bug that broke the sequence collections manuscript."""
        result = check_and_fix_latex_incompatible_chars("before\x0bafter")
        assert result == "before\nafter"

    def test_no_break_space(self):
        result = check_and_fix_latex_incompatible_chars("hello\u00A0world")
        assert result == "hello world"

    def test_zero_width_space_removed(self):
        result = check_and_fix_latex_incompatible_chars("hel\u200Blo")
        assert result == "hello"

    def test_greek_letters(self):
        result = check_and_fix_latex_incompatible_chars("\u03B1 and \u03B2")
        assert "$\\alpha$" in result
        assert "$\\beta$" in result

    def test_degree_sign(self):
        result = check_and_fix_latex_incompatible_chars("90\u00B0")
        assert "$^\\circ$" in result

    def test_subscripts(self):
        result = check_and_fix_latex_incompatible_chars("H\u2082O")
        assert "$_2$" in result

    def test_superscripts(self):
        result = check_and_fix_latex_incompatible_chars("m\u00B2")
        assert "$^2$" in result

    def test_arrows(self):
        result = check_and_fix_latex_incompatible_chars("A \u2192 B")
        assert "$\\rightarrow$" in result

    def test_plain_ascii_unchanged(self):
        md = "Just plain ASCII text with numbers 123 and symbols !@#."
        assert check_and_fix_latex_incompatible_chars(md) == md

    def test_multiple_replacements_in_one_string(self):
        md = "The \u03B1-value\u2014ranging from 1\u20135\u2014was \u2248 0.05"
        result = check_and_fix_latex_incompatible_chars(md)
        assert "$\\alpha$" in result
        assert "---" in result
        assert "--" in result
        assert "~" in result


# ============================================================
# clean_markdown (integration)
# ============================================================

class TestCleanMarkdownIntegration:
    def test_all_steps_applied(self):
        """Verify the full pipeline handles a realistic Google Docs export."""
        md = (
            "# **Introduction**\n"
            "This is a paragraph with \\[escaped brackets\\] "
            "and smart quotes \u201Clike this\u201D.\n"
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
        assert "\u201C" not in result
        assert "\u201D" not in result
        # Blank line before ## Methods
        assert "\n\n## Methods" in result

    def test_heading_after_paragraph_in_full_pipeline(self):
        """The exact pattern that caused the original bug."""
        md = (
            "End of paragraph (Figure 3E).\n"
            "![Caption](fig/fig07.svg){fullwidth=\"t\"}\n"
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
