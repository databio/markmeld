"""Tests for local figure conversion (markmeld.figure_conversion)."""

import os
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from markmeld.figure_conversion import (
    extract_figure_paths,
    parse_figure_label,
    parse_figure_parameters,
    update_figure_paths,
    convert_svg,
    process_local_figures,
    _compute_file_md5,
    _needs_conversion,
    _save_digest,
)


class TestExtractFigurePaths:
    def test_basic_svg(self):
        md = "![diagram](fig/overview.svg)"
        result = extract_figure_paths(md)
        # Plain inline image: legend is the alt-text, label is None.
        assert result == [("fig/overview.svg", {"legend": "diagram", "label": None})]

    def test_multiple_figures(self):
        md = "![a](fig/a.svg)\n![b](fig/b.png)\n![c](fig/c.svg)"
        result = extract_figure_paths(md)
        assert len(result) == 3
        assert result[0][0] == "fig/a.svg"
        assert result[1][0] == "fig/b.png"
        assert result[2][0] == "fig/c.svg"

    def test_with_parameters(self):
        md = "![diagram](fig/overview.svg){width=174mm}"
        result = extract_figure_paths(md)
        assert result[0][0] == "fig/overview.svg"
        assert result[0][1] == {"width": "174mm", "legend": "diagram", "label": None}

    def test_filters_urls(self):
        md = "![ext](https://example.com/img.svg)\n![local](fig/local.svg)"
        result = extract_figure_paths(md)
        assert len(result) == 1
        assert result[0][0] == "fig/local.svg"

    def test_deduplicates(self):
        md = "![a](fig/x.svg)\n![b](fig/x.svg)"
        result = extract_figure_paths(md)
        assert len(result) == 1

    def test_reference_style(self):
        md = "[fig1]: fig/diagram.svg"
        result = extract_figure_paths(md)
        # Reference-style images have no alt-text: legend and label are None.
        assert result == [("fig/diagram.svg", {"legend": None, "label": None})]

    def test_legend_and_label(self):
        md = "![\\label{tss} Fig: **TSS enrichment**. A) ... B) ...](fig/tss.pdf){width=174mm}"
        result = extract_figure_paths(md)
        assert result[0][0] == "fig/tss.pdf"
        params = result[0][1]
        assert params["legend"] == "\\label{tss} Fig: **TSS enrichment**. A) ... B) ..."
        assert params["label"] == "tss"
        assert params["width"] == "174mm"

    def test_plain_image_has_no_label(self):
        md = "![just a caption](fig/plain.svg)"
        params = extract_figure_paths(md)[0][1]
        assert params["legend"] == "just a caption"
        assert params["label"] is None

    def test_empty_alt_text(self):
        md = "![](fig/blank.svg)"
        params = extract_figure_paths(md)[0][1]
        assert params["legend"] is None
        assert params["label"] is None


class TestParseFigureLabel:
    def test_extracts_label(self):
        assert parse_figure_label("\\label{tss} Fig: caption") == "tss"

    def test_no_label(self):
        assert parse_figure_label("Fig: caption with no label") is None

    def test_empty(self):
        assert parse_figure_label("") is None
        assert parse_figure_label(None) is None


class TestParseFigureParameters:
    def test_empty(self):
        assert parse_figure_parameters("") == {}

    def test_simple(self):
        assert parse_figure_parameters("{width=174mm}") == {"width": "174mm"}

    def test_quoted(self):
        assert parse_figure_parameters('{col-widths="20,5,8"}') == {"col-widths": "20,5,8"}

    def test_multiple(self):
        result = parse_figure_parameters("{width=174mm font-size=6pt}")
        assert result == {"width": "174mm", "font-size": "6pt"}


class TestUpdateFigurePaths:
    def test_basic_replacement(self):
        md = "![diagram](fig/overview.svg)"
        result = update_figure_paths(md, {"fig/overview.svg": "/cache/fig/overview.pdf"})
        assert "](/cache/fig/overview.pdf)" in result

    def test_preserves_parameters(self):
        md = "![diagram](fig/overview.svg){width=174mm}"
        result = update_figure_paths(md, {"fig/overview.svg": "/cache/fig/overview.pdf"})
        assert "](/cache/fig/overview.pdf){width=174mm}" in result

    def test_no_mapping_leaves_unchanged(self):
        md = "![diagram](fig/overview.svg)"
        result = update_figure_paths(md, {"fig/other.svg": "/cache/fig/other.pdf"})
        assert result == md

    def test_reference_style(self):
        md = "[fig1]: fig/diagram.svg"
        result = update_figure_paths(md, {"fig/diagram.svg": "/cache/fig/diagram.pdf"})
        assert "[fig1]: /cache/fig/diagram.pdf" in result


class TestConvertSvg:
    def test_missing_inkscape(self, tmp_path):
        svg_file = tmp_path / "test.svg"
        svg_file.write_text("<svg></svg>")
        output = tmp_path / "test.pdf"
        with patch("markmeld.figure_conversion.INKSCAPE_COMMAND", "/nonexistent/inkscape"):
            result = convert_svg(str(svg_file), output)
        assert result is False

    def test_successful_conversion(self, tmp_path):
        svg_file = tmp_path / "test.svg"
        svg_file.write_text("<svg></svg>")
        output = tmp_path / "out" / "test.pdf"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("markmeld.figure_conversion.subprocess.run", return_value=mock_result):
            # Simulate inkscape creating the file
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("fake pdf")
            result = convert_svg(str(svg_file), output)

        assert result is True


class TestProcessLocalFigures:
    def test_no_svgs_passthrough(self):
        md = "![photo](fig/photo.png)"
        result = process_local_figures(md, "/some/path", Path("/tmp/cache"))
        assert result == md

    def test_missing_svg_warns(self, tmp_path):
        md = "![diagram](fig/missing.svg)"
        result = process_local_figures(md, str(tmp_path), tmp_path)
        # Should return unchanged since file doesn't exist
        assert result == md

    def test_rewrites_svg_to_pdf(self, tmp_path):
        # Create a fake SVG file
        fig_dir = tmp_path / "fig"
        fig_dir.mkdir()
        svg_file = fig_dir / "diagram.svg"
        svg_file.write_text("<svg></svg>")

        md = "![diagram](fig/diagram.svg)"

        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(cmd, **kwargs):
            # Simulate inkscape creating the PDF
            for i, arg in enumerate(cmd):
                if arg.startswith("--export-filename="):
                    pdf_path = Path(arg.split("=", 1)[1])
                    pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    pdf_path.write_text("fake pdf")
            return mock_result

        with patch("markmeld.figure_conversion.subprocess.run", side_effect=fake_run):
            result = process_local_figures(md, str(tmp_path), tmp_path)

        assert "fig/diagram.svg" not in result
        assert "diagram.pdf" in result

    def test_caching_skips_reconversion(self, tmp_path):
        # Create a fake SVG file
        fig_dir = tmp_path / "fig"
        fig_dir.mkdir()
        svg_file = fig_dir / "diagram.svg"
        svg_file.write_text("<svg></svg>")

        # Pre-populate cache
        converted_dir = tmp_path / ".cache" / "local" / "converted"
        pdf_path = converted_dir / "fig" / "diagram.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("cached pdf")

        digest_dir = tmp_path / ".cache" / "local" / "digest"
        digest_path = digest_dir / "fig" / "diagram.svg.md5"
        current_md5 = _compute_file_md5(str(svg_file))
        _save_digest(digest_path, current_md5)

        md = "![diagram](fig/diagram.svg)"

        with patch("markmeld.figure_conversion.convert_svg") as mock_convert:
            result = process_local_figures(md, str(tmp_path), tmp_path)

        # Should NOT have called convert_svg since cache is valid
        mock_convert.assert_not_called()
        assert "diagram.pdf" in result

    def test_absolute_paths(self, tmp_path):
        svg_file = tmp_path / "diagram.svg"
        svg_file.write_text("<svg></svg>")

        abs_path = str(svg_file)
        md = f"![diagram]({abs_path})"

        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(cmd, **kwargs):
            for arg in cmd:
                if arg.startswith("--export-filename="):
                    pdf_path = Path(arg.split("=", 1)[1])
                    pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    pdf_path.write_text("fake pdf")
            return mock_result

        with patch("markmeld.figure_conversion.subprocess.run", side_effect=fake_run):
            result = process_local_figures(md, str(tmp_path), tmp_path)

        assert abs_path not in result
        assert ".pdf" in result
