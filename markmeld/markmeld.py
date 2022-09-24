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
from jinja2.filters import FILTERS, pass_environment
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


@pass_environment
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


# Filter used by the nih_biosketch template to find references
# in a given prose block. Used to add citations to NIH
# "contributions" sections.
@pass_environment
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

    banner = "%(prog)s - markdown melder"
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



def load_config_file(filepath, autocomplete=True):
    """
    Loads a configuration file.

    @param str filepath Path to configuration file to load
    @return dict Loaded yaml data object.
    """

    try: 
        with open(filepath, "r") as f:
            cfg_data = f.read()
        return load_config_data(cfg_data, os.path.abspath(filepath), autocomplete)
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


def load_config_data(cfg_data, filepath=None, autocomplete=True):
    """
    Recursive loader that parses a yaml string, and handles imports.
    """


    higher_cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    higher_cfg["_cfg_file_path"] = filepath
    lower_cfg = {}

    # Add date to targets?
    if "targets" in higher_cfg:
        for tgt in higher_cfg["targets"]:
            _LOGGER.debug(tgt, higher_cfg["targets"][tgt])
            higher_cfg["targets"][tgt]["_filepath"] = filepath
            
    # Imports
    if "imports" in higher_cfg:
        _LOGGER.debug("Found imports")
        for import_file in higher_cfg["imports"]:
            if not autocomplete:
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
            factory_targets = func(fac_vals, lower_cfg)
            for k,v in factory_targets.items():
                factory_targets[k]["_filepath"] = filepath
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
        dabs = make_abspath(d, cfg)

        with open(dabs, "r") as f:
            data.update(yaml.load(f, Loader=yaml.SafeLoader))

    return data

# For itemized yaml this time...
def populate_yaml_keyed(cfg, data):
    # Load up yaml data
    if "data_yaml_keyed" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating keyed yaml data...")
    for k,v in cfg["data_yaml_keyed"].items():
        _LOGGER.info(f"MM | --> {k}: {v}")
        with open(v, "r") as f:
            yaml_dict = yaml.load(f, Loader=yaml.SafeLoader)
            print(yaml_dict)
            data[k] = yaml_dict
            data["yaml"][k] = yaml_dict
            data["raw"][k] = yaml.dump(yaml_dict)
            # 2022-08-12 Original way, this doesn't work in the case that data[k] is a list 
            # (if the yaml file is an array, not an object)
            # So I changed it put the raw value under ["raw"][k] instead of [k]["raw"]
            # data[k]["raw"] = yaml.dump(yaml_dict)
    return data

def populate_md_data(cfg, data):
    # Load up markdown data
    if "data_md" not in cfg:
        return data

    if "md" not in data:
        data["md"] = {}

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
            vabs = make_abspath(v, cfg)

            if os.path.exists(vabs):
                p = frontmatter.load(vabs)
            else:
                _LOGGER.warning(f"Skipping file that does not exist: {vabs}")
                data[k] = {}
                data["md"][k] = {}
                data[k]["all"] = ""
                continue
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



def make_abspath(relpath, cfg, root=None):
    if root:
        return os.path.join(root, relpath)
    return os.path.join(os.path.dirname(cfg["_cfg_file_path"]), relpath)

    


def load_template(cfg):
    if "md_template" not in cfg:
        return None

    md_tpl = None
    root = cfg["mm_templates"] if "mm_templates" in cfg else None
    md_tpl = make_abspath(cfg["md_template"], cfg, root)

    # # if os.path.isfile(cfg["md_template"]):
    # #     md_tpl = cfg["md_template"]
    # if "mm_templates" in cfg:
    #     md_tpl = os.path.join(cfg["mm_templates"], cfg["md_template"])
    # else:
    #     md_tpl = os.path.join(, cfg["md_template"])
    if not os.path.isfile(md_tpl):
        print(cfg)
        raise Exception(f"md_template file not found: {md_tpl}")
    
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



class MMDict(dict):
    """
    Just a dict object with a cmd_data property,
    to hold a second more specialized dict
    """
    def __init__(self, *arg, **kw):
       super(MMDict, self).__init__(*arg, **kw)
       self.cmd_data = {}


class Target(object):
    """
    Holds 2 dicts: real data and metadata for a target
    """
    def __init__(self, data={}, target_name=None):
        self.data = data
        self.target_name = target_name
        self.target_meta = populate_cmd_data(self.data, target_name)
        _LOGGER.info(f"MM | Output file: {self.target_meta['output_file']}")


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
    """ Runs a command from a given workdir"""
    _LOGGER.info(f"MM | Command: {cmd}; CWD: {workdir}")
    if stdin:
        # Call command (default: pandoc), passing the rendered template to stdin
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, cwd=os.path.dirname(workdir))
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
    cmd = target.target_meta["command"]
    if "output_file" in target.target_meta:
        target.target_meta["output_file"] = target.target_meta["output_file"].format(**target.target_meta)
    else:
        target.target_meta["output_file"] = None
    cmd_fmt = cmd.format(**target.target_meta)
    return cmd_fmt    


class MarkdownMelder(object):
    def __init__(self, cfg):
        """
        Instantiate a MarkdownMelder object
        """
        _LOGGER.info("Initializing MarkdownMelder...")
        self.cfg = cfg
        self.target_objects = {}
       
    def open_target(self, target_name):
        tgt = Target(self.cfg, target_name)

        if tgt.target_meta["output_file"] and not "stopopen" in tgt.target_meta:
            return tgt.target_meta["output_file"]
        else:
            return False

    def build_target(self, target_name, print_only=False):

        tgt = Target(self.cfg, target_name)

        # First, run any pre-builds
        if "prebuild" in tgt.data:
            for pretgt in tgt.data["prebuild"]:
                _LOGGER.info(f"MM | Run prebuild hooks: {tgt}: {pretgt}")
                if pretgt in self["targets"]:
                    self.build_target(self, pretgt)
                else:
                    _LOGGER.warning(f"MM | No target called {pretgt}, requested prebuild by target {tgt}.")
                    return False

        # Next, meld the inputs. This can be time-consuming, it reads data to populate variables
        melded_input = self.meld_inputs(tgt)

        if "loop" in tgt.target_meta:
            return self.build_target_in_loop(tgt, melded_input, print_only)

        # Run command...
        return self.run_command_for_target(tgt, melded_input, print_only)

    def run_command_for_target(self, tgt, melded_input, print_only):
        cmd_fmt = format_command(tgt)
        if "type" in tgt.data and tgt.data["type"] == "raw":
            # Raw = No subprocess stdin printing. (so, it doesn't render anything)
            cmd_fmt = format_command(tgt)
            tgt.melded_output = None
            tgt.returncode = run_cmd(cmd_fmt, None, tgt.target_meta["_filepath"])
        elif print_only:
            # Case 2: print_only means just render but run no command.
            # return print(tpl.render(data))  # one time
            tgt.melded_output = self.render_template(melded_input, tgt)
            tgt.returncode = 0
        elif tgt.target_meta["command"]:
            cmd_fmt = format_command(tgt)
            _LOGGER.debug(cmd_fmt)
            if "recursive_render" in tgt.target_meta and not tgt.target_meta["recursive_render"]:
                melded_output = self.render_template(melded_input, tgt, double=False).encode()
            else:
                # Recursive rendering allows your template to include variables
                melded_output = self.render_template(melded_input, tgt, double=True).encode()
            tgt.melded_output = melded_output
            tgt.returncode = run_cmd(cmd_fmt, melded_output, tgt.target_meta["_filepath"])

        return tgt

    def build_target_in_loop(self, tgt, melded_input, print_only=False):
        #  Process each iteration of the loop
        loop_dat = recursive_get(melded_input,tgt.target_meta["loop"]["loop_data"].split("."))
        print(loop_dat)
        print(tgt.data)
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_target_objects = {}
        for i in range(len(loop_dat)):
            loop_var_value = loop_dat[i]
            melded_input_copy = deepcopy(melded_input)
            tgt_copy = deepcopy(tgt)
            var = tgt_copy.target_meta["loop"]["assign_to"]
            print(f"{var}: {loop_var_value}")
            _LOGGER.info(f"{var}: {loop_var_value}")
            melded_input_copy.update({ var: loop_var_value })
            tgt_copy.target_meta.update({ var: loop_var_value })
            print(tgt_copy.target_meta)
            # _LOGGER.debug(cmd_data)
            rendered_in = self.render_template(melded_input_copy, tgt_copy, double=False).encode()
            return_target_objects[i] = self.run_command_for_target(tgt_copy, melded_input_copy, print_only)

        return return_target_objects

    def meld_inputs(self, target):
        data_copy = deepcopy(target.data)
        data_copy["yaml"] = {}
        data_copy["raw"] = {}
        data_copy = populate_data_md_globs(target.target_meta, data_copy)
        data_copy = populate_yaml_data(target.target_meta, data_copy)
        data_copy = populate_yaml_keyed(target.target_meta, data_copy)
        data_copy = populate_md_data(target.target_meta, data_copy)
        if "data_variables" in target.target_meta:
            data_copy.update(target.target_meta["data_variables"])

        return data_copy

    def render_template(self, melded_input, target, double=True):
        if "md_template" in target.target_meta:
            tpl = load_template(target.target_meta)
        else:
            # cmd_data["md_template"] = None
            tpl = Template(tpl_generic)
            _LOGGER.error("No md_template provided. Using generic markmeld template.")
        if double:
            return Template(tpl.render(melded_input)).render(melded_input)  # two times
        else:
            return tpl.render(melded_input)



    def meld_output(self, data, cmd_data, config=None, print_only=False, in_loop=False):
        """
        Melds input markdown and yaml through a jinja template to produce text output.
        """
        cfg = config if config else self.cfg
        print("loop", loop)

        def call_hook(cmd_data, data, tgt):
            # if tgt in mm_targets:

            #     cmd = mm_targets[tgt].format(**cmd_data)
            #     return run_cmd(cmd)
            # el

            if tgt in cmd_data["targets"]:
                return meld_output(data, populate_cmd_data(cfg, tgt), cfg, print_only)
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

        if not in_loop:
            # If we're not looping, then these were already populated
            # by the parent loop. We don't want to repopulate
            data["yaml"] = {}
            data["raw"] = {}
            data = populate_data_md_globs(cmd_data, data)
            data = populate_yaml_data(cmd_data, data)
            data = populate_yaml_keyed(cmd_data, data)
            data = populate_md_data(cmd_data, data)
            # _LOGGER.info(data)
            if "data_variables" in cmd_data:
                data.update(cmd_data["data_variables"])

            print(cmd_data)
            _LOGGER.info(f"MM | Today's date: {cmd_data['today']}")
            _LOGGER.info(f"MM | latex_template: {cmd_data['latex_template']}")
            _LOGGER.info(f"MM | Output md_template: {cmd_data['md_template']}")

        if "loop" in cmd_data and not in_loop:
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
                return_codes.append(meld_output(data, deepcopy(cmd_data), cfg, print_only=args.print, in_loop=True))

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

        return data



    def meld_to_command(self, data, cmd_data):
        """
        This function takes the melded output and runs the command on it.
        """

        def run_cmd(cmd, cwd=None):
            _LOGGER.info(f"MM | Command: {cmd}; CWD: {cwd}")
            p = subprocess.Popen(cmd, shell=True, cwd=os.path.dirname(cwd))
            return p.communicate()

        returncode = -1

        if "type" in cmd_data and cmd_data["type"] == "raw":
            # Raw = No subprocess stdin printing. (so, it doesn't render anything)
            cmd = cmd_data["command"]
            cmd_fmt = cmd.format(**cmd_data)
            _LOGGER.info(cmd_fmt)        
            run_cmd(cmd_fmt, cmd_data["_filepath"])  
        elif print_only:
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

class TargetError(Exception):
    pass


def populate_cmd_data(cfg, target=None, vardata=None):
    cmd_data = {}
    cmd_data.update(cfg)
    cmd_data["today"] = date.today().strftime("%Y-%m-%d")

    if target:
        if "targets" not in cfg:
            _LOGGER.error(f"No targets specified in config.")
            raise TargetError(f"No targets specified in config.")
        if target not in cfg["targets"]:
            _LOGGER.error(f"target {target} not found")
            raise TargetError(f"Target {target} not found")
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

    cfg = load_config_file(args.config, args.autocomplete)

    if args.list:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        tarlist = [x for x, k in cfg["targets"].items()]
        _LOGGER.error(f"Targets: {tarlist}")
        sys.exit(1)

    if args.autocomplete:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        for t, k in cfg["targets"].items():
            sys.stdout.write(t + " ")
        sys.exit(1)

    _LOGGER.debug("Custom date formatting...")
    # Add custom date formatter filter
    FILTERS["date"] = datetimeformat

    data = MMDict({"md": {}})
    data["now"] = date.today().strftime("%s")

    # Add custom reference extraction filter
    FILTERS["extract_refs"] = extract_refs

    # Set up cmd_data object (it's variables for the command population)
    cmd_data = populate_cmd_data(cfg, args.target, args.vars)
    _LOGGER.debug("Melding...")

    mm = MarkdownMelder(cfg)

    # Meld it!
    built_target = mm.build_target(args.target, print_only=args.print)
    # returncode = mm.meld_output(data, cmd_data, cfg, print_only=args.print)
    # Open the file

    # if returncode == 0 and cmd_data["output_file"] and not "stopopen" in cmd_data:
    output_file = built_target.target_meta["output_file"]

    if built_target.returncode == 0 and output_file and not "stopopen" in built_target.target_meta:
        cmd_open = ["xdg-open", output_file]
        _LOGGER.info(" ".join(cmd_open))
        subprocess.call(cmd_open)
    else:
        _LOGGER.info(f"Return code: {built_target.returncode}")

    return


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
