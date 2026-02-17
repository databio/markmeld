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
        """Convert SVG to PDF using inkscape.

        Args:
            svg_path: Path to SVG file.
            output_path: Path for output PDF.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Run Inkscape conversion
            cmd = [
                self.inkscape_command,
                "--batch-process",
                "--export-type=pdf",
                f"--export-filename={output_path}",
                svg_path
            ]
            
            _LOGGER.info(f"  Converting SVG to PDF: {svg_path}")
            
            # Set environment to avoid X11/DBus issues
            env = os.environ.copy()
            env['DISPLAY'] = ''
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )
            
            if result.returncode != 0:
                _LOGGER.error(f"❌ Inkscape conversion failed with return code {result.returncode}")
                _LOGGER.error(f"   Command: {' '.join(cmd)}")
                if result.stderr:
                    _LOGGER.error(f"   Error output: {result.stderr[:500]}")
                if result.stdout:
                    _LOGGER.debug(f"   Output: {result.stdout[:500]}")
                return False
            
            if not output_path.exists():
                _LOGGER.error(f"❌ PDF file was not created at {output_path}")
                _LOGGER.error(f"   SVG source: {svg_path}")
                _LOGGER.error(f"   Check if Inkscape completed successfully")
                return False
            
            # Log with relative paths for readability
            svg_rel = '/'.join(Path(svg_path).parts[-2:])
            out_rel = '/'.join(output_path.parts[-2:])
            _LOGGER.info(f"  Converted: {svg_rel} -> {out_rel}")
            return True
            
        except subprocess.TimeoutExpired:
            _LOGGER.error(f"❌ Inkscape conversion timed out after 60 seconds")
            _LOGGER.error(f"   SVG file: {svg_path}")
            _LOGGER.error(f"   This may indicate a complex or corrupted SVG file")
            return False
        except FileNotFoundError:
            _LOGGER.error(f"❌ Inkscape not found: '{self.inkscape_command}'")
            _LOGGER.error(f"   Please install Inkscape: sudo apt-get install inkscape (Ubuntu/Debian)")
            _LOGGER.error(f"   Or: brew install inkscape (macOS)")
            return False
        except Exception as e:
            _LOGGER.error(f"❌ Unexpected error in SVG conversion: {e}")
            _LOGGER.error(f"   SVG file: {svg_path}")
            return False
    
    def convert_csv(
        self, csv_path: str, output_path: Path, params: Dict[str, Any]
    ) -> bool:
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
            from weasyprint import HTML
            
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Load CSV
            df = pd.read_csv(csv_path)
            
            # Prepare parameters
            table_params = self._prepare_table_parameters(params, df)
            
            # Convert to PDF
            self._df_to_pdf(df, str(output_path), **table_params)
            
            # Log with relative paths for readability
            csv_rel = '/'.join(Path(csv_path).parts[-2:])
            out_rel = '/'.join(output_path.parts[-2:])
            _LOGGER.info(f"  Converted: {csv_rel} -> {out_rel}")
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error converting CSV to PDF: {e}")
            return False
    
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
        """Prepare table parameters for PDF generation.

        Args:
            params: Parameters from markdown.
            df: pandas DataFrame.

        Returns:
            Dictionary of parameters for table PDF builder.
        """
        import pandas as pd
        
        # Start with defaults
        table_params = self.default_table_params.copy()
        _LOGGER.debug(f"  Input params: {params}")
        
        # Extract and convert parameters
        if 'fig_width' in params:
            # Convert width like "174mm", "174", or "auto"
            width_str = str(params['fig_width']).strip().lower()
            if width_str == 'auto':
                # Use CSS auto for width
                table_params['fig_width_mm'] = 'auto'
                _LOGGER.debug(f"  Using CSS auto width")
            elif width_str.endswith('mm'):
                table_params['fig_width_mm'] = float(width_str[:-2])
                _LOGGER.debug(f"  Set width: {table_params['fig_width_mm']}mm")
            else:
                # Assume mm if no unit specified (and not 'auto')
                try:
                    table_params['fig_width_mm'] = float(width_str)
                    _LOGGER.debug(f"  Set width: {table_params['fig_width_mm']}mm")
                except ValueError:
                    _LOGGER.warning(f"  Invalid width value '{params['fig_width']}', using default")
                    # Default already in table_params
        
        if 'font-size' in params:
            # Convert font size like "6pt" or "6" to float
            size_str = str(params['font-size'])
            if size_str.endswith('pt'):
                table_params['font_size_pt'] = float(size_str[:-2])
            else:
                # Assume pt if no unit specified
                table_params['font_size_pt'] = float(size_str)
            _LOGGER.debug(f"  Set font-size: {table_params['font_size_pt']}pt")
        
        # Extract column/padding params FIRST (needed for height calculation)
        if 'col-names' in params:
            table_params['colnames'] = params['col-names'].split(',')
        else:
            table_params['colnames'] = list(df.columns)

        if 'col-widths' in params:
            widths = params['col-widths'].split(',')
            table_params['col_widths'] = [float(w.strip()) for w in widths]
        else:
            n_cols = len(df.columns)
            table_params['col_widths'] = [100.0 / n_cols] * n_cols

        if 'col-align' in params:
            table_params['col_alignments'] = params['col-align'].split(',')
        else:
            table_params['col_alignments'] = ['left'] * len(df.columns)

        if 'padding-v' in params:
            table_params['tr_padding_v'] = float(params['padding-v'])
        if 'padding-h' in params:
            table_params['tr_padding_h'] = float(params['padding-h'])

        # NOW handle height (explicit or auto-calculated)
        if 'fig_height' in params:
            height_str = str(params['fig_height']).strip().lower()
            if height_str == 'auto':
                table_params['fig_height_mm'] = 'auto'
                _LOGGER.info(f"  Using CSS auto height")
            elif height_str.endswith('mm'):
                table_params['fig_height_mm'] = float(height_str[:-2])
                _LOGGER.info(f"  Using explicit height: {table_params['fig_height_mm']}mm")
            else:
                try:
                    table_params['fig_height_mm'] = float(height_str)
                    _LOGGER.info(f"  Using explicit height: {table_params['fig_height_mm']}mm")
                except ValueError:
                    _LOGGER.warning(f"  Invalid height value '{params['fig_height']}', using CSS auto")
                    table_params['fig_height_mm'] = 'auto'
        else:
            # Auto-calculate height using actual column widths
            font_size = table_params.get('font_size_pt', 6)
            page_width = table_params.get('fig_width_mm', 174)
            if page_width == 'auto':
                page_width = 174
            table_params['fig_height_mm'] = self._find_optimal_height(
                df, table_params['col_widths'], table_params['col_alignments'],
                page_width, font_size,
                table_params.get('tr_padding_v', 1), table_params.get('tr_padding_h', 3)
            )
            _LOGGER.info(f"  Auto-calculated height: {table_params['fig_height_mm']:.2f}mm for {len(df)} data rows + header (font: {font_size}pt)")
        
        _LOGGER.debug(f"  Final table params: {table_params}")
        return table_params
    
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
        """Build CSS for table rendering.

        Args:
            col_widths: List of column widths as percentages.
            col_alignments: List of column alignments.
            page_width_mm: Page width in millimeters.
            page_height_mm: Page height in millimeters.
            font_size_pt: Font size in points.
            tr_padding_v: Vertical padding in pixels.
            tr_padding_h: Horizontal padding in pixels.

        Returns:
            CSS string for table styling.
        """
        # Column-specific CSS
        col_css = ""
        for i, (w, align) in enumerate(zip(col_widths, col_alignments)):
            col_css += f"th:nth-child({i+1}), td:nth-child({i+1}) {{ width: {w}%; text-align: {align}; box-sizing: border-box; }}\n"

        # Format dimensions
        def fmt(val):
            return 'auto' if val == 'auto' else f"{val}mm"

        width_css, height_css = fmt(page_width_mm), fmt(page_height_mm)
        page_size = "auto" if width_css == 'auto' and height_css == 'auto' else f"{width_css} {height_css}"

        return f"""<style>
          @page {{ size: {page_size}; margin: 0; }}
          body {{ font-family: Helvetica, Arial, sans-serif; font-size: {font_size_pt}pt; margin: 2mm; }}
          table {{ border-collapse: collapse; width: 100%; table-layout: fixed; padding: 0; }}
          th, td {{ border: 0; padding: {tr_padding_v}px {tr_padding_h}px; word-wrap: break-word; }}
          th {{ background-color: #ccc; color: black; font-weight: bold; }}
          tr:nth-child(even) {{ background-color: #f2f2f2; }}
          {col_css}
        </style>"""

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
        """Convert DataFrame to PDF using weasyprint.

        Args:
            df: pandas DataFrame to convert.
            output_file: Output PDF file path.
            colnames: Column header names.
            col_widths: Column widths as percentages.
            col_alignments: Column text alignments.
            fig_width_mm: Page width in millimeters.
            fig_height_mm: Page height (auto-calculated if None).
            font_size_pt: Font size in points.
            tr_padding_v: Vertical cell padding in pixels.
            tr_padding_h: Horizontal cell padding in pixels.

        Raises:
            ValueError: If column counts don't match.
        """
        from weasyprint import HTML

        if len(df.columns) != len(colnames):
            raise ValueError("Number of column names does not match DataFrame columns")
        if len(col_widths) != len(colnames):
            raise ValueError("Number of column widths does not match number of columns")
        if len(col_alignments) != len(colnames):
            raise ValueError("Number of column alignments does not match number of columns")

        # Auto-calculate height if not provided
        if fig_height_mm is None:
            page_width = fig_width_mm if fig_width_mm != 'auto' else 174
            fig_height_mm = self._find_optimal_height(
                df, col_widths, col_alignments, page_width, font_size_pt, tr_padding_v, tr_padding_h
            )

        df.columns = colnames
        css = self._build_table_css(col_widths, col_alignments, fig_width_mm, fig_height_mm,
                                     font_size_pt, tr_padding_v, tr_padding_h)

        _LOGGER.info(f"  Generating PDF with dimensions: {fig_width_mm}mm x {fig_height_mm}mm")
        HTML(string=css + df.to_html(index=False, escape=True)).write_pdf(output_file)

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
        """Find minimum page height that fits content on one page.

        Uses binary search to find optimal height.

        Args:
            df: pandas DataFrame.
            col_widths: Column widths as percentages.
            col_alignments: Column text alignments.
            page_width_mm: Page width in millimeters.
            font_size_pt: Font size in points.
            tr_padding_v: Vertical padding in pixels.
            tr_padding_h: Horizontal padding in pixels.

        Returns:
            Optimal page height in millimeters.
        """
        from weasyprint import HTML

        def fits_on_one_page(height_mm: float) -> bool:
            css = self._build_table_css(col_widths, col_alignments, page_width_mm, height_mm,
                                         font_size_pt, tr_padding_v, tr_padding_h)
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

        return high * 1.02  # Small buffer for safety

    def _guess_pdf_height_mm(
        self,
        n_rows: int,
        font_size_pt: float = 6,
        df: Any = None,
        page_width_mm: float = 174,
    ) -> float:
        """Estimate page height for table.

        Uses binary search if DataFrame provided, otherwise formula-based.

        Args:
            n_rows: Number of data rows.
            font_size_pt: Font size in points.
            df: Optional pandas DataFrame for accurate calculation.
            page_width_mm: Page width in millimeters.

        Returns:
            Estimated page height in millimeters.
        """
        if df is not None:
            # Use accurate binary search
            n_cols = len(df.columns)
            col_widths = [100.0 / n_cols] * n_cols
            col_alignments = ['left'] * n_cols
            return self._find_optimal_height(df, col_widths, col_alignments,
                                              page_width_mm, font_size_pt, 1, 3)
        else:
            # Formula fallback (for tests without df)
            slope = 2.64 + (font_size_pt - 6) * 0.353
            return (slope * n_rows + 2.5) * 1.10
    
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

    def compute_params_digest(self, params: Dict[str, Any]) -> str:
        """
        Compute a digest for a parameter dictionary.
        
        Args:
            params: Parameters dictionary
            
        Returns:
            MD5 digest of the parameters
        """
        # Sort keys for consistent ordering
        sorted_params = json.dumps(params, sort_keys=True)
        digest = hashlib.md5(sorted_params.encode()).hexdigest()
        _LOGGER.debug(f"  Computed params digest: {digest} for params: {sorted_params}")
        return digest
    
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
        """
        Parse figure parameters from markdown syntax.
        
        Handles various parameter formats:
        - Simple values: width=174mm
        - Quoted values: width="174mm"
        - Lists: col-widths="20,5,8,30,26,3"
        - Nested values: col-align="left,center,right"
        
        Args:
            param_string: String containing parameters like '{width=174mm font-size=6pt}'
            
        Returns:
            Dictionary of parsed parameters
        """
        params = {}
        if not param_string:
            return params
        
        # Remove outer braces if present
        param_string = param_string.strip()
        if param_string.startswith('{') and param_string.endswith('}'):
            param_string = param_string[1:-1].strip()
        
        # Pattern to match parameters: name=value or name="value with spaces"
        # No dot prefix required
        pattern = r'([a-zA-Z0-9_-]+)=(?:"([^"]+)"|([^\s}]+))'
        
        for match in re.finditer(pattern, param_string):
            key = match.group(1)
            # Use quoted value if present, otherwise unquoted value
            value = match.group(2) if match.group(2) else match.group(3)
            params[key] = value
        
        return params
    
    def extract_figure_paths(self, markdown_content: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract all figure paths and their parameters from markdown content.
        
        Returns:
            List of tuples (path, parameters_dict)
        """
        # Pattern to find markdown images with optional parameters
        # Matches: ![alt](path){.param=value .param2="value"}
        inline_pattern = r'!\[[^\]]*\]\(([^)]+)\)(\{[^}]*\})?'
        
        # Find reference-style images: [ref]: path
        ref_pattern = r'^\[[^\]]+\]:\s*(.+)$'
        
        figures = []
        
        # Process inline images
        for match in re.finditer(inline_pattern, markdown_content):
            path = match.group(1)
            params_str = match.group(2) if match.group(2) else ""
            params = self.parse_figure_parameters(params_str)
            figures.append((path, params))
        
        # Process reference-style images (these typically don't have parameters)
        for match in re.finditer(ref_pattern, markdown_content, re.MULTILINE):
            path = match.group(1)
            figures.append((path, {}))
        
        # Also look for CSV files with {csv/...} syntax
        csv_pattern = r'\{(csv/[^}]+\.csv)\}'
        for match in re.finditer(csv_pattern, markdown_content):
            path = match.group(1)
            # CSVs in {} syntax don't have parameters
            figures.append((path, {}))
        
        # Filter out URLs and data URIs, keep only local paths and Google Sheets
        local_figures = []
        for path, params in figures:
            if not path.startswith(('http://', 'https://', 'data:')):
                local_figures.append((path, params))
            elif 'docs.google.com/spreadsheets' in path:
                # Keep Google Sheets URLs
                local_figures.append((path, params))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_figures = []
        for path, params in local_figures:
            if path not in seen:
                seen.add(path)
                unique_figures.append((path, params))
        
        return unique_figures
