"""
Figure Converter - Unified handler for all figure format conversions.

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
from typing import Optional, Dict, Any, Tuple, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class FigureConverter:
    """
    Handles all figure-to-PDF conversions for the markmeld system.
    
    This class consolidates all figure conversion logic, providing:
    - SVG to PDF conversion (via inkscape)
    - CSV to PDF conversion (via table_pdf_builder)
    - Google Sheets to PDF conversion (via table_pdf_builder)
    - Change detection and caching
    - Parameter handling for table formatting
    """
    
    def __init__(self, cache_manager, drive_service=None):
        """
        Initialize the FigureConverter.
        
        Args:
            cache_manager: CloudCacheManager instance for cache operations
            drive_service: Google Drive API service instance (for Sheets conversion)
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
    
    def convert_figure(self, source_path: str, params: Dict[str, Any], 
                      doc_id: str, file_info: Optional[Dict] = None, 
                      original_path: Optional[str] = None) -> Optional[str]:
        """
        Main routing method for figure conversion.
        
        Args:
            source_path: Path to the source figure file (may be cached path)
            params: Parameters dictionary from markdown
            doc_id: Document ID for cache context
            file_info: Optional file metadata from Google Drive
            original_path: Original path from markdown (for digest keys)
            
        Returns:
            Path to the converted PDF file, or None if conversion failed
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
            logger.info(f"  Using cached: {output_path}")
            return str(output_path)
        
        # Route to appropriate converter
        try:
            if figure_type == 'svg':
                success = self.convert_svg(source_path, output_path)
            elif figure_type == 'csv':
                success = self.convert_csv(source_path, output_path, params)
            elif figure_type == 'sheet':
                success = self._convert_gsheet(source_path, output_path, params, file_info)
            else:
                logger.warning(f"Unsupported figure type: {figure_type}")
                return None
            
            if success:
                # Save digests for future cache checks (use original path as key)
                if file_info and 'md5Checksum' in file_info:
                    logger.info(f"  Saving file digest for {digest_path}: {file_info['md5Checksum']}")
                    self.save_digest(digest_path, file_info['md5Checksum'], doc_id, 'file')
                
                # For CSV files, also save parameter digest (even if empty)
                if figure_type == 'csv':
                    params_to_save = params if params is not None else {}
                    params_digest = self.compute_params_digest(params_to_save)
                    logger.info(f"  Saving params digest for {digest_path}: {params_digest}")
                    logger.info(f"  Params being saved: {params_to_save}")
                    self.save_digest(digest_path, params_digest, doc_id, 'params')
                
                return str(output_path)
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error converting {source_path}: {e}")
            return None
    
    def get_figure_type(self, path: str) -> str:
        """
        Detect figure type from path.
        
        Args:
            path: File path or URL
            
        Returns:
            Figure type: 'svg', 'csv', 'sheet', 'pdf', or 'unknown'
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
    
    def needs_conversion(self, source_path: str, doc_id: str, 
                         output_path: Path, file_info: Optional[Dict] = None,
                         params: Optional[Dict] = None) -> bool:
        """
        Check if conversion is needed.
        
        Args:
            source_path: Source file path
            doc_id: Document ID for cache context
            output_path: Target output path
            file_info: Optional file metadata with MD5 checksum
            params: Optional parameters for table conversion
            
        Returns:
            True if conversion is needed, False if cached version is current
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
            logger.debug(f"  Checking CSV cache for: {source_path}")
            logger.debug(f"  Params provided: {params}")
            
            # Check file digest
            if file_info and 'md5Checksum' in file_info:
                stored_file_digest = self._load_digest(source_path, doc_id, 'file')
                current_digest = file_info.get('md5Checksum')
                logger.info(f"  File digest - stored: {stored_file_digest}, current: {current_digest}")
                if stored_file_digest != current_digest:
                    logger.info(f"  File has changed, re-converting")
                    return True  # File has changed
            else:
                # No file_info provided - can't check file changes, assume needs conversion
                logger.debug(f"  No file_info provided for CSV, assuming needs conversion")
                return True
            
            # Check parameter digest (even if params is empty dict)
            params_to_check = params if params is not None else {}
            params_digest = self.compute_params_digest(params_to_check)
            stored_params_digest = self._load_digest(source_path, doc_id, 'params')
            logger.info(f"  Params digest - stored: {stored_params_digest}, current: {params_digest}")
            logger.debug(f"  Current params: {params_to_check}")
            if stored_params_digest != params_digest:
                logger.info(f"  Parameters changed - re-converting")
                logger.info(f"    Old digest: {stored_params_digest}")
                logger.info(f"    New digest: {params_digest}")
                logger.info(f"    New params: {params_to_check}")
                return True  # Parameters have changed
            
            logger.debug(f"  Both file and params unchanged, using cache")
            return False  # Both file and params unchanged
        
        # For other files (SVG, etc.), check MD5 digest
        if file_info and 'md5Checksum' in file_info:
            stored_digest = self._load_digest(source_path, doc_id, 'file')
            if stored_digest == file_info['md5Checksum']:
                return False  # File hasn't changed
        
        return True
    
    def convert_svg(self, svg_path: str, output_path: Path) -> bool:
        """
        Convert SVG to PDF using inkscape.
        
        Args:
            svg_path: Path to SVG file
            output_path: Path for output PDF
            
        Returns:
            True if successful, False otherwise
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
            
            logger.info(f"  Converting SVG to PDF: {svg_path}")
            
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
                logger.error(f"Inkscape error: {result.stderr}")
                return False
            
            if not output_path.exists():
                logger.error(f"PDF file was not created at {output_path}")
                return False
            
            logger.info(f"  Converted: {svg_path} -> {output_path}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Inkscape conversion timed out")
            return False
        except FileNotFoundError:
            logger.error(f"Inkscape not found: '{self.inkscape_command}'")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in SVG conversion: {e}")
            return False
    
    def convert_csv(self, csv_path: str, output_path: Path, params: Dict[str, Any]) -> bool:
        """
        Convert CSV to PDF using table_pdf_builder.
        
        Args:
            csv_path: Path to CSV file
            output_path: Path for output PDF
            params: Table formatting parameters
            
        Returns:
            True if successful, False otherwise
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
            
            logger.info(f"  Converted: {csv_path} -> {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error converting CSV to PDF: {e}")
            return False
    
    def _convert_gsheet(self, sheet_url: str, output_path: Path, 
                       params: Dict[str, Any], file_info: Optional[Dict] = None) -> bool:
        """
        Convert Google Sheet to PDF.
        
        Args:
            sheet_url: Google Sheets URL or ID
            output_path: Path for output PDF
            params: Table formatting parameters
            file_info: Optional file metadata from Google Drive
            
        Returns:
            True if successful, False otherwise
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
                logger.error(f"Failed to download Google Sheet: {sheet_id}")
                return False
            
            # Prepare parameters
            table_params = self._prepare_table_parameters(params, df)
            
            # Convert to PDF
            self._df_to_pdf(df, str(output_path), **table_params)
            
            logger.info(f"  Converted: Google Sheet {sheet_id} -> {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error converting Google Sheet to PDF: {e}")
            return False
    
    def _download_sheet_as_dataframe(self, sheet_id: str, worksheet: Optional[str] = None):
        """
        Download Google Sheet as pandas DataFrame using Drive API.
        
        Args:
            sheet_id: Google Sheet ID
            worksheet: Optional worksheet name
            
        Returns:
            pandas DataFrame or None if failed
        """
        if not self.drive_service:
            logger.error("Drive service not available for Sheet download")
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
            logger.error(f"Error downloading Google Sheet: {e}")
            return None
    
    def _prepare_table_parameters(self, params: Dict[str, Any], df) -> Dict[str, Any]:
        """
        Prepare table parameters for PDF generation.
        
        Args:
            params: Parameters from markdown
            df: pandas DataFrame
            
        Returns:
            Dictionary of parameters for table_pdf_builder
        """
        import pandas as pd
        
        # Start with defaults
        table_params = self.default_table_params.copy()
        logger.debug(f"  Input params: {params}")
        
        # Extract and convert parameters
        if 'fig_width' in params:
            # Convert width like "174mm", "174", or "auto"
            width_str = str(params['fig_width']).strip().lower()
            if width_str == 'auto':
                # Use CSS auto for width
                table_params['fig_width_mm'] = 'auto'
                logger.debug(f"  Using CSS auto width")
            elif width_str.endswith('mm'):
                table_params['fig_width_mm'] = float(width_str[:-2])
                logger.debug(f"  Set width: {table_params['fig_width_mm']}mm")
            else:
                # Assume mm if no unit specified (and not 'auto')
                try:
                    table_params['fig_width_mm'] = float(width_str)
                    logger.debug(f"  Set width: {table_params['fig_width_mm']}mm")
                except ValueError:
                    logger.warning(f"  Invalid width value '{params['fig_width']}', using default")
                    # Default already in table_params
        
        if 'font-size' in params:
            # Convert font size like "6pt" or "6" to float
            size_str = str(params['font-size'])
            if size_str.endswith('pt'):
                table_params['font_size_pt'] = float(size_str[:-2])
            else:
                # Assume pt if no unit specified
                table_params['font_size_pt'] = float(size_str)
            logger.debug(f"  Set font-size: {table_params['font_size_pt']}pt")
        
        if 'fig_height' in params:
            # Convert height like "200mm", "200", or "auto"
            height_str = str(params['fig_height']).strip().lower()
            if height_str == 'auto':
                # Use CSS auto for height
                table_params['fig_height_mm'] = 'auto'
                logger.info(f"  Using CSS auto height")
            elif height_str.endswith('mm'):
                table_params['fig_height_mm'] = float(height_str[:-2])
                logger.info(f"  Using explicit height: {table_params['fig_height_mm']}mm")
            else:
                # Assume mm if no unit specified (and not 'auto')
                try:
                    table_params['fig_height_mm'] = float(height_str)
                    logger.info(f"  Using explicit height: {table_params['fig_height_mm']}mm")
                except ValueError:
                    # If conversion fails, fall back to CSS auto
                    logger.warning(f"  Invalid height value '{params['fig_height']}', using CSS auto")
                    table_params['fig_height_mm'] = 'auto'
        else:
            # Auto-calculate height based on row count (+1 for header)
            table_params['fig_height_mm'] = self._guess_pdf_height_mm(len(df) + 1)
            logger.info(f"  Auto-calculated height: {table_params['fig_height_mm']}mm for {len(df)} data rows + header")
        
        # Column names (default to DataFrame columns)
        if 'col-names' in params:
            table_params['colnames'] = params['col-names'].split(',')
        else:
            table_params['colnames'] = list(df.columns)
        
        # Column widths
        if 'col-widths' in params:
            widths = params['col-widths'].split(',')
            table_params['col_widths'] = [float(w.strip()) for w in widths]
        else:
            # Equal distribution
            n_cols = len(df.columns)
            table_params['col_widths'] = [100.0 / n_cols] * n_cols
        
        # Column alignments
        if 'col-align' in params:
            table_params['col_alignments'] = params['col-align'].split(',')
        else:
            table_params['col_alignments'] = ['left'] * len(df.columns)
        
        # Padding parameters
        if 'padding-v' in params:
            table_params['tr_padding_v'] = float(params['padding-v'])
        if 'padding-h' in params:
            table_params['tr_padding_h'] = float(params['padding-h'])
        
        logger.debug(f"  Final table params: {table_params}")
        return table_params
    
    def _df_to_pdf(self, df, output_file: str, colnames: list, col_widths: list,
                  col_alignments: list, fig_width_mm: float, fig_height_mm: float = None,
                  font_size_pt: float = 6, tr_padding_v: float = 1, tr_padding_h: float = 3):
        """
        Convert DataFrame to PDF (adapted from table_pdf_builder).
        """
        from weasyprint import HTML
        
        if len(df.columns) != len(colnames):
            raise ValueError("Number of column names does not match DataFrame columns")
        if len(col_widths) != len(colnames):
            raise ValueError("Number of column widths does not match number of columns")
        if len(col_alignments) != len(colnames):
            raise ValueError("Number of column alignments does not match number of columns")
        
        if fig_height_mm is None:
            fig_height_mm = self._guess_pdf_height_mm(len(df) + 1)  # +1 for header
        
        # Replace column names
        df.columns = colnames
        
        # Build column width & alignment CSS
        col_css = ""
        for i, (w, align) in enumerate(zip(col_widths, col_alignments)):
            col_css += f"th:nth-child({i+1}), td:nth-child({i+1}) {{ width: {w}%; text-align: {align}; box-sizing: border-box; }}\n"
        
        # Build CSS
        # Handle 'auto' dimensions and numeric values
        def format_dimension(value):
            """Format dimension value for CSS."""
            if value == 'auto':
                return 'auto'
            else:
                return f"{value}mm"
        
        width_css = format_dimension(fig_width_mm)
        height_css = format_dimension(fig_height_mm)
        
        if width_css == 'auto' and height_css == 'auto':
            page_size = "auto"
        else:
            page_size = f"{width_css} {height_css}"
        
        logger.info(f"  Generating PDF with dimensions: {width_css} x {height_css}")
        
        css = f"""
        <style>
          @page {{
            size: {page_size};
            margin: 0;
          }}
          body {{
            font-family: Helvetica, Arial, sans-serif;
            font-size: {font_size_pt}pt;
            margin: 2mm;
          }}
          table {{
            border-collapse: collapse;
            width: 100%;
            table-layout: fixed;
            padding: 0;
          }}
          th, td {{
            border: 0;
            padding: {tr_padding_v}px {tr_padding_h}px;
            word-wrap: break-word;
          }}
          th {{
            background-color: #ccc;
            color: black;
            font-weight: bold;
          }}
          tr:nth-child(even) {{background-color: #f2f2f2;}}
          {col_css}
        </style>
        """
        
        # Generate HTML
        html_content = css + df.to_html(index=False, escape=True)
        
        # Render PDF
        HTML(string=html_content).write_pdf(output_file)
    
    def _guess_pdf_height_mm(self, n_rows: int) -> float:
        """
        Estimate page height (mm) based on number of rows.
        """
        slope = (215 - 12) / (60 - 3)   # ~3.5614
        intercept = 12 - slope * 3      # ~1.316
        return slope * n_rows + intercept
    
    def get_output_path(self, source_path: str, doc_id: str, figure_type: str) -> Path:
        """
        Determine the output path for converted figure.
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
        logger.debug(f"  Computed params digest: {digest} for params: {sorted_params}")
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