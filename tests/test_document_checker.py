"""Tests for markmeld.document_checker figure reference analysis."""

import pytest

from markmeld.document_checker import DocumentChecker


@pytest.fixture
def dc():
    return DocumentChecker()


# ---------------------------------------------------------------------------
# extract_figure_references: format variants
# ---------------------------------------------------------------------------

EXTRACT_CASES = [
    pytest.param(
        """
        Some text with a figure reference (Fig. 1).
        Another reference (Figure 2A).
        Multiple panels (Fig. 3B-D).
        Supplemental figure (Figure S1).
        """,
        [("1", ""), ("2", "A"), ("3", "B-D"), ("S1", "")],
        id="parenthetic",
    ),
    pytest.param(
        """
        As shown in Figure 4, the results are clear.
        See Fig. 5 for details.
        """,
        [("4", ""), ("5", "")],
        id="non_parenthetic",
    ),
    pytest.param(
        """
        Results are shown in Figure \\ref{fig:methods}.
        (Fig. \\ref{fig:results}A)
        """,
        [("fig:methods", ""), ("fig:results", "A")],
        id="latex",
    ),
    pytest.param(
        """
        Results shown in (Fig. 3B, 3C).
        Also see (Figure 4A-C).
        """,
        [("3", "B"), ("3", "C"), ("4", "A-C")],
        id="multi_panel_same_figure",
    ),
    pytest.param(
        """
        Results are shown (Fig. \\ref{clustering-comp}A, see Methods).
        Additional data (Fig. \\ref{clustering-comp}B; see Supplement).
        """,
        [("clustering-comp", "A"), ("clustering-comp", "B")],
        id="punctuation_after_panel",
    ),
    pytest.param(
        """
        See the results (Fig. \\ref{bulk-analysis} D).
        Also shown in (Fig. \\ref{test-figure} C).
        """,
        [("bulk-analysis", ""), ("test-figure", "")],
        id="space_before_panel_is_error",
    ),
    pytest.param(
        """
        Standard reference (Fig. \\ref{test}A).
        Reference with space (Fig. \\ref{test} B).
        Reference with comma (Fig. \\ref{test}C, see Methods).
        Reference with semicolon (Fig. \\ref{test}D; additional info).
        """,
        [("test", "A"), ("test", ""), ("test", "C"), ("test", "D")],
        id="latex_various_formats",
    ),
    pytest.param(
        """
        Reference with comma: (Fig. \\ref{test}A, see Methods)
        Reference with semicolon: (Fig. \\ref{test}B; additional info)
        Reference with period: (Fig. \\ref{test}C).
        Reference clean: (Fig. \\ref{test}D)
        """,
        [("test", "A"), ("test", "B"), ("test", "C"), ("test", "D")],
        id="punctuation_variations",
    ),
    pytest.param(
        """
        Correct reference: (Fig. \\ref{test}A)
        Error with space: (Fig. \\ref{test} B)
        Another error: (Fig. \\ref{other} C)
        Correct again: (Fig. \\ref{test}D)
        """,
        [("test", "A"), ("test", ""), ("other", ""), ("test", "D")],
        id="space_errors",
    ),
    pytest.param(
        """
        Results were specific (Fig. 2C, Fig. S2), and the analysis confirmed this.
        The AUC was high (AUC >98%; Fig. 4C) as expected.
        Another example (see Fig. 3B for details).
        """,
        [("2", "C"), ("S2", ""), ("4", "C"), ("3", "B")],
        id="refs_in_parentheses_with_other_text",
    ),
    pytest.param(
        """
        Results shown (Fig. 1A, Fig. 1B, Fig. 2) are significant.
        Both methods work (see Fig. 3 and Fig. 4).
        Compare results (Fig. 5A vs Fig. 5B).
        """,
        [
            ("1", "A"),
            ("1", "B"),
            ("2", ""),
            ("3", ""),
            ("4", ""),
            ("5", "A"),
            ("5", "B"),
        ],
        id="multiple_figures_in_same_parentheses",
    ),
    pytest.param(
        """
        The AUC was high (AUC >98%; Fig. 4C) as expected.
        The specificity was good (specificity >95%, Fig. 5A) in tests.
        Results were significant (p<0.05; see Fig. 6B).
        """,
        [("4", "C"), ("5", "A"), ("6", "B")],
        id="figure_with_text_before_it_in_parentheses",
    ),
]


@pytest.mark.parametrize("markdown, expected", EXTRACT_CASES)
def test_extract_figure_references_formats(dc, markdown, expected):
    refs = dc.extract_figure_references(markdown)
    assert [(r.figure_num, r.panels) for r in refs] == expected


def test_skip_image_definitions(dc):
    """Image definitions and reference-style link defs are not figure references."""
    markdown = """
        ![Figure 1: Caption](path/to/figure.png)
        [fig1]: path/to/figure.png

        This is a real reference (Fig. 1).
        """

    refs = dc.extract_figure_references(markdown)

    assert len(refs) == 1
    assert refs[0].line_num == 5


PARSE_FIGURE_REFERENCE_CASES = [
    ("(Fig. 1)", ("1", "")),
    ("(Figure 2A)", ("2", "A")),
    ("(Fig. 3B-D)", ("3", "B-D")),
    ("Figure S1", ("S1", "")),
    ("(Supplemental Figure 2)", ("2", "")),
    ("Figure \\ref{fig:test}", ("fig:test", "")),
    ("Figure \\ref{fig:test}C", ("fig:test", "C")),
]


@pytest.mark.parametrize("ref_text, expected", PARSE_FIGURE_REFERENCE_CASES)
def test_parse_figure_reference_formats(dc, ref_text, expected):
    assert dc.parse_figure_reference(ref_text) == expected


def test_line_numbers_correct(dc):
    markdown = """Line 1
Line 2 with (Fig. 1).
Line 3
Line 4 with (Fig. 2).
"""
    refs = dc.extract_figure_references(markdown)

    assert refs[0].line_num == 2
    assert refs[1].line_num == 4


def test_context_extraction(dc):
    markdown = "This is some text before (Fig. 1) and some text after."

    refs = dc.extract_figure_references(markdown)

    assert len(refs) == 1
    context = refs[0].context
    assert "text before" in context
    assert "text after" in context


# ---------------------------------------------------------------------------
# detect_figure_warnings
# ---------------------------------------------------------------------------

WARNING_CASES = [
    pytest.param(
        """
        This is shown in Figure 1.
        As described in Figure 2, the results are clear.
        Figure 3 shows the data.
        """,
        [("no_parentheses", "3")],
        id="standalone_figure_warns",
    ),
    pytest.param(
        """
        As shown in Figure 1, the results are clear.
        See Figure 2 for details.
        Results are shown in Figure 3.
        As described in Figure 4.
        As illustrated in Figure 5.
        """,
        [],
        id="acceptable_contexts_no_warning",
    ),
]


@pytest.mark.parametrize("markdown, expected", WARNING_CASES)
def test_detect_figure_warnings(dc, markdown, expected):
    refs = dc.extract_figure_references(markdown)
    warnings = dc.detect_figure_warnings(refs)
    assert [(w["type"], w["figure"]) for w in warnings] == expected


# ---------------------------------------------------------------------------
# validate_figure_order: numeric and supplemental ordering/gaps
# ---------------------------------------------------------------------------

FIGURE_ORDER_CASES = [
    pytest.param(
        """
        First reference (Fig. 1).
        Second reference (Fig. 2).
        Third reference (Fig. 3).
        """,
        [],
        id="correct_order",
    ),
    pytest.param(
        """
        First reference (Fig. 2).
        Second reference (Fig. 1).
        Third reference (Fig. 3).
        """,
        [("out_of_order", "1")],
        id="out_of_order",
    ),
    pytest.param(
        """
        Main figure (Fig. 1).
        First supplemental (Figure S1).
        Second supplemental (Figure S3).
        Third supplemental (Figure S2).
        """,
        [("out_of_order", "S2")],
        id="supplemental_out_of_order",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. 1) and (Fig. 2) and (Fig. 3).

        ![Figure 1](fig1.svg)
        ![Figure 2](fig2.svg)
        ![Figure 3](fig3.svg)
        """,
        [],
        id="numeric_in_order",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. 3) and then (Fig. 1).
        """,
        [("out_of_order", "1"), ("missing_figure", "2")],
        id="numeric_out_of_order",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. S1) and (Fig. S2) and (Fig. S3).
        """,
        [],
        id="numeric_supplemental_in_order",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. S3) and then (Fig. S1).
        """,
        [("out_of_order", "S1"), ("missing_figure", "S2")],
        id="numeric_supplemental_out_of_order",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. 1) and (Fig. 5).
        """,
        [
            ("missing_figure", "2"),
            ("missing_figure", "3"),
            ("missing_figure", "4"),
        ],
        id="numeric_gap",
    ),
    pytest.param(
        """
        Main text:
        See (Fig. S1) and (Fig. S4) and (Fig. S10).
        """,
        [
            ("missing_figure", "S2"),
            ("missing_figure", "S3"),
            ("missing_figure", "S5"),
            ("missing_figure", "S6"),
            ("missing_figure", "S7"),
            ("missing_figure", "S8"),
            ("missing_figure", "S9"),
        ],
        id="numeric_supplemental_gap",
    ),
]


@pytest.mark.parametrize("markdown, expected", FIGURE_ORDER_CASES)
def test_validate_figure_order(dc, markdown, expected):
    refs = dc.extract_figure_references(markdown)
    violations = dc.validate_figure_order(refs)
    assert [(v["type"], v["figure"]) for v in violations] == expected


# ---------------------------------------------------------------------------
# validate_panel_order
# ---------------------------------------------------------------------------

PANEL_ORDER_CASES = [
    pytest.param(
        """
        First reference (Fig. 1B).
        Second reference (Fig. 2).
        Third reference (Fig. 1D).
        Fourth reference (Fig. 3C).
        """,
        [
            ("missing_panel_A", "1", None),
            ("missing_panel", "1", "A"),
            ("missing_panel", "1", "C"),
            ("missing_panel_A", "3", None),
        ],
        id="missing_panel_a_and_gap",
    ),
    pytest.param(
        """
        First (Fig. 5A).
        Then (Fig. 5C).
        Finally (Fig. 5E).
        """,
        [("missing_panel", "5", "B"), ("missing_panel", "5", "D")],
        id="gaps_in_sequence",
    ),
    pytest.param(
        """
        Figure with missing A: (Fig. 1B)
        Then has C: (Fig. 1C)
        Missing D: (Fig. 1E)

        Figure starting correctly: (Fig. 2A)
        Then B: (Fig. 2B)
        Skip to D: (Fig. 2D)
        """,
        [
            ("missing_panel_A", "1", None),
            ("missing_panel", "1", "A"),
            ("missing_panel", "1", "D"),
            ("missing_panel", "2", "C"),
        ],
        id="two_figures_comprehensive",
    ),
    pytest.param(
        """
        First (Fig. 1A).
        Second (Fig. 1B).
        Third (Fig. 1C).
        """,
        [],
        id="complete_sequence_no_violations",
    ),
]


@pytest.mark.parametrize("markdown, expected", PANEL_ORDER_CASES)
def test_validate_panel_order(dc, markdown, expected):
    refs = dc.extract_figure_references(markdown)
    violations = dc.validate_panel_order(refs)
    assert [(v["type"], v["figure"], v.get("missing_panel")) for v in violations] == expected


# ---------------------------------------------------------------------------
# generate_figure_analysis_report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markdown",
    ["", "This is text without any figure references."],
    ids=["empty_markdown", "no_references"],
)
def test_report_empty_when_no_references(dc, markdown):
    assert dc.generate_figure_analysis_report(markdown) == ""


REPORT_CASES = [
    pytest.param(
        """
        First (Fig. 2).
        Second (Fig. 1).
        Third Figure 3 shows the data.
        """,
        [
            "FIGURE REFERENCE ANALYSIS",
            "Total figure references found: 3",
            "FIGURE ORDER VIOLATIONS",
            "FIGURE REFERENCE WARNINGS",
        ],
        [],
        id="out_of_order_and_unparenthesized",
    ),
    pytest.param(
        """
        First (Fig. 1).
        Second (Fig. 2).
        Third (Fig. 3).
        """,
        ["FIGURE REFERENCE ANALYSIS", "All figure references appear to be in order!"],
        ["VIOLATIONS", "WARNINGS"],
        id="all_correct",
    ),
    pytest.param(
        """
        Introduction shows (Fig. 1C).
        Methods describe (Fig. 2).
        Results show (Fig. 1A).
        Discussion mentions (Fig. 3B).
        """,
        [
            "PANEL ORDER VIOLATIONS",
            "panel A was never referenced",
            "Figure 1",
            "Figure 3",
        ],
        [],
        id="panel_violations",
    ),
]


@pytest.mark.parametrize("markdown, must_contain, must_not_contain", REPORT_CASES)
def test_generate_figure_analysis_report(dc, markdown, must_contain, must_not_contain):
    report = dc.generate_figure_analysis_report(markdown)
    for text in must_contain:
        assert text in report
    for text in must_not_contain:
        assert text not in report


def test_real_manuscript_example(dc):
    markdown = """
# Introduction

Previous work has shown interesting results (Fig. 1A). We extend this work
by analyzing additional data (Fig. 2).

# Methods

The experimental setup is illustrated in Figure \\ref{fig:methods}.

# Results

Our findings (Fig. 3A-C) demonstrate the effectiveness of the approach.
Supplemental data is provided (Figure S1).

# Discussion

As shown in Figure 4, our results align with previous studies. However,
Figure 2 revealed unexpected patterns that warrant further investigation.
"""

    report = dc.generate_figure_analysis_report(markdown)

    assert "FIGURE REFERENCE ANALYSIS" in report
    assert "Total figure references found:" in report

    refs = dc.extract_figure_references(markdown)
    figure_nums = [r.figure_num for r in refs if "\\ref{" not in str(r.figure_num)]

    assert {"1", "2", "3", "4", "S1"} <= set(figure_nums)


# ---------------------------------------------------------------------------
# Regression tests for specific ordering/parsing bugs
# ---------------------------------------------------------------------------


def test_multi_panel_same_figure_in_parentheses(dc):
    """
    Test that multi-panel references like (Fig. 3A, 3B) are correctly parsed.

    This is a regression test for a bug where (Fig. 3A, 3B) was being split
    into separate matches, causing only panel A to be recorded, and panel B
    to be recorded at a later line when it appeared standalone. This caused
    false positive panel order violations.
    """
    markdown = """
        De novo motif analysis across region subgroups highlighted MADS box (MEF2 family)
        and C4 zinc-finger classes in primary WT samples and bZIP (ATF/AP-1) class in
        Tumoral samples (Fig. 3A, 3B), consistent with prior studies. We observed similar
        patterns in other pairwise combinations. Single-cell RNA-seq from JG cells supported
        candidate factors within motif families (e.g., Mef2d, Mafg; Fig. 3C). Interestingly,
        in the recruited group, the top motifs were a mix of the top motifs found in the
        WT and tumoral groups.

        Later in the document:
        We conducted de novo motif enrichment analyses for the core renin-specific regions.
        In the core renin-specific regions, the top enriched motifs were the MADS box class,
        bZip class, and C4 zinc finger class (Fig. 3A). For the other combination sets, we
        found notable differences in the top enriched TF motifs among the 3 groups (Fig. 3B).
        """

    refs = dc.extract_figure_references(markdown)

    fig3_refs = [(ref.panels, ref.line_num) for ref in refs if ref.figure_num == "3"]

    panel_a_lines = [line for panel, line in fig3_refs if panel == "A"]
    assert len(panel_a_lines) >= 1, "Panel A should be found"
    first_a_line = min(panel_a_lines)

    # Panel B should ALSO first appear on line 4 (in "Fig. 3A, 3B"), NOT later
    panel_b_lines = [line for panel, line in fig3_refs if panel == "B"]
    assert len(panel_b_lines) >= 1, "Panel B should be found"
    first_b_line = min(panel_b_lines)

    panel_c_lines = [line for panel, line in fig3_refs if panel == "C"]
    assert len(panel_c_lines) >= 1, "Panel C should be found"

    assert first_a_line == first_b_line, (
        "Panel A and B should both be first recorded on the same line (from "
        f"'Fig. 3A, 3B'), but A was on line {first_a_line} and B on {first_b_line}"
    )

    panel_violations = dc.validate_panel_order(refs)

    fig3_order_violations = [
        v for v in panel_violations if v["figure"] == "3" and v["type"] == "panel_out_of_order"
    ]
    assert len(fig3_order_violations) == 0, (
        f"Should have no panel order violations for Fig 3, but found: {fig3_order_violations}"
    )

    fig3_missing_violations = [
        v
        for v in panel_violations
        if v["figure"] == "3" and v["type"] in ["missing_panel_A", "missing_panel"]
    ]
    assert len(fig3_missing_violations) == 0, (
        f"Should have no missing panel violations for Fig 3, but found: {fig3_missing_violations}"
    )


def test_multiple_panels_same_line_correct_order(dc):
    """
    Test that multiple panel references on the same line in correct order
    do not trigger false positive panel order violations.

    Regression test for bug where (Figure 7A)...(Figure 7B)...(Figure 7C)...(Figure 7D)
    all on the same line were incorrectly flagged as out of order because the
    sort by line number didn't preserve text position order.
    """
    # This exact text was incorrectly flagging "Figure 7 panel B appears before panel D"
    markdown = """(Figure 7A). To make it simpler to interpret results of the comparison function, we developed the Seqcol Comparison Interpretation Module (SCIM), which allows a user to paste the output of a comparison endpoint and get a human-friendly interpretation of the result (Figure 7B; https://refget.databio.org/scim). This module interprets the numbers of the comparison into a simpler, understandable observation about how related two sequence collections are. To extend this reference discovery, or identifying existing collections that are similar in some way to a user-provided query, we developed the Seqcol Comparison Overview Module (SCOM), which goes beyond the 1-to-1 query provided by the comparison API to a 1-vs-many comparison. Users with a query collection can send this to the server, which iteratively compares it to each of the human or mouse reference genomes assembled for the analysis in this paper, and aggregates the results (Figure 7C;  https://refget.databio.org/scom). The resulting summary figure describes similarity scores for the 4 key attributes, highlighting existing references that may be usable for the analysis, encouraging reuse (Figure 7D)."""

    refs = dc.extract_figure_references(markdown)

    fig7_refs = [(ref.panels, ref.line_num) for ref in refs if ref.figure_num == "7"]
    panels_found = [panel for panel, line in fig7_refs]
    assert "A" in panels_found, "Should find panel A"
    assert "B" in panels_found, "Should find panel B"
    assert "C" in panels_found, "Should find panel C"
    assert "D" in panels_found, "Should find panel D"

    panel_violations = dc.validate_panel_order(refs)

    fig7_order_violations = [
        v for v in panel_violations if v["figure"] == "7" and v["type"] == "panel_out_of_order"
    ]
    assert len(fig7_order_violations) == 0, (
        "Should have no panel order violations for Fig 7 (panels are in A,B,C,D "
        f"order), but found: {fig7_order_violations}"
    )

    fig7_missing_violations = [
        v
        for v in panel_violations
        if v["figure"] == "7" and v["type"] in ["missing_panel_A", "missing_panel"]
    ]
    assert len(fig7_missing_violations) == 0, (
        f"Should have no missing panel violations for Fig 7, but found: {fig7_missing_violations}"
    )


def test_figure_order_with_parenthetical_context(dc):
    """Figure order validation should not treat "Fig. S2" inside a complex
    parenthetical (with other figures/text) as an isolated, out-of-place ref."""
    markdown = """
        The results were specific (Fig. 2C, Fig. S2), and we confirmed this.
        Earlier work showed (AUC >98%; Fig. 4C) that the method was effective.
        Figure 4 panel D referenced (Fig. 4D) after some other text.
        """

    refs = dc.extract_figure_references(markdown)
    violations = dc.validate_figure_order(refs)

    missing_s2 = [v for v in violations if v["type"] == "missing_figure" and v["figure"] == "S2"]
    assert len(missing_s2) == 0, f"Incorrectly reported S2 as missing. Violations: {violations}"


def test_panel_order_with_parenthetical_context(dc):
    """Panel order validation should not be confused by non-figure text
    sharing the parentheses with a figure/panel reference."""
    markdown = """
        Initial analysis (AUC >98%; Fig. 4A) showed promising results.
        Further work (precision >95%; Fig. 4B) confirmed this.
        The final results (sensitivity >90%; Fig. 4C) were conclusive.
        Additional data (specificity >92%; Fig. 4D) supported the findings.
        """

    refs = dc.extract_figure_references(markdown)
    panel_violations = dc.validate_panel_order(refs)

    fig4_violations = [v for v in panel_violations if v["figure"] == "4"]
    assert len(fig4_violations) == 0, (
        f"Incorrectly reported panel violations for Fig 4: {fig4_violations}"
    )


# ---------------------------------------------------------------------------
# Comprehensive plan example: split from a single 110-line mega-test into
# focused checks, sharing the source markdown as a module constant.
# ---------------------------------------------------------------------------

PLAN_EXAMPLE_MARKDOWN = """
# Introduction

The overview figure shows our approach (Fig. \\ref{overview}A). We can see the overall design
(Fig. \\ref{overview}B) and how it relates to the implementation.

Further details are shown (Fig. \\ref{overview}C).

The main components (Fig. \\ref{overview}D) and distribution (Fig. \\ref{context-window-distribution})
are illustrated.

# Methods

Our craft analysis (Fig. \\ref{craft}B) reveals interesting patterns. The modality comparison
(Fig. \\ref{craft-by-modality}) and additional details (Fig. \\ref{craft}C) support this.
The final results (Fig. \\ref{craft}D) are conclusive.

Extended analysis (Fig. \\ref{craft}F) and supplemental data (Fig. \\ref{craft}G) provide
additional context. The summary (Fig. \\ref{craft}H) concludes this section.

# Results

## Clustering Analysis

Initial clustering (Fig. \\ref{clustering-comp}B) shows the patterns.

Now we test the problematic references:
- With comma after panel: (Fig. \\ref{clustering-comp}A, see Methods)
- With semicolon after panel: (Fig. \\ref{clustering-comp}A; see Methods)

## Context Window Analysis

The analysis results (Fig. \\ref{context-window-analysis}) are shown. Additional panels
(Fig. \\ref{context-window-analysis}B), (Fig. \\ref{context-window-analysis}C),
(Fig. \\ref{context-window-analysis}D), and (Fig. \\ref{context-window-analysis}E) provide details.

Further clustering (Fig. \\ref{clustering-comp}E) and fragment analysis (Fig. \\ref{fragments-bc})
complete this section.

## Bulk Analysis

The bulk analysis (Fig. \\ref{bulk-analysis}F) shows expected results.

This reference has a space before the panel (an error): (Fig. \\ref{bulk-analysis} D)

## Cell Line Analysis

The distribution (Fig. \\ref{assay-cell-line-dists}) is shown.

## Fragment Analysis

Additional fragments (Fig. \\ref{fragments-analysis}C) are analyzed.

The main fragment analysis (Fig. \\ref{fragments-analysis}) provides the overview.

# Discussion

As shown in Figure 3, our results are significant.
"""


def test_plan_example_punctuation_after_panel_caught(dc):
    """References with punctuation immediately after the panel letter (comma,
    semicolon) are still recognized and the panel is still extracted."""
    refs = dc.extract_figure_references(PLAN_EXAMPLE_MARKDOWN)

    clustering_comp_a = [r for r in refs if r.figure_num == "clustering-comp" and r.panels == "A"]
    assert len(clustering_comp_a) == 2, (
        f"Expected 2 clustering-comp panel A refs, found {len(clustering_comp_a)}"
    )


def test_plan_example_space_before_panel_extracts_no_panel(dc):
    """A space between the \\ref{} and the panel letter is a LaTeX error, so
    no panel should be extracted for that reference."""
    refs = dc.extract_figure_references(PLAN_EXAMPLE_MARKDOWN)

    bulk_refs = [r for r in refs if r.figure_num == "bulk-analysis"]
    assert len(bulk_refs) == 2, f"Expected 2 bulk-analysis refs, found {len(bulk_refs)}"

    space_error_refs = [r for r in bulk_refs if " D)" in r.context and r.panels == ""]
    assert len(space_error_refs) == 1, "Should find 1 reference with space before D in context"
    assert space_error_refs[0].panels == ""


def test_plan_example_panel_order_violations_per_figure(dc):
    refs = dc.extract_figure_references(PLAN_EXAMPLE_MARKDOWN)
    panel_violations = dc.validate_panel_order(refs)

    expected_violations = {
        "clustering-comp": "panel_out_of_order",  # A appears after B (out of order)
        "context-window-analysis": "missing_panel_A",  # No A, starts with B
        "fragments-analysis": "missing_panel_A",  # C appears without A
        "craft": "missing_panel_A",  # Starts with B
        "bulk-analysis": "missing_panel_A",  # Starts with F
    }

    for fig, violation_type in expected_violations.items():
        matching = [
            v for v in panel_violations if fig in str(v["figure"]) and v["type"] == violation_type
        ]
        assert len(matching) > 0, f"Failed to detect {violation_type} for {fig}"


def test_plan_example_panel_gap_violations(dc):
    refs = dc.extract_figure_references(PLAN_EXAMPLE_MARKDOWN)
    panel_violations = dc.validate_panel_order(refs)

    gap_violations = [v for v in panel_violations if v["type"] == "missing_panel"]
    # craft has panels B, C, D, F, G, H -- missing E
    craft_gaps = [v for v in gap_violations if "craft" in str(v["figure"])]
    assert len(craft_gaps) > 0, "Should detect gap violations in craft figure"


def test_plan_example_report_generation(dc):
    report = dc.generate_figure_analysis_report(PLAN_EXAMPLE_MARKDOWN)
    assert "FIGURE REFERENCE ANALYSIS" in report
    assert "PANEL ORDER VIOLATIONS" in report


# ---------------------------------------------------------------------------
# TestLabelFigureValidation: LaTeX label-based figure validation
# ---------------------------------------------------------------------------

LABEL_EXTRACTION_CASES = [
    pytest.param(
        r"""
        ![**\label{overview} Figure 1.** Overview diagram](fig/overview.svg)
        ![**\label{methods} Figure 2.** Methods schematic](fig/methods.svg)
        """,
        {"overview": "main", "methods": "main"},
        id="main_figures",
    ),
    pytest.param(
        r"""
        ![**\label{supp-data} Supplemental Figure 1.** Extra data](fig/supp1.svg)
        ![**\label{supp-methods} Supplemental Figure 2.** Methods details](fig/supp2.svg)
        """,
        {"supp-data": "supplemental", "supp-methods": "supplemental"},
        id="supplemental_figures",
    ),
]


@pytest.mark.parametrize("content, expected_types", LABEL_EXTRACTION_CASES)
def test_extract_figure_labels(dc, content, expected_types):
    labels = dc.extract_figure_labels(content)
    for label, fig_type in expected_types.items():
        assert label in labels
        assert labels[label][1] == fig_type


LABEL_ORDER_CASES = [
    pytest.param(
        r"""
        Main text:
        See Fig. \ref{suppfig1} and Fig. \ref{suppfig2}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        """,
        [],
        id="correct_order",
    ),
    pytest.param(
        r"""
        Main text:
        See Fig. \ref{suppfig2} for details.
        Also see Fig. \ref{suppfig1}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        """,
        [("label_out_of_order", "suppfig1", "suppfig2")],
        id="out_of_order",
    ),
    pytest.param(
        r"""
        Main text:
        See Fig. \ref{suppfig1} and Fig. \ref{suppfig3}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        ![**\label{suppfig3} Supplemental Figure \ref{suppfig3}.**](fig3.svg)
        """,
        [("missing_supplemental_label", "suppfig2", None)],
        id="gap",
    ),
]


@pytest.mark.parametrize("content, expected", LABEL_ORDER_CASES)
def test_label_figure_order(dc, content, expected):
    refs = dc.extract_figure_references(content)
    violations = dc.validate_figure_order(refs, content)
    assert [(v["type"], v["figure"], v.get("expected_after")) for v in violations] == expected


def test_mixed_numeric_and_label_references(dc):
    """A document using both numeric (Fig. 1, Fig. S1) and label-based
    (\\ref{overview}, \\ref{supp-data}) references for otherwise-consistent,
    in-order figures gets flagged only for the style mix, not spurious
    ordering/gap violations."""
    content = r"""
        Main text:
        See (Fig. 1) and Fig. \ref{overview}.
        Also (Fig. S1) and Fig. \ref{supp-data}.

        ![Figure 1](fig1.svg)
        ![**\label{overview} Figure 2.**](fig2.svg)

        # Supplement
        ![**\label{supp-data} Supplemental Figure \ref{supp-data}.**](supp1.svg)
        """

    refs = dc.extract_figure_references(content)
    violations = dc.validate_figure_order(refs, content)

    assert [v["type"] for v in violations] == ["mixed_reference_style"]
