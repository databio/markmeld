import os
import subprocess
import yaml

from logging import getLogger
from collections.abc import Mapping
from ubiquerg import expandpath

from .const import PKG_NAME

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


def format_command(target):
    """
    Given a command from a user config file, populate variables
    from the target metadata
    """
    cmd = target.target_meta["command"]
    if "output_file" in target.target_meta and target.target_meta["output_file"]:
        target.target_meta["output_file"] = target.target_meta["output_file"].format(
            **target.target_meta
        )
    else:
        target.target_meta["output_file"] = None
    cmd_fmt = cmd.format(**target.target_meta)
    return cmd_fmt


def load_config_file(filepath, target_filepath=None, autocomplete=True):
    """
    Loads a configuration file.

    @param str filepath Path to configuration file to load
    @return dict Loaded yaml data object.
    """

    try:
        with open(filepath, "r") as f:
            cfg_data = f.read()
        return load_config_data(
            cfg_data, os.path.abspath(filepath), target_filepath, autocomplete
        )
    except Exception as e:
        _LOGGER.error(f"Couldn't load config file: {filepath} because: {repr(e)}")
        return {}


def make_abspath(relpath, filepath, root=None):
    if root:
        return os.path.join(root, relpath)
    return os.path.join(os.path.dirname(filepath), relpath)


def load_config_data(cfg_data, filepath=None, target_filepath=None, autocomplete=True):
    """
    Recursive loader that parses a yaml string, handles imports, and runs target factories.
    """
    higher_cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    higher_cfg["_cfg_file_path"] = filepath
    lower_cfg = {}

    # Add filepath to targets defined in the current cfg file
    if "targets" in higher_cfg:
        for tgt in higher_cfg["targets"]:
            _LOGGER.debug(tgt, higher_cfg["targets"][tgt])
            if target_filepath:
                higher_cfg["targets"][tgt]["_filepath"] = target_filepath
            else:
                higher_cfg["targets"][tgt]["_filepath"] = filepath

    # Imports
    if "imports" in higher_cfg:
        _LOGGER.debug("Found imports")
        for import_file in higher_cfg["imports"]:
            import_file_abspath = os.path.relpath(
                make_abspath(expandpath(import_file), expandpath(filepath))
            )
            if not autocomplete:
                _LOGGER.error(f"Specified config file to import: {import_file_abspath}")
            deep_update(
                lower_cfg, load_config_file(import_file_abspath, expandpath(filepath))
            )

    if "imports_relative" in higher_cfg:
        _LOGGER.debug("Found relative imports")
        for import_file in higher_cfg["imports_relative"]:
            import_file_abspath = os.path.relpath(
                make_abspath(expandpath(import_file), expandpath(filepath))
            )
            if not autocomplete:
                _LOGGER.error(f"Specified config file to import: {import_file}")
            deep_update(lower_cfg, load_config_file(expandpath(import_file_abspath)))

    deep_update(lower_cfg, higher_cfg)

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
                factory_targets[k]["_filepath"] = filepath
            deep_update(lower_cfg, {"targets": factory_targets})

    _LOGGER.debug("Lower cfg: " + str(lower_cfg))
    return lower_cfg


def deep_update(old, new):
    """
    Like built-in dict update, but recursive.
    """
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
