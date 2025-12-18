"""Utility functions for the markmeld package.

This module contains helper functions for:
- Configuration file loading and processing
- Command formatting and execution
- File operations and path handling
- Markdown content cleaning and processing
- Plugin loading and management
"""

import glob
import os
import platform
import re
import subprocess
import yaml
from collections.abc import Mapping
from logging import getLogger
from pathlib import Path
from string import Template as StringTemplate
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ubiquerg import expandpath

from .const import PKG_NAME, FILE_OPENER_MAP
from .glob_factory import glob_factory



_LOGGER = getLogger(PKG_NAME)

# ====================
# Configuration and Command Processing
# ====================

class MyTemplate(StringTemplate):
    """Custom string template for command variable substitution.

    This class modifies the standard string.Template to:
    - Use an empty delimiter (no $ prefix required)
    - Only replace variables surrounded by braces {variable}
    - Leave undefined variables as-is (no errors on missing variables)

    This allows commands to contain braces without errors if the variable
    is not found in the substitution dictionary. Useful for commands with
    shell expressions or other brace-delimited content.

    Attributes:
        delimiter: Empty string (no prefix required).
        idpattern: Disabled (None).
        braceidpattern: Pattern allowing alphanumeric chars and hyphens.

    Example:
        >>> template = MyTemplate("echo {name} > {output_file}")
        >>> template.safe_substitute(name="test", output_file="out.txt")
        'echo test > out.txt'

        >>> template = MyTemplate("if [[ {check} ]]; then echo {undefined}; fi")
        >>> template.safe_substitute(check="true")
        'if [[ true ]]; then echo {undefined}; fi'  # {undefined} is preserved
    """

    delimiter = ""
    idpattern = None
    # braceidpattern = r"[_a-z][_a-z0-9]*"
    braceidpattern = r"[_a-z0-9-][_a-z0-9-]*"  # allow hyphens.
    # braceidpattern = r"[_a-z][_a-z0-9]*(?:\.[_a-z][_a-z0-9]*)*"  # allows dots, to enable nested variable names


def format_command(tgt: Any) -> str:
    """Format a command string by substituting variables from target metadata.

    Performs recursive variable substitution (up to 5 iterations), allowing
    variables to contain other variables. Uses MyTemplate for safe substitution
    that preserves undefined variables.

    Args:
        tgt: Target object with metadata containing 'command' and variables.

    Returns:
        The formatted command with all available variables substituted.
    """
    cmd = tgt.meta["command"]
    if "output_file" in tgt.meta and tgt.meta["output_file"]:
        tgt.meta["output_file"] = expandpath(tgt.meta["output_file"]).format(**tgt.meta)
    else:
        tgt.meta["output_file"] = None

    # Add in custom command keys for all embedded resources
    # (Note: These should already be injected during Target initialization,
    # but we ensure they're present here for backward compatibility)
    from .resource_manager import inject_resource_variables
    tgt.meta = inject_resource_variables(tgt.meta)

    # Recursively expand variables (up to 5 iterations to prevent infinite loops)
    # This allows for variables to contain variables
    cmd = MyTemplate(expandpath(cmd)).safe_substitute(**tgt.meta)
    _LOGGER.debug(f"Expanded command: {cmd}")
    count = 1
    while True and count < 5:
        cmd_new = MyTemplate(expandpath(cmd)).safe_substitute(**tgt.meta)
        _LOGGER.debug(f"Expanded command: {cmd_new}")
        if cmd == cmd_new:
            _LOGGER.debug("No more variables to expand")
            break
        cmd = cmd_new
        count += 1
    return cmd


def run_cmd(
    cmd: str, stdin: Optional[bytes] = None, workdir: Optional[str] = None
) -> Tuple[int, str, str]:
    """Run a shell command with optional stdin and working directory.

    Args:
        cmd: Shell command to execute.
        stdin: Optional bytes to pass to command's stdin.
        workdir: Working directory for command execution. If a file path,
            uses its parent directory.

    Returns:
        Tuple of (returncode, stdout, stderr) where stdout and stderr are strings.
    """
    _LOGGER.info(f"MM | Command: {cmd}; CWD: {workdir}")

    # Determine the actual working directory
    if workdir:
        if os.path.isdir(workdir):
            # If workdir is already a directory, use it directly
            cwd = workdir
        else:
            # If workdir is a file path, get its directory
            cwd = os.path.dirname(workdir)
    else:
        cwd = None

    _LOGGER.debug(f"MM | Actual CWD: {cwd}")

    if stdin:
        # Call command (default: pandoc), passing the rendered template to stdin
        p = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd
        )
        stdout, stderr = p.communicate(input=stdin)
        return p.returncode, stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace')
    else:
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=cwd)
        stdout, stderr = p.communicate()
        return p.returncode, stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace')


# ====================
# Configuration File Loading
# ====================

def recursive_get(dat: Dict[str, Any], indices: List[str]) -> Optional[Any]:
    """Index into a nested dictionary using a list of keys.

    Args:
        dat: Nested dictionary to traverse.
        indices: List of keys to follow into the nested structure.

    Returns:
        Value at the nested location, or None if any key is not found.
    """
    for i in indices:
        if i not in dat:
            return None
        dat = dat[i]
    return dat


def load_config_wrapper(
    cfg_path: str, workpath: Optional[str] = None, autocomplete: bool = True
) -> Dict[str, Any]:
    """Load a configuration file with import tracking to prevent duplicates.

    Wrapper function that initializes import tracking before loading.

    Args:
        cfg_path: Path to the configuration file.
        workpath: Working path for resolving relative paths.
        autocomplete: If True, suppresses some logging output.

    Returns:
        Loaded configuration dictionary.
    """
    imported_list: Dict[str, bool] = {}
    return load_config_file(cfg_path, workpath, autocomplete, imported_list)


def load_config_file(
    filepath: str,
    workpath: Optional[str] = None,
    autocomplete: bool = True,
    imported_list: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        filepath: Path to the configuration file.
        workpath: Working path for resolving relative paths in targets.
        autocomplete: If True, suppresses some logging output.
        imported_list: Dictionary tracking already-imported files to prevent duplicates.

    Returns:
        Loaded configuration dictionary, or empty dict if file not found.

    Raises:
        Exception: If file exists but cannot be parsed (non-FileNotFoundError).
    """
    if imported_list is None:
        imported_list = {}
    _LOGGER.debug(f"Loading config file: {filepath}")
    _LOGGER.debug(f"Imported list: {imported_list}")
    if imported_list.get(filepath):
        _LOGGER.debug(f"Already imported: {filepath}")
        return {}
    try:
        with open(filepath, "r") as f:
            cfg_data = f.read()
        return load_config_data(
            cfg_data, os.path.abspath(filepath), workpath, autocomplete, imported_list
        )
    except FileNotFoundError as e:
        _LOGGER.error(f"Couldn't load config file: {filepath} because: {repr(e)}")
        return {}  # Allow continuing if file not found
    except Exception as e:
        _LOGGER.error(f"Couldn't load config file: {filepath} because: {repr(e)}")
        raise e  # Fail on other errors


def make_abspath(relpath: str, filepath: str, root: Optional[str] = None) -> str:
    """Convert a relative path to an absolute path.

    Args:
        relpath: Relative path to convert.
        filepath: Reference file or directory path for resolution.
        root: If provided, joins relpath directly to this root instead.

    Returns:
        Absolute path.
    """
    if root:
        return os.path.join(root, relpath)

    # Handle both directory paths and file paths
    if os.path.isdir(filepath):
        base_path = filepath
    else:
        base_path = os.path.dirname(filepath)

    return os.path.abspath(os.path.join(base_path, relpath))


def load_config_data(
    cfg_data: str,
    filepath: Optional[str] = None,
    workpath: Optional[str] = None,
    autocomplete: bool = True,
    imported_list: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Parse YAML config data, process imports, and run target factories.

    Args:
        cfg_data: Raw YAML configuration string.
        filepath: Path of the config file (for resolving relative imports).
        workpath: Working path for target relative paths.
        autocomplete: If True, suppresses some logging output.
        imported_list: Dictionary tracking already-imported files.

    Returns:
        Processed configuration dictionary with merged imports and factory targets.
    """
    if imported_list is None:
        imported_list = {}
    higher_cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    higher_cfg["_cfg_file_path"] = filepath
    lower_cfg = {}

    _LOGGER.debug(f"Loading config data filepath: {filepath}; workpath: {workpath}")

    # Add filepath to targets defined in the current cfg file
    if "targets" in higher_cfg:
        for tgt in higher_cfg["targets"]:
            higher_cfg["targets"][tgt]["_defpath"] = filepath
            if workpath:
                higher_cfg["targets"][tgt]["_workpath"] = workpath
            else:
                higher_cfg["targets"][tgt]["_workpath"] = os.path.dirname(filepath)

    # Imports
    if "imports" in higher_cfg and higher_cfg["imports"]:
        _LOGGER.debug("Found imports")
        for import_file in higher_cfg["imports"]:
            import_file_abspath = make_abspath(
                expandpath(import_file), expandpath(filepath)
            )
            if not autocomplete:
                _LOGGER.info(f"Specified config file to import: {import_file_abspath}")
            deep_update(
                lower_cfg,
                load_config_file(import_file_abspath, os.path.dirname(expandpath(filepath))),
                warn_override=not autocomplete,
            )
            imported_list[import_file_abspath] = True

    if "imports_relative" in higher_cfg and higher_cfg["imports_relative"]:
        _LOGGER.debug("Found relative imports")
        for import_file in higher_cfg["imports_relative"]:
            import_file_abspath = make_abspath(
                expandpath(import_file), expandpath(filepath)
            )
            if not autocomplete:
                _LOGGER.info(
                    f"Specified relative config file to import (relative): {import_file}"
                )
            deep_update(
                lower_cfg,
                load_config_file(expandpath(import_file_abspath)),
                warn_override=not autocomplete,
            )
            imported_list[import_file_abspath] = True

    deep_update(lower_cfg, higher_cfg, warn_override=not autocomplete)

    # Target factories
    if "target_factories" in lower_cfg:
        factories = load_target_factories()
        _LOGGER.debug(f"Available target factories: {factories}")
        for fac in lower_cfg["target_factories"]:
            fac_name = list(fac.keys())[0]
            fac_vals = list(fac.values())[0]
            _LOGGER.debug(f"Processing target factory: {fac_name}")
            # Look up function to call.
            func = factories[fac_name]
            factory_targets = func(fac_vals, lower_cfg)
            for k, v in factory_targets.items():
                factory_targets[k]["_workpath"] = os.path.dirname(filepath)
                factory_targets[k]["_defpath"] = filepath
            deep_update(
                lower_cfg, {"targets": factory_targets}, warn_override=not autocomplete
            )

    # _LOGGER.debug("Lower cfg: " + str(lower_cfg))
    return lower_cfg


def warn_overriding_target(old: Dict[str, Any], new: Dict[str, Any]) -> None:
    """Check for and raise error on target name conflicts.

    Args:
        old: Existing configuration dictionary.
        new: New configuration dictionary being merged.

    Raises:
        Exception: If a target in new already exists in old.
    """
    if "targets" in old and "targets" in new:
        for tgt in new["targets"]:
            if tgt in old["targets"]:
                _LOGGER.error(f"Overriding target: {tgt}")
                _LOGGER.error(
                    "Originally defined in: ".rjust(27, " ")
                    + f"{old['targets'][tgt]['_defpath']}"
                )
                _LOGGER.error(
                    "Redefined in: ".rjust(27, " ")
                    + f"{new['targets'][tgt]['_defpath']}"
                )
                raise Exception(
                    "Same target name is defined in imported file. Overriding targets is not allowed."
                )


def deep_update(
    old: Dict[str, Any], new: Dict[str, Any], warn_override: bool = True
) -> Dict[str, Any]:
    """Recursively update a dictionary with another dictionary.

    Like built-in dict.update(), but merges nested dictionaries instead
    of replacing them entirely.

    Args:
        old: Dictionary to update (modified in place).
        new: Dictionary with values to merge in.
        warn_override: If True, check for and warn about target conflicts.

    Returns:
        The updated old dictionary.
    """
    if warn_override:
        warn_overriding_target(old, new)
    for k, v in new.items():
        if isinstance(v, Mapping):
            old[k] = deep_update(old.get(k, {}), v)
        else:
            old[k] = v
    return old


# ====================
# Target Factory Loading
# ====================

def load_target_factories() -> Dict[str, Callable]:
    """Load target factories from entry points.

    Discovers target factories registered under the 'markmeld.factories' entry point
    group and combines them with built-in factories.

    Returns:
        Dictionary mapping factory names to their factory functions.
    """
    try:
        # Python 3.10+ has importlib.metadata in stdlib
        from importlib.metadata import entry_points
    except ImportError:
        # Fallback for Python 3.8-3.9
        from importlib_metadata import entry_points

    built_in_factories: Dict[str, Callable] = {"glob": glob_factory}

    # Get entry points for markmeld.factories
    try:
        # Python 3.10+ returns SelectableGroups
        eps = entry_points(group="markmeld.factories")
    except TypeError:
        # Python 3.8-3.9 compatibility
        eps = entry_points().get("markmeld.factories", [])

    installed_factories = {ep.name: ep.load() for ep in eps}
    built_in_factories.update(installed_factories)
    return built_in_factories


# ====================
# File and Path Operations
# ====================

def globs_to_dict(globs: Optional[List[str]], cfg_path: str) -> Dict[str, str]:
    """Resolve glob patterns to a dictionary of file names to paths.

    Args:
        globs: List of glob patterns to resolve.
        cfg_path: Path to configuration file or directory for resolving
            relative patterns.

    Returns:
        Dictionary mapping base file names (without extension) to absolute paths.
    """
    return_items: Dict[str, str] = {}
    if not globs:
        return return_items

    # Handle both directory paths and file paths
    if os.path.isdir(cfg_path):
        base_path = cfg_path
    else:
        base_path = os.path.dirname(cfg_path)

    for item in globs:
        path = os.path.join(base_path, item)
        _LOGGER.info(f"MM | Glob path: {path}")
        files = glob.glob(path)
        for file in files:
            k = os.path.splitext(os.path.basename(file))[0]
            _LOGGER.info(f"MM | [key:value] {k}:{file}")
            return_items[k] = file
    return return_items


def get_file_open_cmd() -> str:
    """Get the platform-appropriate command for opening files.

    Returns:
        Name of the executable: 'open' on macOS, 'start' on Windows,
        'xdg-open' on Linux/other.
    """
    system = platform.system()
    return FILE_OPENER_MAP.get(system, "xdg-open")


def write_to_file(content: str, output_path: Union[str, Path]) -> None:
    """Write content to a file, creating parent directories as needed.

    Args:
        content: String content to write.
        output_path: Destination file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


# ====================
# Markdown Processing Functions
# ====================

def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by removing or replacing invalid characters.

    Handles Windows-incompatible characters, trailing dots/spaces, and
    enforces a maximum length of 255 characters.

    Args:
        filename: Original filename to sanitize.

    Returns:
        Sanitized filename safe for use on all platforms.
    """
    # Remove invalid characters for filenames
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove trailing dots and spaces (Windows compatibility)
    name_parts = filename.rsplit('.', 1)
    if len(name_parts) == 2:
        name, ext = name_parts
        name = name.rstrip('. ')
        filename = f"{name}.{ext}" if name else f"file.{ext}"
    else:
        filename = filename.rstrip('. ')
    
    # Limit length to 255 characters
    if len(filename) > 255:
        name_parts = filename.rsplit('.', 1)
        if len(name_parts) == 2:
            name, ext = name_parts
            if len(name) > 251:
                filename = f"{name[:251]}.{ext}"
        else:
            filename = filename[:251]
    
    return filename


def clean_markdown(
    markdown_content: str,
    clean_escapes: bool = True,
    remove_images: bool = True,
    strip_heading_bold: bool = True,
    replace_svg_with_pdf: bool = False,
    fix_latex_chars: bool = True,
) -> str:
    """Apply cleaning operations to markdown content.

    Primarily used to clean Google Docs exports for LaTeX processing.

    Args:
        markdown_content: Raw markdown content to clean.
        clean_escapes: Remove escape characters from markdown elements.
        remove_images: Remove embedded images and data URIs.
        strip_heading_bold: Remove bold formatting from headings.
        replace_svg_with_pdf: Replace .svg extensions with .pdf in images.
        fix_latex_chars: Replace Unicode characters incompatible with LaTeX.

    Returns:
        Cleaned markdown content.
    """
    if clean_escapes:
        markdown_content = clean_escape_characters(markdown_content)
    
    if remove_images:
        markdown_content = remove_embedded_images(markdown_content)
    
    if strip_heading_bold:
        markdown_content = strip_bold_from_headings(markdown_content)
    
    if replace_svg_with_pdf:
        markdown_content = replace_svg_extensions(markdown_content)
    
    if fix_latex_chars:
        markdown_content = check_and_fix_latex_incompatible_chars(markdown_content)
    
    return markdown_content


def clean_escape_characters(markdown_content: str) -> str:
    """Remove escape characters from markdown elements.

    Used to clean Google Docs exports which over-escape markdown syntax.
    Preserves LaTeX escape sequences.

    Args:
        markdown_content: Markdown content with escaped characters.

    Returns:
        Content with markdown escapes removed but LaTeX escapes preserved.
    """
    content = markdown_content
    
    # Remove escapes from various markdown characters (but NOT LaTeX ones)
    content = content.replace('\\[', '[')
    content = content.replace('\\]', ']')
    content = content.replace('\\_', '_')
    content = content.replace('\\!', '!')
    content = content.replace('\\(', '(')
    content = content.replace('\\)', ')')
    content = content.replace('\\`', '`')
    content = content.replace('\\-', '-')
    content = content.replace('\\*', '*')
    content = content.replace('\\=', '=')
    content = content.replace('\\+', '+')
    content = content.replace('\\<', '<')
    content = content.replace('\\>', '>')
    
    # Handle LaTeX-specific fixes: convert double backslashes before LaTeX commands to single
    # This fixes Google Docs converting \{ to \\{ while preserving the LaTeX command
    content = re.sub(r'\\\\([{}\\])', r'\\\1', content)
    
    # Handle other LaTeX commands: convert \\alpha to \alpha, etc.
    content = re.sub(r'\\\\([a-zA-Z]+)', r'\\\1', content)
    
    # Finally, clean up any remaining double backslashes that aren't LaTeX commands
    content = re.sub(r'\\\\(?![{}\\a-zA-Z])', r'\\', content)

    return content


def remove_embedded_images(markdown_content: str) -> str:
    """Remove embedded images and image references from markdown.

    Removes reference-style image definitions, inline data URI images,
    and markdown image references. Used to clean Google Docs exports.

    Args:
        markdown_content: Markdown content potentially containing images.

    Returns:
        Content with embedded images removed and blank lines cleaned up.
    """
    # Remove reference-style image definitions with data URIs (both with and without angle brackets)
    content = re.sub(r'^\[[^\]]+\]:\s*<?data:[^>\n]*>?\s*$', '', markdown_content, flags=re.MULTILINE)
    
    # Remove markdown image references (both ![][imageX] and ![alt][imageX])
    content = re.sub(r'!\[[^\]]*\]\[[^\]]+\]', '', content)
    
    # Remove inline data URI images
    content = re.sub(r'!\[[^\]]*\]\(data:[^)]+\)', '', content)
    
    # Clean up extra blank lines
    content = re.sub(r'\n\n+', '\n\n', content)
    
    return content.strip()


def strip_bold_from_headings(markdown_content: str) -> str:
    """Remove bold formatting from markdown headings.

    Used to clean Google Docs exports which often wrap heading text in bold.

    Args:
        markdown_content: Markdown content with potentially bold headings.

    Returns:
        Content with bold markers removed from heading lines.
    """
    # Pattern matches heading lines with bold markers
    content = re.sub(r'^(#+)\s+\*\*(.*?)\*\*\s*$', r'\1 \2', markdown_content, flags=re.MULTILINE)
    
    # Also handle cases where there might be bold within the heading
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('#'):
            line = line.replace('**', '')
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


def replace_svg_extensions(markdown_content: str) -> str:
    """Replace .svg extensions with .pdf in markdown image syntax.

    Used when SVG images need to be converted to PDF for LaTeX processing.

    Args:
        markdown_content: Markdown content with image references.

    Returns:
        Content with .svg image extensions replaced by .pdf.
    """
    # Pattern to match markdown images with .svg extension
    pattern = r'!\[([^\]]*)\]\(([^)]+?)(\.svg)\)'
    
    # Replace .svg with .pdf
    content = re.sub(pattern, r'![\1](\2.pdf)', markdown_content)
    
    return content


def check_and_fix_latex_incompatible_chars(markdown_content: str) -> str:
    """Check for and fix Unicode characters incompatible with LaTeX.

    Detects characters that cause "inputenc Error: Unicode character not set up
    for use with LaTeX" errors and replaces them with LaTeX-compatible
    alternatives. Also warns about other non-ASCII characters.

    Args:
        markdown_content: Markdown content to check and fix.

    Returns:
        Content with problematic Unicode characters replaced.
    """
    # Dictionary of problematic Unicode characters and their LaTeX-safe replacements
    # Add more as we discover them
    char_replacements = {
        '∼': '~',           # U+223C TILDE OPERATOR → regular tilde
        '−': '-',           # U+2212 MINUS SIGN → hyphen-minus
        ''': "'",           # U+2019 RIGHT SINGLE QUOTATION MARK → apostrophe
        ''': "'",           # U+2018 LEFT SINGLE QUOTATION MARK → apostrophe
        '\u201C': '"',           # U+201C LEFT DOUBLE QUOTATION MARK → quotation mark
        '\u201D': '"',           # U+201D RIGHT DOUBLE QUOTATION MARK → quotation mark
        '…': '...',         # U+2026 HORIZONTAL ELLIPSIS → three dots
        '–': '--',          # U+2013 EN DASH → double hyphen
        '—': '---',         # U+2014 EM DASH → triple hyphen
        '\u00A0': ' ',           # U+00A0 NO-BREAK SPACE → regular space
        '​': '',            # U+200B ZERO WIDTH SPACE → remove
        '‐': '-',           # U+2010 HYPHEN → hyphen-minus
        '×': 'x',           # U+00D7 MULTIPLICATION SIGN → letter x
        '÷': '/',           # U+00F7 DIVISION SIGN → forward slash
        '≈': '~',           # U+2248 ALMOST EQUAL TO → tilde
        '≠': '!=',          # U+2260 NOT EQUAL TO → != 
        '≤': '<=',          # U+2264 LESS-THAN OR EQUAL TO → <=
        '≥': '>=',          # U+2265 GREATER-THAN OR EQUAL TO → >=
        '±': '+/-',         # U+00B1 PLUS-MINUS SIGN → +/-
        '°': '$^\\circ$',   # U+00B0 DEGREE SIGN → LaTeX degree symbol
        'µ': '$\\mu$',      # U+00B5 MICRO SIGN → LaTeX mu
        '∞': '$\\infty$',   # U+221E INFINITY → LaTeX infinity
        '√': '$\\sqrt{}$',  # U+221A SQUARE ROOT → LaTeX square root
        '∑': '$\\sum$',     # U+2211 N-ARY SUMMATION → LaTeX sum
        '∏': '$\\prod$',    # U+220F N-ARY PRODUCT → LaTeX product
        '∫': '$\\int$',     # U+222B INTEGRAL → LaTeX integral
        'α': '$\\alpha$',   # U+03B1 GREEK SMALL LETTER ALPHA
        'β': '$\\beta$',    # U+03B2 GREEK SMALL LETTER BETA
        'γ': '$\\gamma$',   # U+03B3 GREEK SMALL LETTER GAMMA
        'δ': '$\\delta$',   # U+03B4 GREEK SMALL LETTER DELTA
        'ε': '$\\epsilon$', # U+03B5 GREEK SMALL LETTER EPSILON
        'θ': '$\\theta$',   # U+03B8 GREEK SMALL LETTER THETA
        'λ': '$\\lambda$',  # U+03BB GREEK SMALL LETTER LAMBDA
        'π': '$\\pi$',      # U+03C0 GREEK SMALL LETTER PI
        'σ': '$\\sigma$',   # U+03C3 GREEK SMALL LETTER SIGMA
        'φ': '$\\phi$',     # U+03C6 GREEK SMALL LETTER PHI
    }
    
    # Track what we find and fix
    issues_found = []
    content = markdown_content
    
    for char, replacement in char_replacements.items():
        if char in content:
            # Find context around each occurrence
            import re
            pattern = re.compile(re.escape(char))
            matches = list(pattern.finditer(content))
            
            if matches:
                # Log each occurrence with context
                for match in matches:
                    start = max(0, match.start() - 20)
                    end = min(len(content), match.end() + 20)
                    context = content[start:end]
                    # Clean up context for display (remove newlines)
                    context = context.replace('\n', ' ')
                    
                    char_code = f"U+{ord(char):04X}"
                    issues_found.append({
                        'char': char,
                        'char_code': char_code,
                        'replacement': replacement,
                        'context': f"...{context}...",
                        'position': match.start()
                    })
                
                # Replace all occurrences
                content = content.replace(char, replacement)
    
    # Log warnings if any problematic characters were found
    if issues_found:
        _LOGGER.warning("⚠️  LaTeX-incompatible characters detected and auto-replaced:")

        # Group by character for cleaner output
        char_groups = {}
        for issue in issues_found:
            char_key = (issue['char'], issue['char_code'], issue['replacement'])
            if char_key not in char_groups:
                char_groups[char_key] = []
            char_groups[char_key].append(issue['context'])

        for (char, char_code, replacement), contexts in char_groups.items():
            # Format as table: 'char' (code) → 'replacement'   N occ: context
            count = len(contexts)
            plural = "s" if count > 1 else ""
            # Take first context, truncate if too long
            context = contexts[0]
            if len(context) > 60:
                context = context[:57] + "..."
            _LOGGER.warning(f"  '{char}' ({char_code}) → '{replacement}'   {count} occurrence{plural}: {context}")

        _LOGGER.warning("Note: Review document to ensure replacements are appropriate.")
    
    # Also check for any other non-ASCII characters that might cause issues
    # but aren't in our replacement list
    remaining_non_ascii = []
    for i, char in enumerate(content):
        if ord(char) > 127 and char not in char_replacements:
            # Skip common accented characters that LaTeX handles well
            if ord(char) < 256:  # Latin-1 supplement, usually OK
                continue
            
            context_start = max(0, i - 20)
            context_end = min(len(content), i + 20)
            context = content[context_start:context_end].replace('\n', ' ')
            
            remaining_non_ascii.append({
                'char': char,
                'char_code': f"U+{ord(char):04X}",
                'context': f"...{context}...",
                'position': i
            })
    
    # Deduplicate remaining non-ASCII warnings
    if remaining_non_ascii:
        seen_chars = {}
        for item in remaining_non_ascii:
            char_key = (item['char'], item['char_code'])
            if char_key not in seen_chars:
                seen_chars[char_key] = []
            seen_chars[char_key].append(item['context'])
        
        if seen_chars:
            _LOGGER.warning("")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("⚠️  ADDITIONAL NON-ASCII CHARACTERS DETECTED")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("")
            _LOGGER.warning("The following non-ASCII characters were found that *might* cause")
            _LOGGER.warning("LaTeX issues (not automatically replaced):")
            _LOGGER.warning("")
            
            for (char, char_code), contexts in list(seen_chars.items())[:10]:  # Limit to 10
                _LOGGER.warning(f"  Character: '{char}' ({char_code})")
                _LOGGER.warning(f"  Example context: {contexts[0]}")
                if len(contexts) > 1:
                    _LOGGER.warning(f"  Found {len(contexts)} occurrence(s)")
                _LOGGER.warning("")
            
            if len(seen_chars) > 10:
                _LOGGER.warning(f"  ... and {len(seen_chars) - 10} more unique characters")
                _LOGGER.warning("")
            
            _LOGGER.warning("Consider reviewing these characters if you encounter LaTeX errors.")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("")

    return content


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