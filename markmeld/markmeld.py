import argparse
import datetime
import frontmatter
import jinja2
import logmuse
import os
import re
import subprocess
import sys
import time
import yaml

from copy import deepcopy
from collections.abc import Mapping
from datetime import date
from jinja2 import Template
from jinja2.filters import FILTERS, environmentfilter
from logging import getLogger
from ubiquerg import VersionInHelpParser
from ubiquerg import expandpath
from ubiquerg import is_url

from ._version import __version__
from .glob_factory import glob_factory

PKG_NAME = "markmeld"

_LOGGER = getLogger(PKG_NAME)


# Embed these in the package?
mm_targets = {
    "figs": "/home/nsheff/code/sciquill/bin/build-pdfs fig",
    "figs_png": "/home/nsheff/code/sciquill/bin/buildfigs fig/*.svg",
    "yaml_refs": "jabref -n --exportMatches 'groups=shefflab',reflists/ncs_papers.yaml,my_yaml i ${HOME}/code/papers/sheffield.bib",
    "pubs": "",
    "split": "/home/nsheff/code/sciquill/bin/splitsupl {combined} {primary} {appendix}",
}

tpl_generic = """{% if data.metadata_yaml is defined %}---
{{ data.metadata_yaml }}
---{% endif %}

{{ data.content }}"""


@environmentfilter
def datetimeformat(environment, value, to_format="%Y-%m-%d", from_format="%Y-%m-%d"):
    if from_format == "%s":
        value = time.ctime(int(value))
        from_format = "%a %b %d %H:%M:%S %Y"
        print(value)
    value = str(value)
    try:
        return datetime.datetime.strptime(value, from_format).strftime(to_format)
    except ValueError as VE:
        _LOGGER.warning(VE)
        return value


@environmentfilter
def extract_refs(environment, value):
    m = re.findall("@([a-zA-Z0-9_]+)", value)
    return m


# m = extract_refs("abc; hello @test;me @second one; and finally @three")
# m

def build_argparser():
    """
    Builds argument parser.

    :return argparse.ArgumentParser
    """

    banner = "%(prog)s - markup melder"
    additional_description = "\nhttps://markmeld.databio.org"

    parser = VersionInHelpParser(
        prog="markmeld",
        version=f"{__version__}",
        description=banner,
        epilog=additional_description,
    )

    parser.add_argument(
        "-c",
        "--config",
        dest="config",
        metavar="C",
        help="Path to mm configuration file.",
    )

    # position 1
    parser.add_argument(dest="target", metavar="T", help="Target", nargs="?")

    parser.add_argument(
        "-l", "--list", action="store_true", default=False, help="List targets"
    )

    parser.add_argument(
        "--autocomplete", action="store_true", default=False, help=argparse.SUPPRESS
    )

    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        default=False,
        help="Print template output instead of going to pandoc.",
    )

    parser.add_argument(
        "-v",
        "--vars",
        nargs="+",
        default=None,
        help="Extra key=value variable pairs",
    )

    return parser


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


def load_config_file(filepath):
    """
    Loads a configuration file.

    @param str filepath Path to configuration file to load
    @return dict Loaded yaml data object.
    """

    try: 
        with open(filepath, "r") as f:
            cfg_data = f.read()
        return load_config_data(cfg_data, os.path.abspath(filepath))
    except Exception as e:
        _LOGGER.error(f"Couldn't load config file: {filepath}")
        _LOGGER.error(e)
        return {}

def load_plugins():
    from pkg_resources import iter_entry_points

    built_in_plugins = {"glob": glob_factory}

    installed_plugins = {
        ep.name: ep.load() for ep in iter_entry_points("markmeld.factories")
    }
    built_in_plugins.update(installed_plugins)
    return built_in_plugins


def load_config_data(cfg_data, filepath=None):
    higher_cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    lower_cfg = {}

    # Add date to targets?
    if "targets" in higher_cfg:
        for tgt in higher_cfg["targets"]:
            _LOGGER.info(tgt, higher_cfg["targets"][tgt])
            higher_cfg["targets"][tgt]["_filepath"] = filepath
            
    # Imports
    if "imports" in higher_cfg:
        _LOGGER.debug("Found imports")
        for import_file in higher_cfg["imports"]:
            _LOGGER.error(f"Specified config file to import: {import_file}")
            deep_update(lower_cfg, load_config_file(expandpath(import_file)))

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
            factory_targets = func(fac_vals)
            deep_update(lower_cfg, {"targets": factory_targets})

    _LOGGER.debug("Lower cfg: " + str(lower_cfg))
    return lower_cfg


def populate_yaml_data(cfg, data):
    # Load up yaml data
    if "data_yaml" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating yaml data...")
    for d in cfg["data_yaml"]:
        _LOGGER.info(f"MM | {d}")
        with open(d, "r") as f:
            data.update(yaml.load(f, Loader=yaml.SafeLoader))

    return data


def populate_md_data(cfg, data):
    # Load up markdown data
    if "data_md" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating md data...")
    for k, v in cfg["data_md"].items():
        _LOGGER.info(f"MM | --> {k}: {v}")
        if not v:
            data[k] = v
            continue
        if is_url(v):
            # Do url stuff
            import requests

            response = requests.get(v)
            p = frontmatter.loads(response.text)
        else:
            p = frontmatter.load(v)
        data[k] = p.__dict__
        data["md"][k] = p.__dict__
        data[k]["all"] = frontmatter.dumps(p)
        _LOGGER.debug(data[k])
        if len(p.metadata) > 0:
            data[k]["metadata_yaml"] = yaml.dump(p.metadata)

    return data


def populate_data_md_globs(cfg, data):
    import glob

    if "data_md_globs" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating md data globs...")
    for folder in cfg["data_md_globs"]:
        files = glob.glob(folder)
        _LOGGER.info(files)
        for file in files:
            basename = os.path.basename(file)
            dirname = os.path.dirname(file)
            splitext =os.path.splitext(basename) 
            k = splitext[0]
            ext = splitext[1]
            _LOGGER.info(f"MM | [key:value] {k}:{file}")
            p = frontmatter.load(file)
            data[k] = p.__dict__
            data["md"][k] = p.__dict__
            data[k]["all"] = frontmatter.dumps(p)
            data[k]["path"] = file
            data[k]["ext"] = ext
            if len(p.metadata) > 0:
                data[k]["metadata_yaml"] = yaml.dump(p.metadata)
    return data


def load_template(cfg):
    if "md_template" not in cfg:
        return None

    md_tpl = None
    if os.path.isfile(cfg["md_template"]):
        md_tpl = cfg["md_template"]
    elif "mm_templates" in cfg:
        md_tpl = os.path.join(cfg["mm_templates"], cfg["md_template"])
    else:
        raise Exception(f"md_template file not found: {cfg['md_template']}")
    
    try:
        if is_url(md_tpl):            
            import requests
            response = requests.get(md_tpl)
            md_tpl_contents = response.text
        else:
            with open(md_tpl, "r") as f:
                md_tpl_contents = f.read()
        t = Template(md_tpl_contents)
    except TypeError:
        _LOGGER.error(f"Unable to open md_template. Path:{md_tpl}")
    return t


def meld_output(args, data, cmd_data, cfg, loop=True):
    """
    Melds input markdown and yaml into a jinja output.
    """

    # define some usful functions
    
    def recursive_get(dat, indices):
        for i in indices:
            if i not in dat:
                return None
            dat = dat[i]
        return dat

    def call_hook(cmd_data, data, tgt):
        # if tgt in mm_targets:

        #     cmd = mm_targets[tgt].format(**cmd_data)
        #     return run_cmd(cmd)
        # el

        if tgt in cmd_data["targets"]:
            return meld_output(args, data, populate_cmd_data(cfg, tgt), cfg)
        else:
            _LOGGER.warning(f"MM | No target called {tgt}.")
            return False

    if "md_template" in cmd_data:
        tpl = load_template(cmd_data)
    else:
        cmd_data["md_template"] = None
        tpl = Template(tpl_generic)
        _LOGGER.error("No md_template provided. Using generic markmeld template.")

    if "latex_template" not in cmd_data:
        cmd_data["latex_template"] = None

    # all the data goes into a big dict, with markdown data under a '.content' attribute
    # for the file name
    # use this to populate the template.


    if "prebuild" in cmd_data:
        # prebuild hooks
        for tgt in cmd_data["prebuild"]:
            _LOGGER.info(f"MM | Run prebuild hooks: {tgt}")
            call_hook(cmd_data, data, tgt)

    if loop:
        # If we're not looping, then these were already populated
        # by the parent loop.
        data = populate_data_md_globs(cmd_data, data)
        data = populate_yaml_data(cmd_data, data)
        data = populate_md_data(cmd_data, data)
        # _LOGGER.info(data)
        if "data_variables" in cmd_data:
            data.update(cmd_data["data_variables"])

        _LOGGER.info(f"MM | Today's date: {cmd_data['today']}")
        _LOGGER.info(f"MM | latex_template: {cmd_data['latex_template']}")
        _LOGGER.info(f"MM | Output md_template: {cmd_data['md_template']}")



    if "loop" in cmd_data and loop:
        loop_dat = recursive_get(data,cmd_data["loop"]["loop_data"].split("."))
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_codes = []
        for i in loop_dat:
            var = cmd_data["loop"]["assign_to"]
            _LOGGER.info(f"{var}: {i}")
            data.update({ var: i })
            cmd_data.update({ var: i })
            _LOGGER.debug(cmd_data)
            return_codes.append(meld_output(args, data, deepcopy(cmd_data), cfg, loop=False))

        _LOGGER.info(f"Return codes: {return_codes}")
        cmd_data["stopopen"] = True
        return max(return_codes)
    else:
        _LOGGER.debug("MM | No loop here.")

    if "output_file" in cmd_data:
        cmd_data["output_file"] = cmd_data["output_file"].format(**cmd_data)
    else:
        cmd_data["output_file"] = None

    _LOGGER.info(f"MM | Output file: {cmd_data['output_file']}")


    def run_cmd(cmd, cwd=None):
        _LOGGER.info(f"MM | Command: {cmd}; CWD: {cwd}")
        p = subprocess.Popen(cmd, shell=True, cwd=os.path.dirname(cwd))
        return p.communicate()

    returncode = -1

    if "type" in cmd_data and cmd_data["type"] == "raw":
        # Raw = No subprocess stdin printing
        cmd = cmd_data["command"]
        cmd_fmt = cmd.format(**cmd_data)
        _LOGGER.info(cmd_fmt)        
        run_cmd(cmd_fmt, cmd_data["_filepath"])  
    elif args.print:
        # return print(tpl.render(data))  # one time
        return print(Template(tpl.render(data)).render(data))  # two times
    elif cmd_data["command"]:
        cmd = cmd_data["command"]
        cmd_fmt = cmd.format(**cmd_data)
        _LOGGER.info(cmd_fmt)
        # Call command (pandoc), passing the rendered template to stdin
        import shlex

        _LOGGER.debug(cmd_fmt)
        # In case I need to make it NOT use the shell in the future
        # here's how:
        # cmd_fmt2 = cmd_fmt.replace("\n", "").replace("\\","")
        # cmd_ary = shlex.split(cmd_fmt2)
        # _LOGGER.debug(cmd_ary)
        p = subprocess.Popen(cmd_fmt, shell=True, stdin=subprocess.PIPE)
        # p.communicate(input=tpl.render(data).encode())
        if "recursive_render" in cmd_data and not cmd_data["recursive_render"]:
            rendered_in = tpl.render(data).encode()
        else:
            # Recursive rendering allows your template to include variables
            rendered_in = Template(tpl.render(data)).render(data).encode()
        p.communicate(input=rendered_in)
        returncode = p.returncode
        # _LOGGER.info(rendered_in)

    if "postbuild" in cmd_data:
        # postbuild hooks
        for tgt in cmd_data["postbuild"]:
            _LOGGER.info(f"MM | Run postbuild hooks: {tgt}")
            call_hook(cmd_data, data, tgt)

    return returncode


def populate_cmd_data(cfg, target=None, vardata=None):
    cmd_data = {}
    cmd_data.update(cfg)
    cmd_data["today"] = date.today().strftime("%Y-%m-%d")

    if target:
        if "targets" not in cfg:
            _LOGGER.error(f"No targets specified in config.")
            sys.exit(1)
        if target not in cfg["targets"]:
            _LOGGER.error(f"target {target} not found")
            sys.exit(1)
        cmd_data.update(cfg["targets"][target])
        _LOGGER.debug(f'Config for this target: {cfg["targets"][target]}')

    if vardata:
        cli_vars = {y[0]: y[1] for y in [x.split("=") for x in vardata]}
        cmd_data.update(cli_vars)
    else:
        cli_vars = {}

    if not "command" in cmd_data:
        # Generally, user should provide a `command`,
        # But if they don't for simple cases, we can just
        # route through pandoc.
        # Populate built-in pandoc auto-options
        options_array = []
        if "latex_template" in cmd_data:
            options_array.append("--template {latex_template}")
        if "output_file" in cmd_data:
            options_array.append("--output \"{output_file}\"")
        # default command
        options = " ".join(options_array)
        cmd_data["command"] = f"pandoc {options}"

    return cmd_data


def main():
    parser = logmuse.add_logging_options(build_argparser())
    args, _ = parser.parse_known_args()
    global _LOGGER
    _LOGGER = logmuse.logger_via_cli(args, make_root=True)

    if not args.config:
        if os.path.exists("_markmeld.yaml"):
            args.config = "_markmeld.yaml"
        else:
            _LOGGER.error(
                "You must provide config file or be in a dir with _markmeld.yaml."
            )
            sys.exit(1)

    data = {"md": {}}
    cfg = load_config_file(args.config)

    if args.list:
        if "targets" not in cfg:
            _LOGGER.error(f"No targets specified in config.")
            sys.exit(1)
        tarlist = [x for x, k in cfg["targets"].items()]
        _LOGGER.error(f"Targets: {tarlist}")
        sys.exit(1)

    if args.autocomplete:
        if "targets" not in cfg:
            sys.exit(1)
        for t, k in cfg["targets"].items():
            sys.stdout.write(t + " ")
        sys.exit(1)

    _LOGGER.debug("Custom date formatting...")
    # Add custom date formatter filter
    FILTERS["date"] = datetimeformat
    data["now"] = date.today().strftime("%s")

    # Add custom reference extraction filter
    FILTERS["extract_refs"] = extract_refs

    # Set up cmd_data object (it's variables for the command population)
    cmd_data = populate_cmd_data(cfg, args.target, args.vars)
    _LOGGER.debug("Melding...")
    # Meld it!
    returncode = meld_output(args, data, cmd_data, cfg)
    # Open the file
    if returncode == 0 and cmd_data["output_file"] and not "stopopen" in cmd_data:
        cmd_open = ["xdg-open", cmd_data["output_file"]]
        _LOGGER.info(" ".join(cmd_open))
        subprocess.call(cmd_open)
    else:
        _LOGGER.info(f"Return code: {returncode}")

    return


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
