import pytest
from markmeld.figure_converter import FigureConverter

class TestNumericFigureValidation:
    """Tests for existing numeric figure validation - should all pass."""

    def test_numeric_figures_in_order(self):
        """Test that correctly ordered numeric figures pass validation."""
        content = """
        Main text:
        See (Fig. 1) and (Fig. 2) and (Fig. 3).

        ![Figure 1](fig1.svg)
        ![Figure 2](fig2.svg)
        ![Figure 3](fig3.svg)
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        assert len(violations) == 0

    def test_numeric_figures_out_of_order_detected(self):
        """Test that out-of-order numeric figures are detected."""
        content = """
        Main text:
        See (Fig. 3) and then (Fig. 1).
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        assert len(violations) > 0
        assert any(v['type'] == 'out_of_order' for v in violations)

    def test_numeric_supplemental_figures_in_order(self):
        """Test that correctly ordered supplemental numeric figures pass."""
        content = """
        Main text:
        See (Fig. S1) and (Fig. S2) and (Fig. S3).
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        assert len(violations) == 0

    def test_numeric_supplemental_figures_out_of_order_detected(self):
        """Test that out-of-order supplemental numeric figures are detected."""
        content = """
        Main text:
        See (Fig. S3) and then (Fig. S1).
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        assert len(violations) > 0
        assert any(v['type'] == 'out_of_order' for v in violations)

    def test_numeric_gap_detection(self):
        """Test that gaps in numeric figure sequence are detected."""
        content = """
        Main text:
        See (Fig. 1) and (Fig. 5).
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        assert any(v['type'] == 'missing_figure' for v in violations)
        assert any('2' in str(v) or '3' in str(v) or '4' in str(v) for v in violations)

    def test_numeric_supplemental_gap_detection(self):
        """Test that gaps in supplemental numeric sequence are detected."""
        content = """
        Main text:
        See (Fig. S1) and (Fig. S4) and (Fig. S10).
        """

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs)

        # Should detect missing S2, S3, S5, S6, S7, S8, S9
        assert any(v['type'] == 'missing_figure' for v in violations)
        missing_violations = [v for v in violations if v['type'] == 'missing_figure']
        assert len(missing_violations) >= 7  # At least 7 missing figures
