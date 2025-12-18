"""
Tests for figure reference analysis functionality.
"""

import pytest
from markmeld.document_checker import DocumentChecker


class TestFigureReferences:
    """Test suite for figure reference extraction and validation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.dc = DocumentChecker()
    
    def test_extract_parenthetic_references(self):
        """Test extraction of parenthetic figure references."""
        markdown = """
        Some text with a figure reference (Fig. 1).
        Another reference (Figure 2A).
        Multiple panels (Fig. 3B-D).
        Supplemental figure (Figure S1).
        """
        
        refs = self.dc.extract_figure_references(markdown)
        
        assert len(refs) == 4
        assert refs[0][1] == '1'  # Figure number
        assert refs[0][2] == ''    # No panels
        assert refs[1][1] == '2'   # Figure number
        assert refs[1][2] == 'A'   # Panel A
        assert refs[2][1] == '3'
        assert refs[2][2] == 'B-D'
        assert refs[3][1] == 'S1'
    
    def test_extract_non_parenthetic_references(self):
        """Test extraction of non-parenthetic figure references."""
        markdown = """
        As shown in Figure 4, the results are clear.
        See Fig. 5 for details.
        """
        
        refs = self.dc.extract_figure_references(markdown)
        
        assert len(refs) == 2
        assert refs[0][1] == '4'
        assert refs[1][1] == '5'
    
    def test_extract_latex_references(self):
        """Test extraction of LaTeX \\ref{} style references."""
        markdown = """
        Results are shown in Figure \\ref{fig:methods}.
        (Fig. \\ref{fig:results}A)
        """
        
        refs = self.dc.extract_figure_references(markdown)
        
        assert len(refs) == 2
        assert refs[0][1] == 'fig:methods'
        assert refs[1][1] == 'fig:results'
        assert refs[1][2] == 'A'  # Panel A
    
    def test_skip_image_definitions(self):
        """Test that image definitions are not counted as references."""
        markdown = """
        ![Figure 1: Caption](path/to/figure.png)
        [fig1]: path/to/figure.png
        
        This is a real reference (Fig. 1).
        """
        
        refs = self.dc.extract_figure_references(markdown)
        
        # Should only find the real reference, not the image definitions
        assert len(refs) == 1
        assert refs[0][3] == 5  # Line number of the real reference (line 5)
    
    def test_parse_figure_reference_formats(self):
        """Test parsing of various figure reference formats."""
        test_cases = [
            ("(Fig. 1)", ('1', '')),
            ("(Figure 2A)", ('2', 'A')),
            ("(Fig. 3B-D)", ('3', 'B-D')),
            ("Figure S1", ('S1', '')),
            ("(Supplemental Figure 2)", ('2', '')),
            ("Figure \\ref{fig:test}", ('fig:test', '')),
            ("Figure \\ref{fig:test}C", ('fig:test', 'C')),
        ]
        
        for ref_text, expected in test_cases:
            result = self.dc.parse_figure_reference(ref_text)
            assert result == expected, f"Failed for {ref_text}"
    
    def test_validate_correct_order(self):
        """Test validation when figures are in correct order."""
        markdown = """
        First reference (Fig. 1).
        Second reference (Fig. 2).
        Third reference (Fig. 3).
        """
        
        refs = self.dc.extract_figure_references(markdown)
        violations = self.dc.validate_figure_order(refs)
        
        assert len(violations) == 0
    
    def test_validate_out_of_order(self):
        """Test validation when figures are out of order."""
        markdown = """
        First reference (Fig. 2).
        Second reference (Fig. 1).
        Third reference (Fig. 3).
        """
        
        refs = self.dc.extract_figure_references(markdown)
        violations = self.dc.validate_figure_order(refs)
        
        assert len(violations) == 1
        assert violations[0]['type'] == 'out_of_order'
        assert violations[0]['figure'] == '1'
        assert violations[0]['expected_after'] == '2'
    
    def test_validate_supplemental_order(self):
        """Test validation of supplemental figure order."""
        markdown = """
        Main figure (Fig. 1).
        First supplemental (Figure S1).
        Second supplemental (Figure S3).
        Third supplemental (Figure S2).
        """
        
        refs = self.dc.extract_figure_references(markdown)
        violations = self.dc.validate_figure_order(refs)
        
        # Should find violation for S2 appearing after S3
        assert len(violations) == 1
        assert violations[0]['figure'] == 'S2'
    
    def test_detect_parentheses_warnings(self):
        """Test detection of references without parentheses."""
        markdown = """
        This is shown in Figure 1.
        As described in Figure 2, the results are clear.
        Figure 3 shows the data.
        """
        
        refs = self.dc.extract_figure_references(markdown)
        warnings = self.dc.detect_figure_warnings(refs)
        
        # Only "Figure 3 shows" should generate a warning
        # The others have acceptable context phrases
        assert len(warnings) == 1
        assert warnings[0]['type'] == 'no_parentheses'
        assert warnings[0]['figure'] == '3'
    
    def test_no_warnings_for_acceptable_contexts(self):
        """Test that acceptable non-parenthetic contexts don't generate warnings."""
        markdown = """
        As shown in Figure 1, the results are clear.
        See Figure 2 for details.
        Results are shown in Figure 3.
        As described in Figure 4.
        As illustrated in Figure 5.
        """
        
        refs = self.dc.extract_figure_references(markdown)
        warnings = self.dc.detect_figure_warnings(refs)
        
        # All these are acceptable contexts
        assert len(warnings) == 0
    
    def test_generate_report_with_violations(self):
        """Test report generation with order violations."""
        markdown = """
        First (Fig. 2).
        Second (Fig. 1).
        Third Figure 3 shows the data.
        """
        
        report = self.dc.generate_figure_analysis_report(markdown)
        
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "Total figure references found: 3" in report
        assert "FIGURE ORDER VIOLATIONS" in report
        assert "FIGURE REFERENCE WARNINGS" in report
    
    def test_generate_report_all_correct(self):
        """Test report generation when everything is correct."""
        markdown = """
        First (Fig. 1).
        Second (Fig. 2).
        Third (Fig. 3).
        """
        
        report = self.dc.generate_figure_analysis_report(markdown)
        
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "All figure references appear to be in order!" in report
        assert "VIOLATIONS" not in report
        assert "WARNINGS" not in report
    
    def test_empty_markdown(self):
        """Test handling of empty markdown content."""
        report = self.dc.generate_figure_analysis_report("")
        assert report == ""
    
    def test_no_references(self):
        """Test handling of markdown with no figure references."""
        markdown = "This is text without any figure references."
        report = self.dc.generate_figure_analysis_report(markdown)
        assert report == ""
    
    def test_complex_multi_panel_references(self):
        """Test extraction of complex multi-panel references."""
        markdown = """
        Results shown in (Fig. 3B, 3C).
        Also see (Figure 4A-C).
        """

        refs = self.dc.extract_figure_references(markdown)

        # Should find the references
        assert len(refs) >= 1
        # Check that we found at least the main references
        found_figures = [ref[1] for ref in refs]
        assert '3' in found_figures or '3B,3C' in found_figures
        assert '4' in found_figures

    def test_references_with_punctuation_after_panel(self):
        """Test extraction of references with punctuation after panel letters."""
        markdown = """
        Results are shown (Fig. \\ref{clustering-comp}A, see Methods).
        Additional data (Fig. \\ref{clustering-comp}B; see Supplement).
        """

        refs = self.dc.extract_figure_references(markdown)

        assert len(refs) == 2
        # Check that panels were extracted correctly
        assert refs[0][1] == 'clustering-comp'
        assert refs[0][2] == 'A'
        assert refs[1][1] == 'clustering-comp'
        assert refs[1][2] == 'B'

    def test_references_with_space_before_panel(self):
        """Test extraction of references with spaces before panel letters (which is an error)."""
        markdown = """
        See the results (Fig. \\ref{bulk-analysis} D).
        Also shown in (Fig. \\ref{test-figure} C).
        """

        refs = self.dc.extract_figure_references(markdown)

        assert len(refs) == 2
        # Space before panel is an ERROR - panels should NOT be extracted
        assert refs[0][1] == 'bulk-analysis'
        assert refs[0][2] == ''  # No panel should be detected due to space
        assert refs[1][1] == 'test-figure'
        assert refs[1][2] == ''  # No panel should be detected due to space

    def test_panel_order_violations(self):
        """Test detection of panel order violations."""
        markdown = """
        First reference (Fig. 1B).
        Second reference (Fig. 2).
        Third reference (Fig. 1D).
        Fourth reference (Fig. 3C).
        """

        refs = self.dc.extract_figure_references(markdown)
        panel_violations = self.dc.validate_panel_order(refs)

        # Should detect missing panel A for Figure 1
        missing_a = [v for v in panel_violations if v['type'] == 'missing_panel_A' and v['figure'] == '1']
        assert len(missing_a) == 1

        # Should detect missing panel C for Figure 1
        missing_c = [v for v in panel_violations if v['type'] == 'missing_panel' and v['figure'] == '1' and v['missing_panel'] == 'C']
        assert len(missing_c) == 1

        # Should detect missing panel A for Figure 3
        missing_3a = [v for v in panel_violations if v['type'] == 'missing_panel_A' and v['figure'] == '3']
        assert len(missing_3a) == 1

    def test_panel_sequence_with_gaps(self):
        """Test detection of gaps in panel sequences."""
        markdown = """
        First (Fig. 5A).
        Then (Fig. 5C).
        Finally (Fig. 5E).
        """

        refs = self.dc.extract_figure_references(markdown)
        panel_violations = self.dc.validate_panel_order(refs)

        # Should detect missing panels B and D
        missing_panels = [v for v in panel_violations if v['type'] == 'missing_panel']
        panel_letters = [v['missing_panel'] for v in missing_panels]

        assert 'B' in panel_letters
        assert 'D' in panel_letters

    def test_latex_refs_with_various_formats(self):
        """Test LaTeX references with various formatting issues."""
        markdown = """
        Standard reference (Fig. \\ref{test}A).
        Reference with space (Fig. \\ref{test} B).
        Reference with comma (Fig. \\ref{test}C, see Methods).
        Reference with semicolon (Fig. \\ref{test}D; additional info).
        """

        refs = self.dc.extract_figure_references(markdown)

        # Should find all 4 references
        assert len(refs) == 4
        # Check panels - space before panel is an error, so B should not be detected
        assert refs[0][2] == 'A'  # Correct format
        assert refs[1][2] == ''   # Space is an error - no panel
        assert refs[2][2] == 'C'  # Comma after is OK
        assert refs[3][2] == 'D'  # Semicolon after is OK
    
    def test_line_numbers_correct(self):
        """Test that line numbers are correctly reported."""
        markdown = """Line 1
Line 2 with (Fig. 1).
Line 3
Line 4 with (Fig. 2).
"""
        
        refs = self.dc.extract_figure_references(markdown)
        
        assert refs[0][3] == 2  # Line number for Fig. 1
        assert refs[1][3] == 4  # Line number for Fig. 2
    
    def test_context_extraction(self):
        """Test that context is properly extracted around references."""
        markdown = "This is some text before (Fig. 1) and some text after."
        
        refs = self.dc.extract_figure_references(markdown)
        
        assert len(refs) == 1
        context = refs[0][4]
        assert "text before" in context
        assert "text after" in context


    def test_report_with_panel_violations(self):
        """Test report generation with panel order violations."""
        markdown = """
        Introduction shows (Fig. 1C).
        Methods describe (Fig. 2).
        Results show (Fig. 1A).
        Discussion mentions (Fig. 3B).
        """

        report = self.dc.generate_figure_analysis_report(markdown)

        # Check report contains panel violations
        assert "PANEL ORDER VIOLATIONS" in report
        assert "panel A was never referenced" in report
        assert "Figure 1" in report
        assert "Figure 3" in report

    def test_complete_panel_sequence(self):
        """Test that complete panel sequences are recognized as correct."""
        markdown = """
        First (Fig. 1A).
        Second (Fig. 1B).
        Third (Fig. 1C).
        """

        refs = self.dc.extract_figure_references(markdown)
        panel_violations = self.dc.validate_panel_order(refs)

        # Should have no violations
        assert len(panel_violations) == 0


class TestFigureReferenceIntegration:
    """Integration tests for figure reference functionality."""

    def test_real_manuscript_example(self):
        """Test with a real manuscript example."""
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

        dc = DocumentChecker()
        report = dc.generate_figure_analysis_report(markdown)

        # Check report contains expected elements
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "Total figure references found:" in report

        # Extract references to verify
        refs = dc.extract_figure_references(markdown)
        figure_nums = [ref[1] for ref in refs if not '\\ref{' in str(ref[1])]

        # Check we found the expected figures
        assert '1' in figure_nums
        assert '2' in figure_nums
        assert '3' in figure_nums
        assert '4' in figure_nums
        assert 'S1' in figure_nums

    def test_comprehensive_plan_example(self):
        """
        Comprehensive test from the plan example covering:
        1. Panel order violations (e.g., panel B appearing before panel A)
        2. Regex patterns catching references with punctuation after panels
        3. Regex patterns correctly identifying space before panel as an error
        """
        markdown = """
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
        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Test 1: Verify we catch references with punctuation after panels
        clustering_comp_refs = [r for r in refs if 'clustering-comp' in str(r[1]) and r[2] == 'A']
        # Should find 2 references to clustering-comp panel A (one with comma, one with semicolon)
        assert len(clustering_comp_refs) == 2, f"Expected 2 clustering-comp panel A refs, found {len(clustering_comp_refs)}"

        # Test 2: Verify space before panel is detected as error (no panel extracted)
        bulk_refs = [r for r in refs if 'bulk-analysis' in str(r[1])]
        # Should find 2 bulk-analysis references: F (without space) and the one with space before D
        assert len(bulk_refs) == 2, f"Expected 2 bulk-analysis refs, found {len(bulk_refs)}"

        # Check that the reference with space has no panel extracted
        # The space error is detectable by checking the context contains " D)" but panel is empty
        space_error_refs = [r for r in bulk_refs if ' D)' in r[4] and r[2] == '']
        assert len(space_error_refs) == 1, "Should find 1 reference with space before D in context"
        assert space_error_refs[0][2] == '', "Panel should NOT be extracted when space before panel"

        # Test 3: Verify panel order violations are detected
        panel_violations = dc.validate_panel_order(refs)

        # Check for specific expected violations
        expected_violations = {
            'clustering-comp': 'panel_out_of_order',  # A appears after B (out of order)
            'context-window-analysis': 'missing_panel_A',  # No A, starts with B
            'fragments-analysis': 'missing_panel_A',  # C appears without A
            'craft': 'missing_panel_A',  # Starts with B
            'bulk-analysis': 'missing_panel_A',  # Starts with F
        }

        for fig, violation_type in expected_violations.items():
            matching = [v for v in panel_violations
                       if fig in str(v['figure']) and v['type'] == violation_type]
            assert len(matching) > 0, f"Failed to detect {violation_type} for {fig}"

        # Test 4: Check for gap violations (missing panels between first and last)
        gap_violations = [v for v in panel_violations if v['type'] == 'missing_panel']
        # Should detect gaps in craft figure (B, C, D, F, G, H - missing E)
        craft_gaps = [v for v in gap_violations if 'craft' in str(v['figure'])]
        assert len(craft_gaps) > 0, "Should detect gap violations in craft figure"

        # Test 5: Verify report generation works for complex case
        report = dc.generate_figure_analysis_report(markdown)
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "PANEL ORDER VIOLATIONS" in report

    def test_plan_example_punctuation_variations(self):
        """Test specific punctuation variations from plan example."""
        markdown = """
        Reference with comma: (Fig. \\ref{test}A, see Methods)
        Reference with semicolon: (Fig. \\ref{test}B; additional info)
        Reference with period: (Fig. \\ref{test}C).
        Reference clean: (Fig. \\ref{test}D)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # All 4 references should be found with correct panels
        assert len(refs) == 4
        assert refs[0][2] == 'A'
        assert refs[1][2] == 'B'
        assert refs[2][2] == 'C'
        assert refs[3][2] == 'D'

    def test_plan_example_space_errors(self):
        """Test space before panel detection from plan example."""
        markdown = """
        Correct reference: (Fig. \\ref{test}A)
        Error with space: (Fig. \\ref{test} B)
        Another error: (Fig. \\ref{other} C)
        Correct again: (Fig. \\ref{test}D)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Should find 4 references
        assert len(refs) == 4
        # Check panels - spaces should result in no panel
        assert refs[0][2] == 'A'  # Correct
        assert refs[1][2] == ''   # Space error - no panel
        assert refs[2][2] == ''   # Space error - no panel
        assert refs[3][2] == 'D'  # Correct

    def test_plan_example_panel_order_comprehensive(self):
        """Test comprehensive panel order checking from plan example."""
        markdown = """
        Figure with missing A: (Fig. 1B)
        Then has C: (Fig. 1C)
        Missing D: (Fig. 1E)

        Figure starting correctly: (Fig. 2A)
        Then B: (Fig. 2B)
        Skip to D: (Fig. 2D)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)
        panel_violations = dc.validate_panel_order(refs)

        # Fig 1: Missing A (starts with B), missing D (gap between C and E)
        fig1_missing_a = [v for v in panel_violations
                         if v['figure'] == '1' and v['type'] == 'missing_panel_A']
        assert len(fig1_missing_a) == 1

        fig1_missing_d = [v for v in panel_violations
                         if v['figure'] == '1' and v['type'] == 'missing_panel' and v['missing_panel'] == 'D']
        assert len(fig1_missing_d) == 1

        # Fig 2: Should have gap for C
        fig2_missing_c = [v for v in panel_violations
                         if v['figure'] == '2' and v['type'] == 'missing_panel' and v['missing_panel'] == 'C']
        assert len(fig2_missing_c) == 1

    def test_references_in_parentheses_with_other_text(self):
        """Test extraction of references in parentheses that contain other text."""
        markdown = """
        Results were specific (Fig. 2C, Fig. S2), and the analysis confirmed this.
        The AUC was high (AUC >98%; Fig. 4C) as expected.
        Another example (see Fig. 3B for details).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Extract just the figure numbers and panels
        found = [(ref[1], ref[2]) for ref in refs]

        # Should find all these figures
        assert ('2', 'C') in found, f"Fig. 2C not found. Found: {found}"
        assert ('S2', '') in found, f"Fig. S2 not found. Found: {found}"
        assert ('4', 'C') in found, f"Fig. 4C not found. Found: {found}"
        assert ('3', 'B') in found, f"Fig. 3B not found. Found: {found}"

    def test_figure_order_with_parenthetical_context(self):
        """Test that figure order validation works correctly with figures in complex parentheticals."""
        markdown = """
        The results were specific (Fig. 2C, Fig. S2), and we confirmed this.
        Earlier work showed (AUC >98%; Fig. 4C) that the method was effective.
        Figure 4 panel D referenced (Fig. 4D) after some other text.
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Validate figure order - should NOT report S2 as missing
        violations = dc.validate_figure_order(refs)

        # Should not have missing figure violations for S2
        missing_s2 = [v for v in violations
                     if v['type'] == 'missing_figure' and v['figure'] == 'S2']
        assert len(missing_s2) == 0, f"Incorrectly reported S2 as missing. Violations: {violations}"

    def test_panel_order_with_parenthetical_context(self):
        """Test that panel order validation works correctly with panels in complex parentheticals."""
        markdown = """
        Initial analysis (AUC >98%; Fig. 4A) showed promising results.
        Further work (precision >95%; Fig. 4B) confirmed this.
        The final results (sensitivity >90%; Fig. 4C) were conclusive.
        Additional data (specificity >92%; Fig. 4D) supported the findings.
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Validate panel order - should NOT report missing panels
        panel_violations = dc.validate_panel_order(refs)

        # Should not have any violations for Figure 4
        fig4_violations = [v for v in panel_violations if v['figure'] == '4']
        assert len(fig4_violations) == 0, f"Incorrectly reported panel violations for Fig 4: {fig4_violations}"

    def test_multiple_figures_in_same_parentheses(self):
        """Test extraction when multiple figures appear in the same set of parentheses."""
        markdown = """
        Results shown (Fig. 1A, Fig. 1B, Fig. 2) are significant.
        Both methods work (see Fig. 3 and Fig. 4).
        Compare results (Fig. 5A vs Fig. 5B).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Extract figure numbers
        found_figs = [ref[1] for ref in refs]

        # Should find all figures
        assert '1' in found_figs
        assert '2' in found_figs
        assert '3' in found_figs
        assert '4' in found_figs
        assert '5' in found_figs

        # Check panels for Fig 1
        fig1_refs = [(ref[1], ref[2]) for ref in refs if ref[1] == '1']
        assert ('1', 'A') in fig1_refs
        assert ('1', 'B') in fig1_refs

    def test_figure_with_text_before_it_in_parentheses(self):
        """Test extraction when figure reference is not at start of parentheses."""
        markdown = """
        The AUC was high (AUC >98%; Fig. 4C) as expected.
        The specificity was good (specificity >95%, Fig. 5A) in tests.
        Results were significant (p<0.05; see Fig. 6B).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Extract figure numbers
        found = [(ref[1], ref[2]) for ref in refs]

        # Should find all figures even when they're not at the start of parentheses
        assert ('4', 'C') in found, f"Fig. 4C not found. Found: {found}"
        assert ('5', 'A') in found, f"Fig. 5A not found. Found: {found}"
        assert ('6', 'B') in found, f"Fig. 6B not found. Found: {found}"

    def test_multi_panel_same_figure_in_parentheses(self):
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

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Find all Fig 3 references
        fig3_refs = [(ref[2], ref[3]) for ref in refs if ref[1] == '3']  # (panel, line_num)

        # Panel A should first appear on line 4 (in "Fig. 3A, 3B")
        panel_a_lines = [line for panel, line in fig3_refs if panel == 'A']
        assert len(panel_a_lines) >= 1, "Panel A should be found"
        first_a_line = min(panel_a_lines)

        # Panel B should ALSO first appear on line 4 (in "Fig. 3A, 3B"), NOT later
        panel_b_lines = [line for panel, line in fig3_refs if panel == 'B']
        assert len(panel_b_lines) >= 1, "Panel B should be found"
        first_b_line = min(panel_b_lines)

        # Panel C should first appear on line 4 or 5 (in "Fig. 3C")
        panel_c_lines = [line for panel, line in fig3_refs if panel == 'C']
        assert len(panel_c_lines) >= 1, "Panel C should be found"
        first_c_line = min(panel_c_lines)

        # Critical assertion: B should be recorded at the same line as A (from "Fig. 3A, 3B")
        assert first_a_line == first_b_line, \
            f"Panel A and B should both be first recorded on the same line (from 'Fig. 3A, 3B'), but A was on line {first_a_line} and B on {first_b_line}"

        # Now test panel order validation - should have NO violations
        panel_violations = dc.validate_panel_order(refs)

        # Should not have panel order violations for Figure 3
        fig3_order_violations = [v for v in panel_violations
                                if v['figure'] == '3' and v['type'] == 'panel_out_of_order']
        assert len(fig3_order_violations) == 0, \
            f"Should have no panel order violations for Fig 3, but found: {fig3_order_violations}"

        # Should not have missing panel violations
        fig3_missing_violations = [v for v in panel_violations
                                  if v['figure'] == '3' and v['type'] in ['missing_panel_A', 'missing_panel']]
        assert len(fig3_missing_violations) == 0, \
            f"Should have no missing panel violations for Fig 3, but found: {fig3_missing_violations}"

    def test_multiple_panels_same_line_correct_order(self):
        """
        Test that multiple panel references on the same line in correct order
        do not trigger false positive panel order violations.

        Regression test for bug where (Figure 7A)...(Figure 7B)...(Figure 7C)...(Figure 7D)
        all on the same line were incorrectly flagged as out of order because the
        sort by line number didn't preserve text position order.
        """
        # This exact text was incorrectly flagging "Figure 7 panel B appears before panel D"
        markdown = """(Figure 7A). To make it simpler to interpret results of the comparison function, we developed the Seqcol Comparison Interpretation Module (SCIM), which allows a user to paste the output of a comparison endpoint and get a human-friendly interpretation of the result (Figure 7B; https://refget.databio.org/scim). This module interprets the numbers of the comparison into a simpler, understandable observation about how related two sequence collections are. To extend this reference discovery, or identifying existing collections that are similar in some way to a user-provided query, we developed the Seqcol Comparison Overview Module (SCOM), which goes beyond the 1-to-1 query provided by the comparison API to a 1-vs-many comparison. Users with a query collection can send this to the server, which iteratively compares it to each of the human or mouse reference genomes assembled for the analysis in this paper, and aggregates the results (Figure 7C;  https://refget.databio.org/scom). The resulting summary figure describes similarity scores for the 4 key attributes, highlighting existing references that may be usable for the analysis, encouraging reuse (Figure 7D)."""

        dc = DocumentChecker()
        refs = dc.extract_figure_references(markdown)

        # Should find all 4 panels
        fig7_refs = [(ref[2], ref[3]) for ref in refs if ref[1] == '7']
        panels_found = [panel for panel, line in fig7_refs]
        assert 'A' in panels_found, "Should find panel A"
        assert 'B' in panels_found, "Should find panel B"
        assert 'C' in panels_found, "Should find panel C"
        assert 'D' in panels_found, "Should find panel D"

        # Validate panel order - should have NO violations since A, B, C, D is correct order
        panel_violations = dc.validate_panel_order(refs)

        # Should not have panel order violations for Figure 7
        fig7_order_violations = [v for v in panel_violations
                                if v['figure'] == '7' and v['type'] == 'panel_out_of_order']
        assert len(fig7_order_violations) == 0, \
            f"Should have no panel order violations for Fig 7 (panels are in A,B,C,D order), but found: {fig7_order_violations}"

        # Should not have missing panel violations
        fig7_missing_violations = [v for v in panel_violations
                                  if v['figure'] == '7' and v['type'] in ['missing_panel_A', 'missing_panel']]
        assert len(fig7_missing_violations) == 0, \
            f"Should have no missing panel violations for Fig 7, but found: {fig7_missing_violations}"


class TestNumericFigureValidation:
    """Tests for numeric figure validation."""

    def test_numeric_figures_in_order(self):
        """Test that correctly ordered numeric figures pass validation."""
        content = """
        Main text:
        See (Fig. 1) and (Fig. 2) and (Fig. 3).

        ![Figure 1](fig1.svg)
        ![Figure 2](fig2.svg)
        ![Figure 3](fig3.svg)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        assert len(violations) == 0

    def test_numeric_figures_out_of_order_detected(self):
        """Test that out-of-order numeric figures are detected."""
        content = """
        Main text:
        See (Fig. 3) and then (Fig. 1).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        assert len(violations) > 0
        assert any(v['type'] == 'out_of_order' for v in violations)

    def test_numeric_supplemental_figures_in_order(self):
        """Test that correctly ordered supplemental numeric figures pass."""
        content = """
        Main text:
        See (Fig. S1) and (Fig. S2) and (Fig. S3).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        assert len(violations) == 0

    def test_numeric_supplemental_figures_out_of_order_detected(self):
        """Test that out-of-order supplemental numeric figures are detected."""
        content = """
        Main text:
        See (Fig. S3) and then (Fig. S1).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        assert len(violations) > 0
        assert any(v['type'] == 'out_of_order' for v in violations)

    def test_numeric_gap_detection(self):
        """Test that gaps in numeric figure sequence are detected."""
        content = """
        Main text:
        See (Fig. 1) and (Fig. 5).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        assert any(v['type'] == 'missing_figure' for v in violations)
        assert any('2' in str(v) or '3' in str(v) or '4' in str(v) for v in violations)

    def test_numeric_supplemental_gap_detection(self):
        """Test that gaps in supplemental numeric sequence are detected."""
        content = """
        Main text:
        See (Fig. S1) and (Fig. S4) and (Fig. S10).
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs)

        # Should detect missing S2, S3, S5, S6, S7, S8, S9
        assert any(v['type'] == 'missing_figure' for v in violations)
        missing_violations = [v for v in violations if v['type'] == 'missing_figure']
        assert len(missing_violations) >= 7  # At least 7 missing figures


class TestLabelFigureValidation:
    """Tests for LaTeX label-based figure validation."""

    def test_extract_figure_labels_main_figures(self):
        """Test extraction of main figure label definitions from captions."""
        content = r"""
        ![**\label{overview} Figure 1.** Overview diagram](fig/overview.svg)
        ![**\label{methods} Figure 2.** Methods schematic](fig/methods.svg)
        """

        dc = DocumentChecker()
        labels = dc.extract_figure_labels(content)

        assert 'overview' in labels
        assert 'methods' in labels
        assert labels['overview'][1] == 'main'
        assert labels['methods'][1] == 'main'

    def test_extract_figure_labels_supplemental_figures(self):
        """Test extraction of supplemental figure label definitions."""
        content = r"""
        ![**\label{supp-data} Supplemental Figure 1.** Extra data](fig/supp1.svg)
        ![**\label{supp-methods} Supplemental Figure 2.** Methods details](fig/supp2.svg)
        """

        dc = DocumentChecker()
        labels = dc.extract_figure_labels(content)

        assert 'supp-data' in labels
        assert 'supp-methods' in labels
        assert labels['supp-data'][1] == 'supplemental'
        assert labels['supp-methods'][1] == 'supplemental'

    def test_label_figures_in_correct_order(self):
        """Test that correctly ordered label references pass validation."""
        content = r"""
        Main text:
        See Fig. \ref{suppfig1} and Fig. \ref{suppfig2}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs, content)

        # No violations for correct order
        label_violations = [v for v in violations if v['type'] in ['label_out_of_order', 'missing_supplemental_label']]
        assert len(label_violations) == 0

    def test_label_figures_out_of_order_detected(self):
        """Test that out-of-order label references are detected."""
        content = r"""
        Main text:
        See Fig. \ref{suppfig2} for details.
        Also see Fig. \ref{suppfig1}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs, content)

        # Should detect that suppfig2 is referenced before suppfig1
        assert any(v['type'] == 'label_out_of_order' for v in violations)
        out_of_order = [v for v in violations if v['type'] == 'label_out_of_order']
        assert len(out_of_order) > 0
        assert any('suppfig1' in v['figure'] for v in out_of_order)

    def test_label_gap_detection(self):
        """Test that gaps in supplemental label sequence are detected."""
        content = r"""
        Main text:
        See Fig. \ref{suppfig1} and Fig. \ref{suppfig3}.

        # Supplement
        ![**\label{suppfig1} Supplemental Figure \ref{suppfig1}.**](fig1.svg)
        ![**\label{suppfig2} Supplemental Figure \ref{suppfig2}.**](fig2.svg)
        ![**\label{suppfig3} Supplemental Figure \ref{suppfig3}.**](fig3.svg)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs, content)

        # Should detect that suppfig2 is never referenced
        assert any(v['type'] == 'missing_supplemental_label' for v in violations)
        missing = [v for v in violations if v['type'] == 'missing_supplemental_label']
        assert any('suppfig2' in v['figure'] for v in missing)

    def test_mixed_numeric_and_label_references(self):
        """Test document with both numeric and label-based references."""
        content = r"""
        Main text:
        See (Fig. 1) and Fig. \ref{overview}.
        Also (Fig. S1) and Fig. \ref{supp-data}.

        ![Figure 1](fig1.svg)
        ![**\label{overview} Figure 2.**](fig2.svg)

        # Supplement
        ![**\label{supp-data} Supplemental Figure \ref{supp-data}.**](supp1.svg)
        """

        dc = DocumentChecker()
        refs = dc.extract_figure_references(content)
        violations = dc.validate_figure_order(refs, content)

        # Should handle both types of references without crashing
        assert isinstance(violations, list)