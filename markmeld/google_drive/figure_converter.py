"""Figure Converter - Unified handler for all figure format conversions.

This module handles conversion of various figure formats to PDF:
- SVG to PDF (via inkscape)
- CSV to PDF (via table_pdf_builder)
- Google Sheets to PDF (via table_pdf_builder)
- Direct PDF downloads (passthrough)
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..figure_conversion import (
    build_table_css as _shared_build_table_css,
    compute_params_digest as _shared_compute_params_digest,
    convert_csv as _shared_convert_csv,
    convert_svg as _shared_convert_svg,
    df_to_pdf as _shared_df_to_pdf,
    extract_figure_paths as _shared_extract_figure_paths,
    find_optimal_height as _shared_find_optimal_height,
    parse_figure_parameters as _shared_parse_figure_parameters,
    prepare_table_parameters as _shared_prepare_table_parameters,
)

_LOGGER = logging.getLogger(__name__)


class FigureConverter:
    """Handles all figure-to-PDF conversions for the markmeld system.

    Consolidates figure conversion logic with change detection and caching.

    Attributes:
        cache_manager: CloudCacheManager instance for cache operations.
        drive_service: Google Drive API service instance.
        inkscape_command: Path to inkscape executable.
        default_table_params: Default parameters for table formatting.

    Supported conversions:
        - SVG to PDF (via inkscape)
        - CSV to PDF (via weasyprint)
        - Google Sheets to PDF (via weasyprint)
    """

    def __init__(self, cache_manager: Any, drive_service: Any = None) -> None:
        """Initialize the FigureConverter.

        Args:
            cache_manager: CloudCacheManager instance for cache operations.
            drive_service: Google Drive API service instance (for Sheets).
        """
        self.cache_manager = cache_manager
        self.drive_service = drive_service
        self.inkscape_command = "inkscape"

        # Default table parameters
        self.default_table_params = {
            'fig_width_mm': 174,  # Standard page width minus margins
            'font_size_pt': 6,
            'tr_padding_v': 1,
            'tr_padding_h': 3
        }
    
    def convert_figure(
        self,
        source_path: str,
        params: Dict[str, Any],
        doc_id: str,
        file_info: Optional[Dict] = None,
        original_path: Optional[str] = None,
    ) -> Optional[str]:
        """Route figure conversion to appropriate handler.

        Args:
            source_path: Path to the source figure file (may be cached).
            params: Parameters dictionary from markdown.
            doc_id: Document ID for cache context.
            file_info: Optional file metadata from Google Drive.
            original_path: Original path from markdown (for digest keys).

        Returns:
            Relative path to converted PDF (e.g., "fig/overview.pdf"),
            or None if conversion failed.
        """
        # Use original_path for digest operations if provided
        digest_path = original_path if original_path else source_path
        
        figure_type = self.get_figure_type(source_path)
        
        if figure_type == 'pdf':
            # PDFs don't need conversion
            return source_path
        
        # Determine output path
        output_path = self.get_output_path(digest_path, doc_id, figure_type)
        
        # Check if conversion is needed
        if not self.needs_conversion(digest_path, doc_id, output_path, file_info, params):
            relative_path = self._get_relative_output_path(digest_path, figure_type)
            _LOGGER.info(f"  Using cached: {relative_path}")
            # Return relative path matching the original structure
            return self._get_relative_output_path(digest_path, figure_type)
        
        # Route to appropriate converter
        try:
            if figure_type == 'svg':
                success = self.convert_svg(source_path, output_path)
            elif figure_type == 'csv':
                success = self.convert_csv(source_path, output_path, params)
            elif figure_type == 'sheet':
                success = self._convert_gsheet(source_path, output_path, params, file_info)
            else:
                _LOGGER.warning(f"Unsupported figure type: {figure_type}")
                return None
            
            if success:
                # Save digests for future cache checks (use original path as key)
                if file_info and 'md5Checksum' in file_info:
                    _LOGGER.info(f"  Saving file digest for {digest_path}: {file_info['md5Checksum']}")
                    self.save_digest(digest_path, file_info['md5Checksum'], doc_id, 'file')
                
                # For CSV files, also save parameter digest (even if empty)
                if figure_type == 'csv':
                    params_to_save = params if params is not None else {}
                    params_digest = self.compute_params_digest(params_to_save)
                    _LOGGER.info(f"  Saving params digest for {digest_path}: {params_digest}")
                    _LOGGER.info(f"  Params being saved: {params_to_save}")
                    self.save_digest(digest_path, params_digest, doc_id, 'params')

                # Return relative path matching the original structure
                return self._get_relative_output_path(digest_path, figure_type)
            else:
                return None
                
        except Exception as e:
            _LOGGER.error(f"Error converting {source_path}: {e}")
            return None
    
    def get_figure_type(self, path: str) -> str:
        """Detect figure type from path or URL.

        Args:
            path: File path or URL.

        Returns:
            Figure type: 'svg', 'csv', 'sheet', 'pdf', or 'unknown'.
        """
        path_lower = path.lower()
        
        if path_lower.endswith('.svg'):
            return 'svg'
        elif path_lower.endswith('.csv'):
            return 'csv'
        elif path_lower.endswith('.pdf'):
            return 'pdf'
        elif 'docs.google.com/spreadsheets' in path:
            return 'sheet'
        else:
            return 'unknown'
    
    def needs_conversion(
        self,
        source_path: str,
        doc_id: str,
        output_path: Path,
        file_info: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> bool:
        """Check if conversion is needed based on cache and digests.

        Args:
            source_path: Source file path.
            doc_id: Document ID for cache context.
            output_path: Target output path.
            file_info: Optional file metadata with MD5 checksum.
            params: Optional parameters for table conversion.

        Returns:
            True if conversion needed, False if cached version is current.
        """
        # If output doesn't exist, conversion is needed
        if not output_path.exists():
            return True
        
        figure_type = self.get_figure_type(source_path)
        
        # For Google Sheets, check modified time
        if figure_type == 'sheet' and file_info:
            # TODO: Implement modified time checking for sheets
            # For now, always reconvert sheets
            return True
        
        # For CSV files, check both file digest AND parameter digest
        if figure_type == 'csv':
            _LOGGER.debug(f"  Checking CSV cache for: {source_path}")
            _LOGGER.debug(f"  Params provided: {params}")
            
            # Check file digest
            if file_info and 'md5Checksum' in file_info:
                stored_file_digest = self._load_digest(source_path, doc_id, 'file')
                current_digest = file_info.get('md5Checksum')
                _LOGGER.info(f"  File digest - stored: {stored_file_digest}, current: {current_digest}")
                if stored_file_digest != current_digest:
                    _LOGGER.info(f"  File has changed, re-converting")
                    return True  # File has changed
            else:
                # No file_info provided - can't check file changes, assume needs conversion
                _LOGGER.debug(f"  No file_info provided for CSV, assuming needs conversion")
                return True
            
            # Check parameter digest (even if params is empty dict)
            params_to_check = params if params is not None else {}
            params_digest = self.compute_params_digest(params_to_check)
            stored_params_digest = self._load_digest(source_path, doc_id, 'params')
            _LOGGER.info(f"  Params digest - stored: {stored_params_digest}, current: {params_digest}")
            _LOGGER.debug(f"  Current params: {params_to_check}")
            if stored_params_digest != params_digest:
                _LOGGER.info(f"  Parameters changed - re-converting")
                _LOGGER.info(f"    Old digest: {stored_params_digest}")
                _LOGGER.info(f"    New digest: {params_digest}")
                _LOGGER.info(f"    New params: {params_to_check}")
                return True  # Parameters have changed
            
            _LOGGER.debug(f"  Both file and params unchanged, using cache")
            return False  # Both file and params unchanged
        
        # For other files (SVG, etc.), check MD5 digest
        if file_info and 'md5Checksum' in file_info:
            stored_digest = self._load_digest(source_path, doc_id, 'file')
            if stored_digest == file_info['md5Checksum']:
                return False  # File hasn't changed
        
        return True
    
    def convert_svg(self, svg_path: str, output_path: Path) -> bool:
        """Convert SVG to PDF using inkscape. Delegates to shared helper."""
        return _shared_convert_svg(svg_path, output_path)
    
    def convert_csv(
        self, csv_path: str, output_path: Path, params: Dict[str, Any]
    ) -> bool:
        """Convert CSV to PDF using weasyprint. Delegates to shared helper."""
        return _shared_convert_csv(csv_path, output_path, params)
    
    def _convert_gsheet(
        self,
        sheet_url: str,
        output_path: Path,
        params: Dict[str, Any],
        file_info: Optional[Dict] = None,
    ) -> bool:
        """Convert Google Sheet to PDF.

        Args:
            sheet_url: Google Sheets URL or ID.
            output_path: Path for output PDF.
            params: Table formatting parameters.
            file_info: Optional file metadata from Google Drive.

        Returns:
            True if successful, False otherwise.
        """
        try:
            import pandas as pd
            from weasyprint import HTML
            
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract sheet ID from URL
            if "docs.google.com" in sheet_url:
                sheet_id = sheet_url.split("/d/")[1].split("/")[0]
            else:
                sheet_id = sheet_url
            
            # Get worksheet name from parameters if specified
            worksheet = params.get('worksheet', None)
            
            # Download sheet data using Drive API
            df = self._download_sheet_as_dataframe(sheet_id, worksheet)
            
            if df is None:
                _LOGGER.error(f"Failed to download Google Sheet: {sheet_id}")
                return False
            
            # Prepare parameters
            table_params = self._prepare_table_parameters(params, df)
            
            # Convert to PDF
            self._df_to_pdf(df, str(output_path), **table_params)
            
            out_rel = '/'.join(output_path.parts[-2:])
            _LOGGER.info(f"  Converted: Google Sheet {sheet_id} -> {out_rel}")
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error converting Google Sheet to PDF: {e}")
            return False
    
    def _download_sheet_as_dataframe(
        self, sheet_id: str, worksheet: Optional[str] = None
    ) -> Optional[Any]:
        """Download Google Sheet as pandas DataFrame using Drive API.

        Args:
            sheet_id: Google Sheet ID.
            worksheet: Optional worksheet name.

        Returns:
            pandas DataFrame or None if failed.
        """
        if not self.drive_service:
            _LOGGER.error("Drive service not available for Sheet download")
            return None
        
        try:
            import pandas as pd
            from googleapiclient.http import MediaIoBaseDownload
            
            # Export sheet as CSV using Drive API
            request = self.drive_service.files().export_media(
                fileId=sheet_id,
                mimeType='text/csv'
            )
            
            # Download into memory
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            done = False
            
            while not done:
                status, done = downloader.next_chunk()
            
            # Parse CSV content
            file_content.seek(0)
            df = pd.read_csv(file_content)
            
            # Clean empty rows
            df = df.dropna(how='all')
            
            return df
            
        except Exception as e:
            _LOGGER.error(f"Error downloading Google Sheet: {e}")
            return None
    
    def _prepare_table_parameters(
        self, params: Dict[str, Any], df: Any
    ) -> Dict[str, Any]:
        """Prepare table parameters. Delegates to shared helper."""
        return _shared_prepare_table_parameters(params, df)

    def _build_table_css(
        self,
        col_widths: List[float],
        col_alignments: List[str],
        page_width_mm: float,
        page_height_mm: float,
        font_size_pt: float,
        tr_padding_v: float,
        tr_padding_h: float,
    ) -> str:
        """Build CSS for table rendering. Delegates to shared helper."""
        return _shared_build_table_css(
            col_widths, col_alignments, page_width_mm, page_height_mm,
            font_size_pt, tr_padding_v, tr_padding_h
        )

    def _df_to_pdf(
        self,
        df: Any,
        output_file: str,
        colnames: List[str],
        col_widths: List[float],
        col_alignments: List[str],
        fig_width_mm: float,
        fig_height_mm: Optional[float] = None,
        font_size_pt: float = 6,
        tr_padding_v: float = 1,
        tr_padding_h: float = 3,
    ) -> None:
        """Convert DataFrame to PDF. Delegates to shared helper."""
        _shared_df_to_pdf(
            df, output_file, colnames, col_widths, col_alignments,
            fig_width_mm, fig_height_mm, font_size_pt, tr_padding_v, tr_padding_h
        )

    def _find_optimal_height(
        self,
        df: Any,
        col_widths: List[float],
        col_alignments: List[str],
        page_width_mm: float,
        font_size_pt: float,
        tr_padding_v: float,
        tr_padding_h: float,
    ) -> float:
        """Find optimal page height. Delegates to shared helper."""
        return _shared_find_optimal_height(
            df, col_widths, col_alignments, page_width_mm,
            font_size_pt, tr_padding_v, tr_padding_h
        )

    def _guess_pdf_height_mm(
        self,
        n_rows: int,
        font_size_pt: float = 6,
        df: Any = None,
        page_width_mm: float = 174,
    ) -> float:
        """Estimate page height for table."""
        if df is not None:
            n_cols = len(df.columns)
            col_widths = [100.0 / n_cols] * n_cols
            col_alignments = ['left'] * n_cols
            return _shared_find_optimal_height(
                df, col_widths, col_alignments, page_width_mm, font_size_pt, 1, 3
            )
        else:
            slope = 2.64 + (font_size_pt - 6) * 0.353
            return (slope * n_rows + 2.5) * 1.10

    def compute_params_digest(self, params: Dict[str, Any]) -> str:
        """Compute params digest. Delegates to shared helper."""
        return _shared_compute_params_digest(params)
    
    def get_output_path(self, source_path: str, doc_id: str, figure_type: str) -> Path:
        """Determine the output path for converted figure.

        Args:
            source_path: Source file path or URL.
            doc_id: Document ID for cache context.
            figure_type: Type of figure ('svg', 'csv', 'sheet').

        Returns:
            Absolute path for the output PDF file.
        """
        if figure_type == 'svg':
            # For SVG files, replace extension with .pdf
            pdf_path = source_path.replace('.svg', '.pdf')
            return self.cache_manager.get_cache_path(doc_id, 'converted', pdf_path)
        elif figure_type == 'csv':
            # For CSV files, replace extension with .pdf
            pdf_path = source_path.replace('.csv', '.pdf')
            return self.cache_manager.get_cache_path(doc_id, 'converted', pdf_path)
        elif figure_type == 'sheet':
            # For Google Sheets, create a unique filename
            sheet_id = source_path.split("/d/")[1].split("/")[0] if "docs.google.com" in source_path else source_path
            return self.cache_manager.get_cache_path(doc_id, 'converted', f'sheets/{sheet_id}.pdf')
        else:
            return Path(source_path)

    def _get_relative_output_path(self, source_path: str, figure_type: str) -> str:
        """Get relative output path for a converted figure.

        Preserves directory structure, just changes extension to .pdf.

        Args:
            source_path: Original path from markdown (e.g., "fig/overview.svg").
            figure_type: Type of figure ('svg', 'csv', 'sheet').

        Returns:
            Relative path string with PDF extension.

        Example:
            >>> _get_relative_output_path("fig/overview.svg", "svg")
            'fig/overview.pdf'
        """
        if figure_type == 'svg':
            return source_path.replace('.svg', '.pdf')
        elif figure_type == 'csv':
            return source_path.replace('.csv', '.pdf')
        elif figure_type == 'sheet':
            # For Google Sheets, create a unique filename
            sheet_id = source_path.split("/d/")[1].split("/")[0] if "docs.google.com" in source_path else source_path
            return f'sheets/{sheet_id}.pdf'
        else:
            return source_path

    def _load_digest(self, file_path: str, doc_id: str, digest_type: str = 'file') -> Optional[str]:
        """
        Load stored digest for a file.
        Delegates to CloudCacheManager.
        
        Args:
            file_path: Source file path
            doc_id: Document ID
            digest_type: 'file' for file content digest, 'params' for parameter digest
        """
        if digest_type == 'params':
            identifier = str(Path(file_path).with_suffix('.params'))
        else:
            identifier = file_path
        
        return self.cache_manager.load_digest(doc_id, identifier)
    
    def save_digest(self, file_path: str, digest: str, doc_id: str, digest_type: str = 'file'):
        """
        Save digest for a file.
        Delegates to CloudCacheManager.
        
        Args:
            file_path: Source file path
            digest: Digest value to save
            doc_id: Document ID
            digest_type: 'file' for file content digest, 'params' for parameter digest
        """
        if digest_type == 'params':
            identifier = str(Path(file_path).with_suffix('.params'))
        else:
            identifier = file_path
        
        self.cache_manager.save_digest(doc_id, identifier, digest)
    
    def parse_figure_parameters(self, param_string: str) -> dict:
        """Parse figure parameters from markdown syntax. Delegates to shared helper."""
        return _shared_parse_figure_parameters(param_string)
    
    def extract_figure_paths(self, markdown_content: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract all figure paths and their parameters from markdown content.

        Delegates to shared helper, then adds Google Drive-specific patterns
        (CSV {} syntax, Google Sheets URLs).
        """
        # Get base figures from shared extractor
        figures = _shared_extract_figure_paths(markdown_content)

        # Also look for CSV files with {csv/...} syntax (Drive-specific)
        csv_pattern = r'\{(csv/[^}]+\.csv)\}'
        for match in re.finditer(csv_pattern, markdown_content):
            path = match.group(1)
            figures.append((path, {}))

        # Re-add Google Sheets URLs that the shared extractor filters out
        inline_pattern = r'!\[(?:[^\[\]]|\[[^\]]*\])*\]\(([^)]+)\)(\{[^}]*\})?'
        for match in re.finditer(inline_pattern, markdown_content):
            path = match.group(1)
            if 'docs.google.com/spreadsheets' in path:
                params_str = match.group(2) if match.group(2) else ""
                params = _shared_parse_figure_parameters(params_str)
                figures.append((path, params))

        # Remove duplicates while preserving order
        seen = set()
        unique_figures = []
        for path, params in figures:
            if path not in seen:
                seen.add(path)
                unique_figures.append((path, params))

        return unique_figures
