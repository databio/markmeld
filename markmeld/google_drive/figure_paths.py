"""Figure path extraction and mapping for Google Drive documents."""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..figure_conversion import update_figure_paths  # noqa: F401 (re-exported)

_LOGGER = logging.getLogger(__name__)


def extract_csv_paths(markdown_content: str) -> List[str]:
    """Extract all CSV file paths from markdown content using {csv/...} syntax.

    Args:
        markdown_content: The markdown content to search

    Returns:
        List of unique CSV file paths found
    """
    # Pattern to match {csv/path/to/file.csv} syntax
    csv_pattern = r'\{(csv/[^}]+\.csv)\}'

    paths = re.findall(csv_pattern, markdown_content)

    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)

    return unique_paths


def create_figure_path_mapping(figure_paths: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, str]:
    """
    Create a mapping of figure paths for SVG to PDF conversions.
    This just creates the mapping without doing any actual processing.

    Args:
        figure_paths: List of (path, params) tuples extracted from the document

    Returns:
        Dictionary mapping original paths to converted paths
    """
    mapping = {}
    converted_dir = Path('converted')

    for fig_item in figure_paths:
        # Extract path from tuple (path, params)
        if isinstance(fig_item, tuple):
            fig_path = fig_item[0]
        else:
            # Backward compatibility if called with plain strings
            fig_path = fig_item

        # Only map SVG files to their PDF equivalents
        if fig_path.endswith('.svg'):
            pdf_path = fig_path.replace('.svg', '.pdf')
            output_path = converted_dir / pdf_path
            mapping[fig_path] = str(output_path)

    return mapping
