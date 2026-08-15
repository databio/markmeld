"""
Tests for CSV/table to PDF height calculation.

Ensures the height formula:
1. Doesn't undershoot (content fits on 1 page)
2. Doesn't overshoot (not more than 25% taller than minimum needed)
"""

import shutil
import pytest
import pandas as pd
import tempfile
import subprocess
from pathlib import Path

try:
    import weasyprint  # noqa: F401

    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

PDFINFO_AVAILABLE = shutil.which("pdfinfo") is not None

pytestmark = pytest.mark.skipif(
    not (WEASYPRINT_AVAILABLE and PDFINFO_AVAILABLE),
    reason="weasyprint and/or pdfinfo not available",
)


def get_page_count(pdf_path: str) -> int:
    """Get number of pages in PDF."""
    result = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True)
    for line in result.stdout.split("\n"):
        if "Pages:" in line:
            return int(line.split(":")[1].strip())
    return 0


def render_table_pdf(
    df: pd.DataFrame, font_size_pt: float, height_mm: float, output_path: str
):
    """Render DataFrame to PDF with specified height."""
    from weasyprint import HTML

    css = f"""<style>
      @page {{ size: 174mm {height_mm:.2f}mm; margin: 0; }}
      body {{ font-family: Helvetica, Arial, sans-serif; font-size: {font_size_pt}pt; margin: 2mm; }}
      table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
      th, td {{ border: 0; padding: 1px 3px; }}
      th {{ background-color: #ccc; font-weight: bold; }}
      tr:nth-child(even) {{ background-color: #f2f2f2; }}
    </style>"""

    html_content = css + df.to_html(index=False, escape=True)
    HTML(string=html_content).write_pdf(output_path)


def find_minimum_height(df: pd.DataFrame, font_size_pt: float) -> float:
    """Binary search to find minimum height that fits on 1 page."""
    low, high = 10.0, 500.0

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        temp_path = f.name

    try:
        while high - low > 1.0:
            mid = (low + high) / 2
            render_table_pdf(df, font_size_pt, mid, temp_path)
            if get_page_count(temp_path) == 1:
                high = mid
            else:
                low = mid
        return high
    finally:
        Path(temp_path).unlink(missing_ok=True)


def create_test_dataframe(n_rows: int) -> pd.DataFrame:
    """Create a test DataFrame with specified number of rows."""
    return pd.DataFrame(
        {
            "Column A": [f"Row {i}" for i in range(n_rows)],
            "Column B": [i * 10 for i in range(n_rows)],
            "Column C": [f"Data {i}" for i in range(n_rows)],
        }
    )


@pytest.mark.slow
class TestTableHeightCalculation:
    """Test suite for table height calculation."""

    REPRESENTATIVE_CASES = [
        (6, 6),  # small table, small font
        (6, 18),  # small table, large font
        (60, 6),  # large table, small font
        (60, 18),  # large table, large font
    ]
    MAX_OVERSHOOT_PERCENT = 25  # Maximum allowed overshoot

    @pytest.fixture
    def figure_converter(self):
        """Create FigureConverter instance."""
        from markmeld.google_drive import FigureConverter

        return FigureConverter(cache_manager=None)

    @pytest.mark.parametrize("n_rows,font_size", REPRESENTATIVE_CASES)
    def test_no_undershoot(self, figure_converter, n_rows, font_size):
        """Test that calculated height fits content on 1 page (no undershoot)."""
        df = create_test_dataframe(n_rows)
        total_rows = n_rows + 1  # +1 for header

        # Get calculated height from our formula
        calculated_height = figure_converter._guess_pdf_height_mm(total_rows, font_size)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            output_path = f.name

        try:
            render_table_pdf(df, font_size, calculated_height, output_path)
            pages = get_page_count(output_path)

            assert pages == 1, (
                f"Content overflowed to {pages} pages. "
                f"Rows={n_rows}, font={font_size}pt, height={calculated_height:.1f}mm"
            )
        finally:
            Path(output_path).unlink(missing_ok=True)

    @pytest.mark.parametrize("n_rows,font_size", REPRESENTATIVE_CASES)
    def test_no_excessive_overshoot(self, figure_converter, n_rows, font_size):
        """Test that calculated height is not excessively larger than minimum needed."""
        df = create_test_dataframe(n_rows)
        total_rows = n_rows + 1  # +1 for header

        # Get calculated height from our formula
        calculated_height = figure_converter._guess_pdf_height_mm(total_rows, font_size)

        # Find minimum height via binary search
        min_height = find_minimum_height(df, font_size)

        overshoot_percent = ((calculated_height - min_height) / min_height) * 100

        assert overshoot_percent <= self.MAX_OVERSHOOT_PERCENT, (
            f"Height overshoot too large: {overshoot_percent:.1f}% > {self.MAX_OVERSHOOT_PERCENT}%. "
            f"Rows={n_rows}, font={font_size}pt, "
            f"calculated={calculated_height:.1f}mm, minimum={min_height:.1f}mm"
        )


@pytest.mark.slow
class TestRealisticContent:
    """Test with realistic content that causes text wrapping."""

    def create_realistic_dataframe(self, n_rows: int) -> pd.DataFrame:
        """Create DataFrame with long content similar to real CSVs."""
        return pd.DataFrame(
            {
                "sample_name": [
                    f"Sample_name_with_long_prefix_{i:03d}" for i in range(n_rows)
                ],
                "common_name": ["hg38" for _ in range(n_rows)],
                "authority": ["institution" for _ in range(n_rows)],
                "description": [
                    f"This is a longer description that will wrap to multiple lines number {i}"
                    for i in range(n_rows)
                ],
                "digest": ["ABC123DEF456GHI789JKL012MNO345PQR" for _ in range(n_rows)],
                "count": [1234 for _ in range(n_rows)],
            }
        )

    @pytest.fixture
    def figure_converter(self):
        """Create FigureConverter instance."""
        from markmeld.google_drive import FigureConverter

        return FigureConverter(cache_manager=None)

    @pytest.mark.parametrize("n_rows", [10, 60])
    def test_realistic_content_fits_single_page(self, figure_converter, n_rows):
        """Test that binary search finds height that fits realistic content on 1 page."""
        df = self.create_realistic_dataframe(n_rows)
        font_size = 6
        total_rows = n_rows + 1  # +1 for header

        # Use binary search (pass df)
        calculated_height = figure_converter._guess_pdf_height_mm(
            total_rows, font_size, df=df, page_width_mm=174
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            output_path = f.name

        try:
            render_table_pdf(df, font_size, calculated_height, output_path)
            pages = get_page_count(output_path)

            assert pages == 1, (
                f"Content overflowed to {pages} pages. "
                f"Rows={n_rows}, font={font_size}pt, height={calculated_height:.1f}mm"
            )
        finally:
            Path(output_path).unlink(missing_ok=True)

    @pytest.mark.parametrize("n_rows", [10, 60])
    def test_realistic_content_minimal_overshoot(self, figure_converter, n_rows):
        """Test that binary search doesn't overshoot excessively for realistic content."""
        df = self.create_realistic_dataframe(n_rows)
        font_size = 6
        total_rows = n_rows + 1

        # Use binary search
        calculated_height = figure_converter._guess_pdf_height_mm(
            total_rows, font_size, df=df, page_width_mm=174
        )

        # Find minimum via our own binary search
        min_height = find_minimum_height(df, font_size)

        overshoot_percent = ((calculated_height - min_height) / min_height) * 100

        # Binary search should be within 5% (it adds 2% buffer)
        assert overshoot_percent <= 5, (
            f"Overshoot too large: {overshoot_percent:.1f}% > 5%. "
            f"Rows={n_rows}, calculated={calculated_height:.1f}mm, minimum={min_height:.1f}mm"
        )
