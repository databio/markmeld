"""Target factory that generates targets from glob patterns."""

import glob
import os
import logging
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def glob_factory(vars: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Generate build targets from a glob pattern.

    Creates multiple targets from files matching a glob pattern. Each matched
    file becomes a separate build target with its own output file.

    Args:
        vars: Variables dictionary containing:
            - path: Glob pattern to match files.
            - name_levels: Optional number of directory levels to include in target name.
            - inherit_from: Optional target to inherit settings from.
            - glob_variables: Optional additional variables to add to each target.
        cfg: Configuration dictionary containing '_cfg_file_path' for path resolution.

    Returns:
        Dictionary mapping target names to target configurations.
    """
    from .utilities import make_abspath
    path = make_abspath(vars["path"], cfg["_cfg_file_path"])
    name_levels = vars.get("name_levels", 0)
    globs = glob.glob(path)
    _LOGGER.debug(f"Globs: {globs}")
    _LOGGER.debug(f"Path: {path}")

    targets: Dict[str, Dict[str, Any]] = {}
    for glob_path in globs:
        # Extract target name from path
        split_path = glob_path.split("/")
        file_name = os.path.splitext(split_path[-1])[0]
        tgt_array = [file_name]
        for lvl in range(1, int(name_levels)):
            tgt_array.insert(0, split_path[-(lvl + 1)])

        tgt = "/".join(tgt_array)
        output_file = f"{tgt}.pdf"
        _LOGGER.debug(f"Found target: {tgt}")
        targets[tgt] = {
            "output_file": output_file,
            "data": {
                "md_files": {
                    "content": glob_path,
                }
            },
        }

        # Carry over inherit from variables
        variables_to_carry_over = ["inherit_from"]
        for v in variables_to_carry_over:
            if v in vars:
                targets[tgt][v] = vars[v]

        if "glob_variables" in vars:
            targets[tgt].update(vars["glob_variables"])

    return targets
