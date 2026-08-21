"""Local figure conversion for markmeld.

Handles SVG→PDF and CSV→PDF conversion for local markdown files without any
Google Drive dependencies. Uses inkscape for SVG conversion and weasyprint for
CSV table rendering, with simple file-based MD5 caching.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

INKSCAPE_COMMAND = "inkscape"


def extract_figure_paths(markdown_content: str) -> list[tuple[str, dict[str, Any]]]:
    """Extract all figure paths and their parameters from markdown content.

    Returns:
        List of tuples (path, parameters_dict)
    """
    # Pattern to find markdown images with optional parameters
    # Matches: ![alt](path){.param=value .param2="value"}
    # Alt text may contain nested [...] spans (e.g., from tracked changes)
    # Group 1 captures the alt-text (legend), group 2 the path, group 3 params.
    inline_pattern = r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+)\)(\{[^}]*\})?"

    # Find reference-style images: [ref]: path
    ref_pattern = r"^\[[^\]]+\]:\s*(.+)$"

    figures = []

    for match in re.finditer(inline_pattern, markdown_content):
        alt = match.group(1) or ""
        path = match.group(2)
        params_str = match.group(3) if match.group(3) else ""
        params = parse_figure_parameters(params_str)
        params["legend"] = alt.strip() if alt.strip() else None
        params["label"] = parse_figure_label(alt)
        figures.append((path, params))

    for match in re.finditer(ref_pattern, markdown_content, re.MULTILINE):
        path = match.group(1)
        figures.append((path, {"legend": None, "label": None}))

    # Filter out URLs and data URIs, keep only local paths
    local_figures = [
        (path, params)
        for path, params in figures
        if not path.startswith(("http://", "https://", "data:"))
    ]

    # Remove duplicates while preserving order
    seen = set()
    unique_figures = []
    for path, params in local_figures:
        if path not in seen:
            seen.add(path)
            unique_figures.append((path, params))

    return unique_figures


def parse_figure_label(alt_text: str) -> str | None:
    """Extract the figure id from a \\label{...} in the image alt-text."""
    if not alt_text:
        return None
    m = re.search(r"\\label\{([^}]+)\}", alt_text)
    return m.group(1) if m else None


def parse_figure_parameters(param_string: str) -> dict:
    """Parse figure parameters from markdown syntax like {width=174mm}."""
    params = {}
    if not param_string:
        return params

    param_string = param_string.strip()
    if param_string.startswith("{") and param_string.endswith("}"):
        param_string = param_string[1:-1].strip()

    pattern = r'([a-zA-Z0-9_-]+)=(?:"([^"]+)"|([^\s}]+))'
    for match in re.finditer(pattern, param_string):
        key = match.group(1)
        value = match.group(2) if match.group(2) else match.group(3)
        params[key] = value

    return params


def update_figure_paths(markdown_content: str, path_mapping: dict[str, str]) -> str:
    """Replace figure paths in markdown with converted paths, preserving parameters.

    Args:
        markdown_content: The markdown content to update
        path_mapping: Dictionary mapping original paths to new paths

    Returns:
        Updated markdown content with paths replaced
    """
    updated = markdown_content

    # Handle paths with parameters first - preserve the parameters
    param_pattern = r"(!\[[^\]]*\]\()([^)]+)(\))(\{[^}]*\})"

    def replace_with_mapping(match):
        prefix = match.group(1)
        path = match.group(2)
        suffix = match.group(3)
        params = match.group(4)
        if path in path_mapping:
            return f"{prefix}{path_mapping[path]}{suffix}{params}"
        return f"{prefix}{path}{suffix}{params}"

    updated = re.sub(param_pattern, replace_with_mapping, updated)

    # Then handle regular path replacements for paths without parameters
    for old_path, new_path in path_mapping.items():
        updated = updated.replace(f"]({old_path})", f"]({new_path})")
        updated = updated.replace(f"]: {old_path}", f"]: {new_path}")
        updated = updated.replace(f"]:{old_path}", f"]:{new_path}")

    return updated


def convert_svg(svg_path: str, output_path: Path) -> bool:
    """Convert SVG to PDF using inkscape.

    Args:
        svg_path: Path to SVG file.
        output_path: Path for output PDF.

    Returns:
        True if successful, False otherwise.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            INKSCAPE_COMMAND,
            "--batch-process",
            "--export-type=pdf",
            f"--export-filename={output_path}",
            svg_path,
        ]

        _LOGGER.info(f"  Converting SVG to PDF: {svg_path}")

        env = os.environ.copy()
        env["DISPLAY"] = ""

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)

        if result.returncode != 0:
            _LOGGER.error(f"Inkscape conversion failed (rc={result.returncode})")
            if result.stderr:
                _LOGGER.error(f"  stderr: {result.stderr[:500]}")
            return False

        if not output_path.exists():
            _LOGGER.error(f"PDF file was not created at {output_path}")
            return False

        svg_rel = "/".join(Path(svg_path).parts[-2:])
        out_rel = "/".join(output_path.parts[-2:])
        _LOGGER.info(f"  Converted: {svg_rel} -> {out_rel}")
        return True

    except subprocess.TimeoutExpired:
        _LOGGER.error(f"Inkscape conversion timed out after 60s for {svg_path}")
        return False
    except FileNotFoundError:
        _LOGGER.error(
            f"Inkscape not found: '{INKSCAPE_COMMAND}'. "
            "Install with: sudo apt-get install inkscape (Ubuntu) or brew install inkscape (macOS)"
        )
        return False


DEFAULT_TABLE_PARAMS = {
    "fig_width_mm": 174,
    "font_size_pt": 6,
    "tr_padding_v": 1,
    "tr_padding_h": 3,
}


def convert_csv(csv_path: str, output_path: Path, params: dict[str, Any]) -> bool:
    """Convert CSV to PDF using weasyprint.

    Args:
        csv_path: Path to CSV file.
        output_path: Path for output PDF.
        params: Table formatting parameters.

    Returns:
        True if successful, False otherwise.
    """
    try:
        import pandas as pd

        output_path.parent.mkdir(parents=True, exist_ok=True)

        df = pd.read_csv(csv_path)
        table_params = prepare_table_parameters(params, df)
        df_to_pdf(df, str(output_path), **table_params)

        csv_rel = "/".join(Path(csv_path).parts[-2:])
        out_rel = "/".join(output_path.parts[-2:])
        _LOGGER.info(f"  Converted: {csv_rel} -> {out_rel}")
        return True

    except Exception as e:
        _LOGGER.error(f"Error converting CSV to PDF: {e}")
        return False


def prepare_table_parameters(params: dict[str, Any], df: Any) -> dict[str, Any]:
    """Prepare table parameters for PDF generation.

    Args:
        params: Parameters from markdown.
        df: pandas DataFrame.

    Returns:
        Dictionary of parameters for table PDF builder.
    """
    table_params = DEFAULT_TABLE_PARAMS.copy()

    if "fig_width" in params:
        width_str = str(params["fig_width"]).strip().lower()
        if width_str == "auto":
            table_params["fig_width_mm"] = "auto"
        elif width_str.endswith("mm"):
            table_params["fig_width_mm"] = float(width_str[:-2])
        else:
            try:
                table_params["fig_width_mm"] = float(width_str)
            except ValueError:
                _LOGGER.warning(f"  Invalid width value '{params['fig_width']}', using default")

    if "font-size" in params:
        size_str = str(params["font-size"])
        if size_str.endswith("pt"):
            table_params["font_size_pt"] = float(size_str[:-2])
        else:
            table_params["font_size_pt"] = float(size_str)

    if "col-names" in params:
        table_params["colnames"] = params["col-names"].split(",")
    else:
        table_params["colnames"] = list(df.columns)

    if "col-widths" in params:
        widths = params["col-widths"].split(",")
        table_params["col_widths"] = [float(w.strip()) for w in widths]
    else:
        n_cols = len(df.columns)
        table_params["col_widths"] = [100.0 / n_cols] * n_cols

    if "col-align" in params:
        table_params["col_alignments"] = params["col-align"].split(",")
    else:
        table_params["col_alignments"] = ["left"] * len(df.columns)

    if "padding-v" in params:
        table_params["tr_padding_v"] = float(params["padding-v"])
    if "padding-h" in params:
        table_params["tr_padding_h"] = float(params["padding-h"])

    if "fig_height" in params:
        height_str = str(params["fig_height"]).strip().lower()
        if height_str == "auto":
            table_params["fig_height_mm"] = "auto"
        elif height_str.endswith("mm"):
            table_params["fig_height_mm"] = float(height_str[:-2])
        else:
            try:
                table_params["fig_height_mm"] = float(height_str)
            except ValueError:
                table_params["fig_height_mm"] = "auto"
    else:
        font_size = table_params.get("font_size_pt", 6)
        page_width = table_params.get("fig_width_mm", 174)
        if page_width == "auto":
            page_width = 174
        table_params["fig_height_mm"] = find_optimal_height(
            df,
            table_params["col_widths"],
            table_params["col_alignments"],
            page_width,
            font_size,
            table_params.get("tr_padding_v", 1),
            table_params.get("tr_padding_h", 3),
        )
        _LOGGER.info(
            f"  Auto-calculated height: {table_params['fig_height_mm']:.2f}mm "
            f"for {len(df)} data rows + header (font: {font_size}pt)"
        )

    return table_params


def build_table_css(
    col_widths: list[float],
    col_alignments: list[str],
    page_width_mm: float,
    page_height_mm: float,
    font_size_pt: float,
    tr_padding_v: float,
    tr_padding_h: float,
) -> str:
    """Build CSS for table rendering."""
    col_css = ""
    for i, (w, align) in enumerate(zip(col_widths, col_alignments)):
        col_css += f"th:nth-child({i + 1}), td:nth-child({i + 1}) {{ width: {w}%; text-align: {align}; box-sizing: border-box; }}\n"

    def fmt(val):
        return "auto" if val == "auto" else f"{val}mm"

    width_css, height_css = fmt(page_width_mm), fmt(page_height_mm)
    page_size = (
        "auto" if width_css == "auto" and height_css == "auto" else f"{width_css} {height_css}"
    )

    return f"""<style>
      @page {{ size: {page_size}; margin: 0; }}
      body {{ font-family: Helvetica, Arial, sans-serif; font-size: {font_size_pt}pt; margin: 2mm; }}
      table {{ border-collapse: collapse; width: 100%; table-layout: fixed; padding: 0; }}
      th, td {{ border: 0; padding: {tr_padding_v}px {tr_padding_h}px; word-wrap: break-word; }}
      th {{ background-color: #ccc; color: black; font-weight: bold; }}
      tr:nth-child(even) {{ background-color: #f2f2f2; }}
      {col_css}
    </style>"""


def df_to_pdf(
    df: Any,
    output_file: str,
    colnames: list[str],
    col_widths: list[float],
    col_alignments: list[str],
    fig_width_mm: float,
    fig_height_mm: float | None = None,
    font_size_pt: float = 6,
    tr_padding_v: float = 1,
    tr_padding_h: float = 3,
) -> None:
    """Convert DataFrame to PDF using weasyprint."""
    from weasyprint import HTML

    if len(df.columns) != len(colnames):
        raise ValueError("Number of column names does not match DataFrame columns")
    if len(col_widths) != len(colnames):
        raise ValueError("Number of column widths does not match number of columns")
    if len(col_alignments) != len(colnames):
        raise ValueError("Number of column alignments does not match number of columns")

    if fig_height_mm is None:
        page_width = fig_width_mm if fig_width_mm != "auto" else 174
        fig_height_mm = find_optimal_height(
            df, col_widths, col_alignments, page_width, font_size_pt, tr_padding_v, tr_padding_h
        )

    df.columns = colnames
    css = build_table_css(
        col_widths,
        col_alignments,
        fig_width_mm,
        fig_height_mm,
        font_size_pt,
        tr_padding_v,
        tr_padding_h,
    )

    _LOGGER.info(f"  Generating PDF with dimensions: {fig_width_mm}mm x {fig_height_mm}mm")
    HTML(string=css + df.to_html(index=False, escape=True)).write_pdf(output_file)


def find_optimal_height(
    df: Any,
    col_widths: list[float],
    col_alignments: list[str],
    page_width_mm: float,
    font_size_pt: float,
    tr_padding_v: float,
    tr_padding_h: float,
) -> float:
    """Find minimum page height that fits content on one page using binary search."""
    from weasyprint import HTML

    def fits_on_one_page(height_mm: float) -> bool:
        css = build_table_css(
            col_widths,
            col_alignments,
            page_width_mm,
            height_mm,
            font_size_pt,
            tr_padding_v,
            tr_padding_h,
        )
        return len(HTML(string=css + df.to_html(index=False, escape=True)).render().pages) == 1

    low, high = 10.0, 2000.0
    if not fits_on_one_page(high):
        _LOGGER.warning("Content doesn't fit on 2000mm page")
        return high

    while high - low > 1.0:
        mid = (low + high) / 2
        if fits_on_one_page(mid):
            high = mid
        else:
            low = mid

    return high * 1.02  # Small buffer


def compute_params_digest(params: dict[str, Any]) -> str:
    """Compute MD5 digest for a parameter dictionary."""
    sorted_params = json.dumps(params, sort_keys=True)
    return hashlib.md5(sorted_params.encode()).hexdigest()


def _compute_file_md5(file_path: str) -> str:
    """Compute MD5 hash of a file's contents."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_digest(digest_path: Path) -> str | None:
    """Load a stored digest from a file."""
    if digest_path.exists():
        return digest_path.read_text().strip()
    return None


def _save_digest(digest_path: Path, digest: str) -> None:
    """Save a digest to a file."""
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(digest)


def _needs_conversion(source_path: str, output_path: Path, digest_path: Path) -> bool:
    """Check if SVG→PDF conversion is needed based on output existence and MD5 cache."""
    if not output_path.exists():
        return True
    if not os.path.exists(source_path):
        return True
    current_md5 = _compute_file_md5(source_path)
    stored_md5 = _load_digest(digest_path)
    return current_md5 != stored_md5


def _needs_csv_conversion(
    source_path: str,
    params: dict[str, Any],
    output_path: Path,
    file_digest_path: Path,
    params_digest_path: Path,
) -> bool:
    """Check if CSV→PDF conversion is needed based on file content and params."""
    if not output_path.exists():
        return True
    if not os.path.exists(source_path):
        return True
    # Check file content
    current_md5 = _compute_file_md5(source_path)
    stored_md5 = _load_digest(file_digest_path)
    if current_md5 != stored_md5:
        return True
    # Check params
    current_params_digest = compute_params_digest(params)
    stored_params_digest = _load_digest(params_digest_path)
    return current_params_digest != stored_params_digest


def process_local_figures(markdown_content: str, defpath: str, cache_dir: Path) -> str:
    """Process local figure references in markdown, converting SVGs and CSVs to PDFs.

    This is the main entry point for local figure conversion. It:
    1. Extracts figure paths from the markdown
    2. Resolves them against defpath
    3. Converts SVGs and CSVs to PDF (with caching)
    4. Rewrites markdown paths to point to the converted PDFs

    Args:
        markdown_content: Rendered markdown content.
        defpath: Project definition path (where source files live).
        cache_dir: Directory for cache/converted files.

    Returns:
        Modified markdown with SVG/CSV paths replaced by PDF paths.
    """
    figures = extract_figure_paths(markdown_content)

    # Filter to files that need conversion
    convertible = [
        (path, params)
        for path, params in figures
        if path.lower().endswith(".svg") or path.lower().endswith(".csv")
    ]

    if not convertible:
        return markdown_content

    converted_dir = cache_dir / ".cache" / "local" / "converted"
    digest_dir = cache_dir / ".cache" / "local" / "digest"

    path_mapping: dict[str, str] = {}

    for fig_path, params in convertible:
        # Resolve source path against defpath
        if os.path.isabs(fig_path):
            source_path = fig_path
        else:
            source_path = os.path.normpath(os.path.join(defpath, fig_path))

        if not os.path.exists(source_path):
            _LOGGER.warning(f"File not found: {source_path} (from {fig_path})")
            continue

        fig_lower = fig_path.lower()
        pdf_relative = re.sub(r"\.(svg|csv)$", ".pdf", fig_path, flags=re.IGNORECASE)
        output_path = converted_dir / pdf_relative
        file_digest_path = digest_dir / (fig_path + ".md5")

        if fig_lower.endswith(".svg"):
            if _needs_conversion(source_path, output_path, file_digest_path):
                success = convert_svg(source_path, output_path)
                if success:
                    _save_digest(file_digest_path, _compute_file_md5(source_path))
                else:
                    _LOGGER.error(f"Failed to convert {fig_path}, leaving path unchanged")
                    continue

        elif fig_lower.endswith(".csv"):
            params_digest_path = digest_dir / (fig_path + ".params.md5")
            if _needs_csv_conversion(
                source_path, params, output_path, file_digest_path, params_digest_path
            ):
                success = convert_csv(source_path, output_path, params)
                if success:
                    _save_digest(file_digest_path, _compute_file_md5(source_path))
                    _save_digest(params_digest_path, compute_params_digest(params))
                else:
                    _LOGGER.error(f"Failed to convert {fig_path}, leaving path unchanged")
                    continue

        path_mapping[fig_path] = str(output_path.resolve())

    if not path_mapping:
        return markdown_content

    return update_figure_paths(markdown_content, path_mapping)
