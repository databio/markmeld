import glob
import os
import string
import subprocess
import yaml
import platform

from logging import getLogger
from collections.abc import Mapping
from ubiquerg import expandpath

from .const import PKG_NAME, FILE_OPENER_MAP

_LOGGER = getLogger(PKG_NAME)


# define some useful functions
def recursive_get(dat, indices):
    """
    Indexes into a nested dict with a list of indexes.
    """
    for i in indices:
        if i not in dat:
            return None
        dat = dat[i]
    return dat


def run_cmd(cmd, stdin=None, workdir=None):
    """Runs a command from a given workdir"""
    _LOGGER.info(f"MM | Command: {cmd}; CWD: {workdir}")
    if stdin:
        # Call command (default: pandoc), passing the rendered template to stdin
        p = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, cwd=os.path.dirname(workdir)
        )
        p.communicate(input=stdin)
        return p.returncode
    else:
        p = subprocess.Popen(cmd, shell=True, cwd=os.path.dirname(workdir))
        p.communicate()
        return p.returncode

    # In case I need to make it NOT use the shell in the future
    # here's how:
    # cmd_fmt2 = cmd_fmt.replace("\n", "").replace("\\","")
    # cmd_ary = shlex.split(cmd_fmt2)
    # _LOGGER.debug(cmd_ary)
    # p = subprocess.Popen(cmd_fmt, shell=True, stdin=subprocess.PIPE)
    # p.communicate(input=tpl.render(data).encode())


def format_command(tgt):
    """
    Given a command from a user config file, populate variables
    from the target metadata
    """
    cmd = tgt.meta["command"]
    if "output_file" in tgt.meta and tgt.meta["output_file"]:
        tgt.meta["output_file"] = expandpath(tgt.meta["output_file"]).format(**tgt.meta)
    else:
        tgt.meta["output_file"] = None
    vars_to_exp = [v[1] for v in string.Formatter().parse(cmd) if v[1] is not None]
    _LOGGER.debug(f"Vars to expand: {vars_to_exp}")
    cmd = expandpath(cmd).format(**tgt.meta)
    while len(vars_to_exp) > 0:
        # format again in case the command has variables in it
        # this allows for variables to contain variables
        cmd = expandpath(cmd).format(**tgt.meta)
        vars_to_exp = [v[1] for v in string.Formatter().parse(cmd) if v[1] is not None]
    return cmd


# There are two paths associated with each target:
# 1. the location of its definition (defpath or filepath)
# 2. the location of where it should be executed (workpath)
# These are not the same thing.


def load_config_wrapper(cfg_path, workpath=None, autocomplete=True):
    """
    Wrapper function that maintains a list of imported files, to prevent duplicate imports.
    """
    imported_list = {}
    return load_config_file(cfg_path, workpath, autocomplete, imported_list)


def load_config_file(filepath, workpath=None, autocomplete=True, imported_list={}):
    """
    Loads a configuration file.

    @param str filepath Path to configuration file to load
    @param str workpath The working path that the target's relative paths are relative to
    @return dict Loaded yaml data object.
    """
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


def make_abspath(relpath, filepath, root=None):
    if root:
        return os.path.join(root, relpath)
    return os.path.abspath(os.path.join(os.path.dirname(filepath), relpath))


def load_config_data(
    cfg_data, filepath=None, workpath=None, autocomplete=True, imported_list={}
):
    """
    Recursive loader that parses a yaml string, handles imports, and runs target factories to create targets.
    """
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
                higher_cfg["targets"][tgt]["_workpath"] = filepath

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
                load_config_file(import_file_abspath, expandpath(filepath)),
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
        plugins = load_plugins()
        _LOGGER.debug(f"Available plugins: {plugins}")
        for fac in lower_cfg["target_factories"]:
            fac_name = list(fac.keys())[0]
            fac_vals = list(fac.values())[0]
            _LOGGER.debug(f"Processing target factory: {fac_name}")
            # Look up function to call.
            func = plugins[fac_name]
            factory_targets = func(fac_vals, lower_cfg)
            for k, v in factory_targets.items():
                factory_targets[k]["_workpath"] = filepath
                factory_targets[k]["_defpath"] = filepath
            deep_update(
                lower_cfg, {"targets": factory_targets}, warn_override=not autocomplete
            )

    # _LOGGER.debug("Lower cfg: " + str(lower_cfg))
    return lower_cfg


def warn_overriding_target(old, new):
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


def deep_update(old, new, warn_override=True):
    """
    Like built-in dict update, but recursive.
    """
    if warn_override:
        warn_overriding_target(old, new)
    for k, v in new.items():
        if isinstance(v, Mapping):
            old[k] = deep_update(old.get(k, {}), v)
        else:
            old[k] = v
    return old


from .glob_factory import glob_factory


def load_plugins():
    from pkg_resources import iter_entry_points

    built_in_plugins = {"glob": glob_factory}

    installed_plugins = {
        ep.name: ep.load() for ep in iter_entry_points("markmeld.factories")
    }
    built_in_plugins.update(installed_plugins)
    return built_in_plugins


def globs_to_dict(globs, cfg_path):
    """
    Given some globs, resolve them to the actual files, and return them in a
    dict that is keyed by the base file name, without extension or parent folders.

    @param globs Iterable[str] List of globs to convert to files.
    @param cfg_path str Path to configuration file
    """
    return_items = {}
    if not globs:
        return return_items
    for item in globs:
        path = os.path.join(os.path.dirname(cfg_path), item)
        _LOGGER.info(f"MM | Glob path: {path}")
        files = glob.glob(path)
        for file in files:
            k = os.path.splitext(os.path.basename(file))[0]
            _LOGGER.info(f"MM | [key:value] {k}:{file}")
            return_items[k] = file
    return return_items


def get_file_open_cmd() -> str:
    """
    Detect the platform markmeld is running on, and
    return the correct executable to call.

    @return str name of executable
    """
    system = platform.system()
    return FILE_OPENER_MAP.get(system, "xdg-open")
