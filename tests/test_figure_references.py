"""
Tests for figure reference analysis functionality.
"""

import pytest
from markmeld.figure_converter import FigureConverter


class TestFigureReferences:
    """Test suite for figure reference extraction and validation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.fc = FigureConverter(None)  # No cache manager needed for tests
    
    def test_extract_parenthetic_references(self):
        """Test extraction of parenthetic figure references."""
        markdown = """
        Some text with a figure reference (Fig. 1).
        Another reference (Figure 2A).
        Multiple panels (Fig. 3B-D).
        Supplemental figure (Figure S1).
        """
        
        refs = self.fc.extract_figure_references(markdown)
        
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
        
        refs = self.fc.extract_figure_references(markdown)
        
        assert len(refs) == 2
        assert refs[0][1] == '4'
        assert refs[1][1] == '5'
    
    def test_extract_latex_references(self):
        """Test extraction of LaTeX \\ref{} style references."""
        markdown = """
        Results are shown in Figure \\ref{fig:methods}.
        (Fig. \\ref{fig:results}A)
        """
        
        refs = self.fc.extract_figure_references(markdown)
        
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
        
        refs = self.fc.extract_figure_references(markdown)
        
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
            result = self.fc.parse_figure_reference(ref_text)
            assert result == expected, f"Failed for {ref_text}"
    
    def test_validate_correct_order(self):
        """Test validation when figures are in correct order."""
        markdown = """
        First reference (Fig. 1).
        Second reference (Fig. 2).
        Third reference (Fig. 3).
        """
        
        refs = self.fc.extract_figure_references(markdown)
        violations = self.fc.validate_figure_order(refs)
        
        assert len(violations) == 0
    
    def test_validate_out_of_order(self):
        """Test validation when figures are out of order."""
        markdown = """
        First reference (Fig. 2).
        Second reference (Fig. 1).
        Third reference (Fig. 3).
        """
        
        refs = self.fc.extract_figure_references(markdown)
        violations = self.fc.validate_figure_order(refs)
        
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
        
        refs = self.fc.extract_figure_references(markdown)
        violations = self.fc.validate_figure_order(refs)
        
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
        
        refs = self.fc.extract_figure_references(markdown)
        warnings = self.fc.detect_figure_warnings(refs)
        
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
        
        refs = self.fc.extract_figure_references(markdown)
        warnings = self.fc.detect_figure_warnings(refs)
        
        # All these are acceptable contexts
        assert len(warnings) == 0
    
    def test_generate_report_with_violations(self):
        """Test report generation with order violations."""
        markdown = """
        First (Fig. 2).
        Second (Fig. 1).
        Third Figure 3 shows the data.
        """
        
        report = self.fc.generate_figure_analysis_report(markdown)
        
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
        
        report = self.fc.generate_figure_analysis_report(markdown)
        
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "All figure references appear to be in order!" in report
        assert "VIOLATIONS" not in report
        assert "WARNINGS" not in report
    
    def test_empty_markdown(self):
        """Test handling of empty markdown content."""
        report = self.fc.generate_figure_analysis_report("")
        assert report == ""
    
    def test_no_references(self):
        """Test handling of markdown with no figure references."""
        markdown = "This is text without any figure references."
        report = self.fc.generate_figure_analysis_report(markdown)
        assert report == ""
    
    def test_complex_multi_panel_references(self):
        """Test extraction of complex multi-panel references."""
        markdown = """
        Results shown in (Fig. 3B, 3C).
        Also see (Figure 4A-C).
        """

        refs = self.fc.extract_figure_references(markdown)

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

        refs = self.fc.extract_figure_references(markdown)

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

        refs = self.fc.extract_figure_references(markdown)

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

        refs = self.fc.extract_figure_references(markdown)
        panel_violations = self.fc.validate_panel_order(refs)

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

        refs = self.fc.extract_figure_references(markdown)
        panel_violations = self.fc.validate_panel_order(refs)

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

        refs = self.fc.extract_figure_references(markdown)

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
        
        refs = self.fc.extract_figure_references(markdown)
        
        assert refs[0][3] == 2  # Line number for Fig. 1
        assert refs[1][3] == 4  # Line number for Fig. 2
    
    def test_context_extraction(self):
        """Test that context is properly extracted around references."""
        markdown = "This is some text before (Fig. 1) and some text after."
        
        refs = self.fc.extract_figure_references(markdown)
        
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

        report = self.fc.generate_figure_analysis_report(markdown)

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

        refs = self.fc.extract_figure_references(markdown)
        panel_violations = self.fc.validate_panel_order(refs)

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

        fc = FigureConverter(None)
        report = fc.generate_figure_analysis_report(markdown)

        # Check report contains expected elements
        assert "FIGURE REFERENCE ANALYSIS" in report
        assert "Total figure references found:" in report

        # Extract references to verify
        refs = fc.extract_figure_references(markdown)
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
        fc = FigureConverter(None)
        refs = fc.extract_figure_references(markdown)

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
        panel_violations = fc.validate_panel_order(refs)

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
        report = fc.generate_figure_analysis_report(markdown)
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

        fc = FigureConverter(None)
        refs = fc.extract_figure_references(markdown)

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

        fc = FigureConverter(None)
        refs = fc.extract_figure_references(markdown)

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

        fc = FigureConverter(None)
        refs = fc.extract_figure_references(markdown)
        panel_violations = fc.validate_panel_order(refs)

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