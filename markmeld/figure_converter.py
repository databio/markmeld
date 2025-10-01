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
                logger.error(f"❌ Inkscape conversion failed with return code {result.returncode}")
                logger.error(f"   Command: {' '.join(cmd)}")
                if result.stderr:
                    logger.error(f"   Error output: {result.stderr[:500]}")
                if result.stdout:
                    logger.debug(f"   Output: {result.stdout[:500]}")
                return False
            
            if not output_path.exists():
                logger.error(f"❌ PDF file was not created at {output_path}")
                logger.error(f"   SVG source: {svg_path}")
                logger.error(f"   Check if Inkscape completed successfully")
                return False
            
            logger.info(f"  Converted: {svg_path} -> {output_path}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Inkscape conversion timed out after 60 seconds")
            logger.error(f"   SVG file: {svg_path}")
            logger.error(f"   This may indicate a complex or corrupted SVG file")
            return False
        except FileNotFoundError:
            logger.error(f"❌ Inkscape not found: '{self.inkscape_command}'")
            logger.error(f"   Please install Inkscape: sudo apt-get install inkscape (Ubuntu/Debian)")
            logger.error(f"   Or: brew install inkscape (macOS)")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error in SVG conversion: {e}")
            logger.error(f"   SVG file: {svg_path}")
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
    
    def extract_figure_references(self, markdown_content: str) -> List[Tuple[str, int, str, int, str]]:
        """
        Extract all figure references from markdown content.

        Finds references in formats like:
        - (Fig. 2), (Figure 2), (Fig 2)
        - (Fig. 2A), (Fig. 3B, 3C), (Figure 3B-D)
        - (Figure S2), (Supplemental Figure 2)
        - Figure \ref{fig:label} with or without spaces before panels
        - Non-parenthetic references: "as shown in Figure 2"

        Returns:
            List of tuples: (reference_text, figure_number, panel_letters, line_number, context)
        """
        references = []
        lines = markdown_content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Skip lines that are image definitions
            if line.strip().startswith('![') or re.match(r'^\s*\[[^\]]+\]:\s*', line):
                continue

            # Track positions already matched to avoid duplicates
            matched_positions = set()

            # Simplified patterns - handle each type separately for better control
            patterns = [
                # LaTeX ref style with panel - NO space allowed before panel letter
                r'\(?\s*Fig(?:ure)?\.?\s*\\ref\{[^}]+\}[A-Z]?(?:-[A-Z])?(?:[,;]\s*[^)]*)?[)]?',
                # LaTeX ref style WITHOUT panel but potentially with space (error case)
                r'\(\s*Fig(?:ure)?\.?\s*\\ref\{[^}]+\}\s+[A-Z]?\)',
                # Parenthetic simple figures - improved to handle commas/semicolons after panels
                r'\(\s*(?:Supplemental\s+)?Fig(?:ure)?\.?\s*S?\d+[A-Z]?(?:-[A-Z])?(?:[,;]\s*[^)]*)?[)]?',
                # Multiple panels in parentheses (e.g., "Fig. 3A, 3B")
                r'\(\s*Fig(?:ure)?\.?\s*S?\d+[A-Z]?(?:\s*,\s*S?\d*[A-Z])+(?:[,;]\s*[^)]*)?[)]?',
                # Context phrases (including "shown in")
                r'(?:as\s+shown\s+in\s+|see\s+|shown\s+in\s+|described\s+in\s+|illustrated\s+in\s+)Fig(?:ure)?\.?\s*(?:\\ref\{[^}]+\}|S?\d+)[A-Z]?(?:-[A-Z])?',
                # Standalone references (but not after "in" to avoid duplicates)
                r'(?<![(\w])(?<!in\s)Fig(?:ure)?\.?\s*(?:\\ref\{[^}]+\}|S?\d+)[A-Z]?(?:-[A-Z])?(?![)\w])'
            ]

            for pattern in patterns:
                for match in re.finditer(pattern, line, re.IGNORECASE):
                    # Check if any part of this match overlaps with already matched positions
                    if any(pos in matched_positions for pos in range(match.start(), match.end())):
                        continue

                    # Mark this position range as matched
                    for pos in range(match.start(), match.end()):
                        matched_positions.add(pos)

                    ref_text = match.group(0).strip()

                    # Clean up the reference text (remove trailing punctuation that's not part of parentheses)
                    if ref_text and ref_text[-1] in ',;' and not ref_text.startswith('('):
                        ref_text = ref_text[:-1]

                    # Check if this is a multi-figure reference
                    multi_refs = self.parse_multi_figure_reference(ref_text)

                    if multi_refs:
                        # Get context once for all references in this match
                        start_pos = max(0, match.start() - 30)
                        end_pos = min(len(line), match.end() + 30)
                        context = line[start_pos:end_pos].strip()

                        # Add each figure reference separately
                        for figure_num, panels in multi_refs:
                            references.append((
                                ref_text,  # Keep original text for reporting
                                figure_num,
                                panels,
                                line_num,
                                context
                            ))
                    else:
                        # Single reference - parse normally
                        parsed = self.parse_figure_reference(ref_text)
                        if parsed:
                            figure_num, panels = parsed

                            # Get context (surrounding text)
                            start_pos = max(0, match.start() - 30)
                            end_pos = min(len(line), match.end() + 30)
                            context = line[start_pos:end_pos].strip()

                            references.append((
                                ref_text,
                                figure_num,
                                panels,
                                line_num,
                                context
                            ))

        return references
    
    def parse_multi_figure_reference(self, ref_text: str) -> Optional[List[Tuple[str, str]]]:
        """
        Parse multi-figure references like "(Fig. 3A, 3B)" or "(Fig. S3, S4)".
        
        Args:
            ref_text: Reference text that might contain multiple figures
            
        Returns:
            List of tuples (figure_number, panel_letters) or None if not multi-ref
        """
        # Check for patterns like "(Fig. 3A, 3B)" or "(Fig. S3, S4)"
        # Pattern: Fig. followed by figure number, then comma-separated additional refs
        pattern = r'\(?\s*Fig(?:ure)?\.?\s*(S?\d+)([A-Z](?:-[A-Z])?)?(?:\s*,\s*([S\d]+[A-Z]?(?:-[A-Z])?(?:\s*,\s*[S\d]+[A-Z]?(?:-[A-Z])?)*))?\)?'
        
        match = re.match(pattern, ref_text, re.IGNORECASE)
        if match and match.group(3):  # Has comma-separated parts
            refs = []
            
            # First figure
            fig_num = match.group(1)
            panel = match.group(2) or ''
            refs.append((fig_num, panel))
            
            # Additional figures
            additional = match.group(3)
            if additional:
                # Split by comma and process each
                for part in additional.split(','):
                    part = part.strip()
                    # Check if it's just a panel letter (e.g., "3B")
                    if re.match(r'^[A-Z](?:-[A-Z])?$', part):
                        # Just a panel for the same figure
                        refs.append((fig_num, part))
                    elif re.match(r'^S?\d+[A-Z]?(?:-[A-Z])?$', part):
                        # Parse figure number and optional panel
                        num_match = re.match(r'^(S?\d+)([A-Z](?:-[A-Z])?)?$', part)
                        if num_match:
                            refs.append((num_match.group(1), num_match.group(2) or ''))
            
            return refs if len(refs) > 1 else None
        
        return None
    
    def parse_figure_reference(self, ref_text: str) -> Optional[Tuple[str, str]]:
        """
        Parse a figure reference to extract figure number and panel letters.

        Args:
            ref_text: Reference text like "(Fig. 3B)", "Figure S2", etc.

        Returns:
            Tuple of (figure_number, panel_letters) or None if parsing fails
        """
        # Clean up the text - remove parentheses and trailing punctuation
        ref_text = ref_text.strip('()')
        if ref_text and ref_text[-1] in ',;':
            ref_text = ref_text[:-1]

        # Handle LaTeX \ref{} style
        if '\\ref{' in ref_text:
            # Extract the label
            label_match = re.search(r'\\ref\{([^}]+)\}', ref_text)
            if label_match:
                label = label_match.group(1)
                # Check for panel letters IMMEDIATELY after the ref (NO space allowed)
                # Spaces before panel letters are LaTeX errors
                panel_match = re.search(r'\\ref\{[^}]+\}([A-Z](?:-[A-Z])?)', ref_text)
                panels = panel_match.group(1) if panel_match else ''
                return (label, panels)

        # Handle regular figure references
        # Match patterns like "Fig. 3B", "Figure S2", "Supplemental Figure 2"
        # Now also handles spaces before panels
        patterns = [
            # Standard format with optional space before panel
            r'(?:Supplemental\s+)?Fig(?:ure)?\.?\s*(S?\d+)\s*([A-Z](?:-[A-Z])?)?',
            # Handle single panel letter
            r'(?:Supplemental\s+)?Fig(?:ure)?\.?\s*(S?\d+)\s*([A-Z])',
            # Handle comma-separated panels like "3B, 3C"
            r'(\d+)\s*([A-Z](?:\s*,\s*[A-Z])*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, ref_text, re.IGNORECASE)
            if match:
                figure_num = match.group(1)
                panels = match.group(2) if len(match.groups()) > 1 and match.group(2) else ''
                # Clean up panels - remove spaces
                if panels:
                    panels = panels.replace(' ', '')
                return (figure_num, panels)

        return None
    
    def validate_figure_order(self, references: List[Tuple[str, int, str, int, str]]) -> List[Dict[str, Any]]:
        """
        Validate that figure references appear in logical order.
        
        Args:
            references: List of figure references from extract_figure_references
            
        Returns:
            List of order violations with details
        """
        violations = []
        
        # Track first occurrence of each figure
        first_occurrences = {}
        figure_order = []
        
        for ref_text, fig_num, panels, line_num, context in references:
            # Skip LaTeX references for now (they use labels not numbers)
            if '\\ref{' in str(fig_num):
                continue
                
            # Track first occurrence
            if fig_num not in first_occurrences:
                first_occurrences[fig_num] = {
                    'line': line_num,
                    'text': ref_text,
                    'context': context
                }
                figure_order.append(fig_num)
        
        # Check if main figures are in order
        main_figures = [f for f in figure_order if not f.startswith('S')]
        supplemental_figures = [f for f in figure_order if f.startswith('S')]
        
        # Check main figure ordering
        for i in range(1, len(main_figures)):
            try:
                curr_num = int(main_figures[i])
                prev_num = int(main_figures[i-1])
                
                if curr_num < prev_num:
                    violations.append({
                        'type': 'out_of_order',
                        'figure': main_figures[i],
                        'expected_after': main_figures[i-1],
                        'line': first_occurrences[main_figures[i]]['line'],
                        'context': first_occurrences[main_figures[i]]['context'],
                        'message': f"Figure {curr_num} appears after Figure {prev_num}"
                    })
            except ValueError:
                # Skip if not a simple number
                pass
        
        # Check supplemental figure ordering
        for i in range(1, len(supplemental_figures)):
            try:
                curr_num = int(supplemental_figures[i][1:])  # Remove 'S' prefix
                prev_num = int(supplemental_figures[i-1][1:])
                
                if curr_num < prev_num:
                    violations.append({
                        'type': 'out_of_order',
                        'figure': supplemental_figures[i],
                        'expected_after': supplemental_figures[i-1],
                        'line': first_occurrences[supplemental_figures[i]]['line'],
                        'context': first_occurrences[supplemental_figures[i]]['context'],
                        'message': f"Figure {supplemental_figures[i]} appears after Figure {supplemental_figures[i-1]}"
                    })
            except (ValueError, IndexError):
                # Skip if not a simple number
                pass
        
        return violations

    def validate_panel_order(self, references: List[Tuple[str, int, str, int, str]]) -> List[Dict[str, Any]]:
        """
        Validate that figure panels appear in correct alphabetical order.

        Args:
            references: List of figure references from extract_figure_references

        Returns:
            List of panel order violations with details
        """
        violations = []

        # Track panels seen for each figure
        figure_panels = {}  # figure_num -> {panel -> (line, context)}

        for ref_text, fig_num, panels, line_num, context in references:
            # Skip LaTeX references with labels for now
            if '\\ref{' in str(fig_num):
                # For LaTeX refs, extract base figure name without 'fig:' prefix
                if fig_num.startswith('fig:'):
                    fig_num = fig_num[4:]

            # Skip if no panels
            if not panels:
                continue

            # Initialize tracking for this figure if needed
            if fig_num not in figure_panels:
                figure_panels[fig_num] = {}

            # Handle multi-panel references (e.g., "B-D")
            if '-' in panels:
                # Extract range (e.g., "B-D" -> ['B', 'C', 'D'])
                start_panel = panels[0]
                end_panel = panels[2] if len(panels) >= 3 else panels[0]
                for p in range(ord(start_panel), ord(end_panel) + 1):
                    panel = chr(p)
                    if panel not in figure_panels[fig_num]:
                        figure_panels[fig_num][panel] = (line_num, context)
            else:
                # Single panel or comma-separated panels
                panel_list = panels.split(',') if ',' in panels else [panels]
                for panel in panel_list:
                    panel = panel.strip()
                    if panel and panel not in figure_panels[fig_num]:
                        figure_panels[fig_num][panel] = (line_num, context)

        # Check each figure for panel order violations
        for fig_num, panels_dict in figure_panels.items():
            if not panels_dict:
                continue

            # Get sorted list of panels that were referenced
            panels_seen = sorted(panels_dict.keys())

            # Check if first panel is not 'A'
            if panels_seen and panels_seen[0] != 'A':
                first_panel = panels_seen[0]
                line_num, context = panels_dict[first_panel]
                violations.append({
                    'type': 'missing_panel_A',
                    'figure': fig_num,
                    'first_panel': first_panel,
                    'line': line_num,
                    'context': context,
                    'message': f"Figure {fig_num} starts with panel {first_panel}, but panel A was never referenced"
                })

            # Check for gaps in panel sequence
            if len(panels_seen) > 1:
                expected_panels = [chr(ord('A') + i) for i in range(ord(panels_seen[-1]) - ord('A') + 1)]
                missing_panels = [p for p in expected_panels if p not in panels_seen]

                if missing_panels:
                    # Find the first referenced panel after the gap
                    for missing in missing_panels:
                        # Find panels that come after the missing one
                        later_panels = [p for p in panels_seen if p > missing]
                        if later_panels:
                            first_later = later_panels[0]
                            line_num, context = panels_dict[first_later]
                            violations.append({
                                'type': 'missing_panel',
                                'figure': fig_num,
                                'missing_panel': missing,
                                'referenced_panel': first_later,
                                'line': line_num,
                                'context': context,
                                'message': f"Figure {fig_num} panel {first_later} referenced, but panel {missing} was never referenced"
                            })

            # Check if panels appear in order by line number
            panel_order_by_line = sorted(panels_dict.items(), key=lambda x: x[1][0])
            prev_panel = None
            for panel, (line_num, context) in panel_order_by_line:
                if prev_panel and panel < prev_panel:
                    violations.append({
                        'type': 'panel_out_of_order',
                        'figure': fig_num,
                        'panel': panel,
                        'expected_after': prev_panel,
                        'line': line_num,
                        'context': context,
                        'message': f"Figure {fig_num} panel {panel} appears before panel {prev_panel}"
                    })
                prev_panel = panel

        return violations

    def detect_figure_warnings(self, references: List[Tuple[str, int, str, int, str]]) -> List[Dict[str, Any]]:
        """
        Detect potential issues with figure references.
        
        Args:
            references: List of figure references
            
        Returns:
            List of warnings with details
        """
        warnings = []
        
        # Check for non-parenthetic references that might need parentheses
        for ref_text, fig_num, panels, line_num, context in references:
            # Skip if it's in a figure caption (starts with **)
            if context.startswith('**'):
                continue
                
            # Warning for references not in parentheses (unless in specific contexts)
            if not ref_text.startswith('('):
                # Check if the reference text itself contains acceptable context phrases
                # These are typically part of the match when using our combined pattern
                acceptable_starts = [
                    'as shown in',
                    'see fig',
                    'shown in fig',
                    'described in fig',
                    'illustrated in fig'
                ]
                
                ref_lower = ref_text.lower()
                if not any(ref_lower.startswith(ctx) for ctx in acceptable_starts):
                    # For standalone "Figure X" references, check context
                    if ref_lower.startswith('fig'):
                        # This is a standalone figure reference - warn about it
                        warnings.append({
                            'type': 'no_parentheses',
                            'figure': fig_num,
                            'line': line_num,
                            'text': ref_text,
                            'context': context,
                            'message': f"Figure reference '{ref_text}' is not in parentheses"
                        })
        
        return warnings
    
    def generate_figure_analysis_report(self, markdown_content: str) -> str:
        """
        Generate a comprehensive figure reference analysis report.

        Args:
            markdown_content: The markdown content to analyze

        Returns:
            Formatted report string
        """
        # Extract references
        references = self.extract_figure_references(markdown_content)

        if not references:
            return ""

        # Validate figure order
        figure_violations = self.validate_figure_order(references)

        # Validate panel order
        panel_violations = self.validate_panel_order(references)

        # Detect warnings
        warnings = self.detect_figure_warnings(references)

        # Check for prefix consistency
        prefix_warnings = self.check_prefix_consistency(references)

        # Build report
        report_lines = []

        # Summary
        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("📊 FIGURE REFERENCE ANALYSIS")
        report_lines.append("=" * 70)
        report_lines.append("")
        report_lines.append(f"Total figure references found: {len(references)}")

        # Count unique figures (including all panels)
        unique_figures = set()
        unique_figure_bases = set()  # Just the figure numbers without panels
        for _, fig_num, panels, _, _ in references:
            if not '\\ref{' in str(fig_num):
                # Add the full figure+panel combination
                if panels:
                    unique_figures.add(f"{fig_num}{panels}")
                else:
                    unique_figures.add(fig_num)
                # Also track just the base figure number
                unique_figure_bases.add(fig_num)

        report_lines.append(f"Unique figures referenced: {len(unique_figure_bases)}")
        report_lines.append("")

        # List first occurrences - SORTED BY LINE NUMBER
        first_occurrences = {}
        for ref_text, fig_num, panels, line_num, context in references:
            # Create a unique key for each figure+panel combination
            if panels:
                key = f"{fig_num}_{panels}"
                display_text = f"Fig. {fig_num}{panels}"  # Normalized display
            else:
                key = fig_num
                display_text = f"Fig. {fig_num}"  # Normalized display

            if key not in first_occurrences:
                first_occurrences[key] = {
                    'line': line_num,
                    'text': display_text,  # Use normalized text for cleaner display
                    'panels': panels,
                    'fig_num': fig_num,
                    'original_text': ref_text  # Keep original for reference
                }

        if first_occurrences:
            report_lines.append("First occurrence of each figure (ordered by appearance):")
            # Sort by line number (order of appearance)
            for key in sorted(first_occurrences.keys(),
                            key=lambda x: first_occurrences[x]['line']):
                info = first_occurrences[key]
                # No need for panel_info since it's in the normalized text
                report_lines.append(f"  Line {info['line']:4d}: {info['text']}")
            report_lines.append("")

        # Report figure order violations
        if figure_violations:
            report_lines.append("⚠️  FIGURE ORDER VIOLATIONS:")
            report_lines.append("")
            for violation in figure_violations:
                report_lines.append(f"  - {violation['message']}")
                report_lines.append(f"    Line {violation['line']}: {violation['context']}")
                report_lines.append("")

        # Report panel order violations
        if panel_violations:
            report_lines.append("❌ PANEL ORDER VIOLATIONS:")
            report_lines.append("")
            for violation in panel_violations:
                report_lines.append(f"  - {violation['message']}")
                if violation['line'] > 0:  # Some violations may not have a specific line
                    report_lines.append(f"    Line {violation['line']}: {violation['context']}")
                report_lines.append("")

        # Report prefix consistency warnings
        if prefix_warnings:
            report_lines.append("⚠️  FIGURE PREFIX INCONSISTENCIES:")
            report_lines.append("")
            for warning in prefix_warnings:
                report_lines.append(f"  - {warning['message']}")
                if warning['line'] > 0:
                    report_lines.append(f"    Line {warning['line']}: {warning['context']}")
                report_lines.append("")

        # Report other warnings
        if warnings:
            report_lines.append("⚠️  FIGURE REFERENCE WARNINGS:")
            report_lines.append("")
            for warning in warnings:
                report_lines.append(f"  - {warning['message']}")
                report_lines.append(f"    Line {warning['line']}: {warning['context']}")
                report_lines.append("")

        if not figure_violations and not panel_violations and not warnings and not prefix_warnings:
            report_lines.append("✅ All figure references appear to be in order!")
            report_lines.append("")

        report_lines.append("=" * 70)
        report_lines.append("")

        return '\n'.join(report_lines)
    
    def check_prefix_consistency(self, references: List[Tuple[str, int, str, int, str]]) -> List[Dict[str, Any]]:
        """
        Check for inconsistent use of "Fig." vs "Figure" prefixes.
        
        Args:
            references: List of figure references
            
        Returns:
            List of warnings about prefix inconsistencies
        """
        warnings = []
        
        # Count the usage of different prefixes
        prefix_counts = {
            'Fig.': 0,
            'Figure': 0,
            'Fig': 0  # Without period
        }
        
        prefix_examples = {
            'Fig.': [],
            'Figure': [],
            'Fig': []
        }
        
        for ref_text, fig_num, panels, line_num, context in references:
            # Skip LaTeX references as they might have different patterns
            if '\\ref{' in ref_text:
                continue
                
            # Determine which prefix is used
            ref_lower = ref_text.lower()
            if 'fig.' in ref_lower:
                prefix_counts['Fig.'] += 1
                prefix_examples['Fig.'].append((ref_text, line_num, context))
            elif 'figure' in ref_lower:
                prefix_counts['Figure'] += 1
                prefix_examples['Figure'].append((ref_text, line_num, context))
            elif 'fig' in ref_lower:
                prefix_counts['Fig'] += 1
                prefix_examples['Fig'].append((ref_text, line_num, context))
        
        # Determine the dominant prefix
        total_refs = sum(prefix_counts.values())
        if total_refs == 0:
            return warnings
            
        dominant_prefix = max(prefix_counts, key=prefix_counts.get)
        dominant_count = prefix_counts[dominant_prefix]
        
        # If one prefix is used >80% of the time, warn about the minority uses
        if dominant_count > 0.8 * total_refs:
            for prefix, count in prefix_counts.items():
                if prefix != dominant_prefix and count > 0:
                    # Add warnings for the minority prefix usage
                    for ref_text, line_num, context in prefix_examples[prefix][:3]:  # Show first 3 examples
                        warnings.append({
                            'type': 'prefix_inconsistency',
                            'prefix': prefix,
                            'dominant_prefix': dominant_prefix,
                            'line': line_num,
                            'text': ref_text,
                            'context': context,
                            'message': f"Inconsistent prefix: '{prefix}' used here, but '{dominant_prefix}' is used in {dominant_count}/{total_refs} references"
                        })
                    
                    # If there are more than 3, add a summary
                    if len(prefix_examples[prefix]) > 3:
                        remaining = len(prefix_examples[prefix]) - 3
                        warnings.append({
                            'type': 'prefix_inconsistency_summary',
                            'prefix': prefix,
                            'dominant_prefix': dominant_prefix,
                            'line': 0,
                            'text': '',
                            'context': '',
                            'message': f"... and {remaining} more instances of '{prefix}' instead of '{dominant_prefix}'"
                        })
        
        return warnings