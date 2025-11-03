import pytest
import os
from markmeld.figure_converter import FigureConverter

class TestLabelFigureValidation:
    """Tests for LaTeX label-based figure validation - will fail until implemented."""

    def test_extract_figure_labels_main_figures(self):
        """Test extraction of main figure label definitions from captions."""
        content = r"""
        ![**\label{overview} Figure 1.** Overview diagram](fig/overview.svg)
        ![**\label{methods} Figure 2.** Methods schematic](fig/methods.svg)
        """

        fc = FigureConverter(None, None)
        labels = fc.extract_figure_labels(content)

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

        fc = FigureConverter(None, None)
        labels = fc.extract_figure_labels(content)

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

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs, content)

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

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs, content)

        # Should detect that suppfig2 is referenced before suppfig1
        # The violation reports suppfig1 as being out of order (appears after suppfig2 despite being defined first)
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

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs, content)

        # Should detect that suppfig2 is never referenced
        assert any(v['type'] == 'missing_supplemental_label' for v in violations)
        missing = [v for v in violations if v['type'] == 'missing_supplemental_label']
        assert any('suppfig2' in v['figure'] for v in missing)

    def test_real_world_atacformer_document(self):
        """Test with actual Atacformer manuscript - should detect ordering issues."""
        doc_path = '/home/nsheff/sandbox/webdev/sciquill/backend/data/builds/2026-atacformer/.cache/1qS4X0NZHJjzl_oNXJJMOSFu84UalalqZhUGMhwlyOhQ/docs/Atacformer manuscript.md'

        # Skip if document doesn't exist (e.g., in CI)
        if not os.path.exists(doc_path):
            pytest.skip("Atacformer manuscript not available")

        with open(doc_path) as f:
            content = f.read()

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs, content)

        # Should detect the supplemental-ictss-anecdotes ordering issue
        label_violations = [v for v in violations if v['type'] in ['label_out_of_order', 'missing_supplemental_label']]
        assert len(label_violations) > 0
        # Verify specific violation is detected
        assert any('supplemental-ictss-anecdotes' in str(v) for v in label_violations)

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

        fc = FigureConverter(None, None)
        refs = fc.extract_figure_references(content)
        violations = fc.validate_figure_order(refs, content)

        # Should handle both types of references
        # Mixed style might generate a warning but shouldn't crash
        # At minimum, should not raise exceptions
        assert isinstance(violations, list)
