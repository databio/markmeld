"""Figure path extraction and mapping for Google Drive documents."""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def update_figure_paths(markdown_content: str, path_mapping: Dict[str, str]) -> str:
    """Replace figure paths in document with converted paths while preserving parameters.

    Args:
        markdown_content: The markdown content to update
        path_mapping: Dictionary mapping original paths to new paths

    Returns:
        Updated markdown content with paths replaced
    """
    _LOGGER.debug(f"update_figure_paths called with {len(path_mapping)} mappings")
    updated = markdown_content

    # First, handle paths with parameters - preserve the parameters
    # Pattern to match figure references with parameters
    param_pattern = r'(!\[[^\]]*\]\()([^)]+)(\))(\{[^}]*\})'

    def replace_with_mapping(match):
        prefix = match.group(1)  # ![alt](
        path = match.group(2)     # the path
        suffix = match.group(3)   # )
        params = match.group(4)   # {parameters} - now preserved

        # Check if this path has a mapping
        if path in path_mapping:
            return f"{prefix}{path_mapping[path]}{suffix}{params}"
        return f"{prefix}{path}{suffix}{params}"

    # Replace figures with parameters
    updated = re.sub(param_pattern, replace_with_mapping, updated)

    # Then handle regular path replacements for paths without parameters
    for old_path, new_path in path_mapping.items():
        # Replace in both inline and reference style images
        updated = updated.replace(f']({old_path})', f']({new_path})')
        updated = updated.replace(f']: {old_path}', f']: {new_path}')
        updated = updated.replace(f']:{old_path}', f']:{new_path}')

    return updated


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
