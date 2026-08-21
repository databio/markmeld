"""Utility functions for the markmeld package.

This module contains helper functions for:
- Configuration file loading and processing
- Command formatting and execution
- File operations and path handling
- Plugin loading and management
"""

import glob
import logging
import os
import platform
import subprocess
from collections.abc import Mapping
from pathlib import Path
from string import Template as StringTemplate
from typing import Any, Callable

import yaml
from ubiquerg import expandpath

from .const import FILE_OPENER_MAP
from .glob_factory import glob_factory

_LOGGER = logging.getLogger(__name__)

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


def expand_dict_templates(d: dict[str, Any], max_iterations: int = 3) -> dict[str, Any]:
    """Expand template variables in string values of a dictionary.

    Iterates over all string values containing '{', substituting template
    references from the dictionary itself. Repeats up to max_iterations
    times to resolve nested references.

    Args:
        d: Dictionary with string values that may contain {variable} references.
        max_iterations: Maximum expansion passes to handle nested references.

    Returns:
        The dictionary with template variables expanded in-place.
    """
    for key, value in list(d.items()):
        if isinstance(value, str) and "{" in value:
            expanded = value
            for _ in range(max_iterations):
                new_expanded = MyTemplate(expanded).safe_substitute(**d)
                if new_expanded == expanded:
                    break
                expanded = new_expanded
            d[key] = expanded
    return d


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

    # Recursively expand variables (up to 5 iterations to prevent infinite loops)
    # This allows for variables to contain variables
    cmd = MyTemplate(expandpath(cmd)).safe_substitute(**tgt.meta)
    _LOGGER.debug(f"Expanded command: {cmd}")
    count = 1
    while count < 5:
        cmd_new = MyTemplate(expandpath(cmd)).safe_substitute(**tgt.meta)
        _LOGGER.debug(f"Expanded command: {cmd_new}")
        if cmd == cmd_new:
            _LOGGER.debug("No more variables to expand")
            break
        cmd = cmd_new
        count += 1
    return cmd


def run_cmd(
    cmd: str, stdin: bytes | None = None, workdir: str | None = None
) -> tuple[int, str, str]:
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
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = p.communicate(input=stdin)
        return (
            p.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    else:
        p = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
        )
        stdout, stderr = p.communicate()
        return (
            p.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )


# ====================
# Configuration File Loading
# ====================


def recursive_get(dat: dict[str, Any], indices: list[str]) -> Any | None:
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
    cfg_path: str, workpath: str | None = None, autocomplete: bool = True
) -> dict[str, Any]:
    """Load a configuration file with import tracking to prevent duplicates.

    Wrapper function that initializes import tracking before loading.

    Args:
        cfg_path: Path to the configuration file.
        workpath: Working path for resolving relative paths.
        autocomplete: If True, suppresses some logging output.

    Returns:
        Loaded configuration dictionary.
    """
    imported_list: dict[str, bool] = {}
    return load_config_file(cfg_path, workpath, autocomplete, imported_list)


def load_config_file(
    filepath: str,
    workpath: str | None = None,
    autocomplete: bool = True,
    imported_list: dict[str, bool] | None = None,
) -> dict[str, Any]:
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


def make_abspath(relpath: str, filepath: str, root: str | None = None) -> str:
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
    filepath: str | None = None,
    workpath: str | None = None,
    autocomplete: bool = True,
    imported_list: dict[str, bool] | None = None,
) -> dict[str, Any]:
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
            import_file_abspath = make_abspath(expandpath(import_file), expandpath(filepath))
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
            import_file_abspath = make_abspath(expandpath(import_file), expandpath(filepath))
            if not autocomplete:
                _LOGGER.info(f"Specified relative config file to import (relative): {import_file}")
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
            deep_update(lower_cfg, {"targets": factory_targets}, warn_override=not autocomplete)

    # _LOGGER.debug("Lower cfg: " + str(lower_cfg))
    return lower_cfg


def warn_overriding_target(old: dict[str, Any], new: dict[str, Any]) -> None:
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
                    "Originally defined in: ".rjust(27, " ") + f"{old['targets'][tgt]['_defpath']}"
                )
                _LOGGER.error(
                    "Redefined in: ".rjust(27, " ") + f"{new['targets'][tgt]['_defpath']}"
                )
                raise Exception(
                    "Same target name is defined in imported file. Overriding targets is not allowed."
                )


def deep_update(
    old: dict[str, Any], new: dict[str, Any], warn_override: bool = True
) -> dict[str, Any]:
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


def load_target_factories() -> dict[str, Callable]:
    """Load target factories from entry points.

    Discovers target factories registered under the 'markmeld.factories' entry point
    group and combines them with built-in factories.

    Returns:
        Dictionary mapping factory names to their factory functions.
    """
    from importlib.metadata import entry_points

    built_in_factories: dict[str, Callable] = {"glob": glob_factory}

    eps = entry_points(group="markmeld.factories")

    installed_factories = {ep.name: ep.load() for ep in eps}
    built_in_factories.update(installed_factories)
    return built_in_factories


# ====================
# File and Path Operations
# ====================


def globs_to_dict(globs: list[str] | None, cfg_path: str) -> dict[str, str]:
    """Resolve glob patterns to a dictionary of file names to paths.

    Args:
        globs: List of glob patterns to resolve.
        cfg_path: Path to configuration file or directory for resolving
            relative patterns.

    Returns:
        Dictionary mapping base file names (without extension) to absolute paths.
    """
    return_items: dict[str, str] = {}
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


def write_to_file(content: str, output_path: str | Path) -> None:
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
        filename = filename.replace(char, "_")

    # Remove trailing dots and spaces (Windows compatibility)
    name_parts = filename.rsplit(".", 1)
    if len(name_parts) == 2:
        name, ext = name_parts
        name = name.rstrip(". ")
        filename = f"{name}.{ext}" if name else f"file.{ext}"
    else:
        filename = filename.rstrip(". ")

    # Limit length to 255 characters
    if len(filename) > 255:
        name_parts = filename.rsplit(".", 1)
        if len(name_parts) == 2:
            name, ext = name_parts
            if len(name) > 251:
                filename = f"{name[:251]}.{ext}"
        else:
            filename = filename[:251]

    return filename
