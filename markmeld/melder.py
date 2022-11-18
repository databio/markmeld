import datetime
import frontmatter
import glob
import jinja2
import os
import re
import sys
import time
import yaml

from copy import deepcopy

from datetime import date
from jinja2 import Template
from jinja2.filters import FILTERS, pass_environment
from logging import getLogger

from ubiquerg import expandpath
from ubiquerg import is_url

from .const import PKG_NAME
from .exceptions import *

from .utilities import format_command, recursive_get, run_cmd, make_abspath
from .utilities import *

MD_FILES_KEY = "md_files"
MD_GLOBS_KEY = "md_globs"
YAML_FILES_KEY = "yaml_files"
YAML_GLOBS_KEY = "yaml_globs"
YAML_GLOBS_UNKEYED_KEY = "yaml_globs_unkeyed"

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


tpl_generic = """
{{ _global_frontmatter.fenced}}{{ content }}
"""

# tpl_generic = """
# {{ data }}
# """


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


# Add custom date formatter filter
FILTERS["date"] = datetimeformat
# Add custom reference extraction filter
FILTERS["extract_refs"] = extract_refs


# m = extract_refs("abc; hello @test;me @second one; and finally @three")
# m


def populate_data_yaml(cfg, data):
    # Load up yaml data
    if "data_yaml" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating yaml data...")
    for d in cfg["data_yaml"]:
        _LOGGER.info(f"MM | {d}")
        dabs = make_abspath(d, cfg["_cfg_file_path"])

        with open(dabs, "r") as f:
            data.update(yaml.load(f, Loader=yaml.SafeLoader))

    return data


# For itemized yaml this time...
def populate_data_yaml_keyed(cfg, data):
    # Load up yaml data
    if "data_yaml_keyed" not in cfg:
        return data
    _LOGGER.info(f"MM | Populating keyed yaml data...")
    for k, v in cfg["data_yaml_keyed"].items():
        _LOGGER.info(f"MM | --> {k}: {v}")
        with open(v, "r") as f:
            yaml_dict = yaml.load(f, Loader=yaml.SafeLoader)
            _LOGGER.debug(yaml_dict)
            data[k] = yaml_dict
            data["yaml"][k] = yaml_dict
            data["raw"][k] = yaml.dump(yaml_dict)
            # 2022-08-12 Original way, this doesn't work in the case that data[k] is a list
            # (if the yaml file is an array, not an object)
            # So I changed it put the raw value under ["raw"][k] instead of [k]["raw"]
            # data[k]["raw"] = yaml.dump(yaml_dict)
    return data


def populate_data_md(cfg, data):
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
        if is_url(v):  # Do url stuff
            import requests

            response = requests.get(v)
            p = frontmatter.loads(response.text)
        else:
            vabs = make_abspath(v, cfg["_cfg_file_path"])
            if os.path.exists(vabs):
                p = frontmatter.load(vabs)
            else:
                _LOGGER.warning(f"Skipping file that does not exist: {vabs}")
                data[k] = {}
                data["md"][k] = {}
                data[k]["all"] = ""
                continue
        data[k] = p.__dict__
        del data[k]["handler"]
        data["md"][k] = data[k]
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
            splitext = os.path.splitext(basename)
            k = splitext[0]
            ext = splitext[1]
            _LOGGER.info(f"MM | [key:value] {k}:{file}")
            p = frontmatter.load(file)
            data[k] = p.__dict__
            del data[k]["handler"]
            data["md"][k] = p.__dict__
            del data["md"][k]["handler"]
            data[k]["all"] = frontmatter.dumps(p)
            data[k]["path"] = file
            data[k]["ext"] = ext
            if len(p.metadata) > 0:
                data[k]["metadata_yaml"] = yaml.dump(p.metadata)
    return data


def resolve_globs(globs, cfg_path):
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


def process_data_block(data_block, filepath):
    _LOGGER.info(f"MM | Processing data block...")
    data = {"_raw": {}}  # Initialize return value
    frontmatter_temp = {}
    local_frontmatter_temp = {}
    vars_temp = {}

    md_files = {}
    yaml_files = {}
    unkeyed_yaml_files = []

    if MD_GLOBS_KEY in data_block and data_block[MD_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating md data globs...")
        md_files.update(resolve_globs(data_block[MD_GLOBS_KEY], filepath))
    if YAML_GLOBS_KEY in data_block and data_block[YAML_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating yaml data globs...")
        yaml_files.update(resolve_globs(data_block[YAML_GLOBS_KEY], filepath))
    if YAML_GLOBS_UNKEYED_KEY in data_block and data_block[YAML_GLOBS_UNKEYED_KEY]:
        _LOGGER.info(f"MM | Populating unkeyed yaml globs...")
        tmp_files = resolve_globs(data_block[YAML_GLOBS_UNKEYED_KEY], filepath)
        yaml_files.update(tmp_files)
        unkeyed_yaml_files = tmp_files
    if MD_FILES_KEY in data_block and data_block[MD_FILES_KEY]:
        md_files.update(data_block[MD_FILES_KEY])
    if YAML_FILES_KEY in data_block and data_block[YAML_FILES_KEY]:
        yaml_files.update(data_block[YAML_FILES_KEY])

    for k, v in yaml_files.items():
        _LOGGER.info(f"MM | Processing yaml file {k}: {v}")
        vabs = make_abspath(v, filepath)
        if not os.path.exists(vabs):
            _LOGGER.error(f"File not found: {vabs}")
        else:
            with open(vabs, "r") as f:
                yaml_dict = yaml.load(f, Loader=yaml.SafeLoader)
                _LOGGER.debug(yaml_dict)
                # data[k] = yaml_dict
                if k in unkeyed_yaml_files:
                    data.update(yaml_dict)
                else:
                    data[k] = yaml_dict
                data["_raw"][k] = yaml.dump(yaml_dict)
                vars_temp.update(yaml_dict)
                if k[:11] == "frontmatter":
                    frontmatter_temp.update(yaml_dict)

    for k, v in md_files.items():
        _LOGGER.info(f"MM | Processing md file {k}:{v}")
        if not v:
            data[k] = v
            continue
        if is_url(v):  # Do url stuff
            import requests

            response = requests.get(v)
            p = frontmatter.loads(response.text)
        else:
            vabs = make_abspath(v, filepath)
            if os.path.exists(vabs):
                p = frontmatter.load(vabs)
            else:
                _LOGGER.warning(f"Skipping file that does not exist: {vabs}")
                data[k] = ""  # Populate with empty values
                data["_raw"][k] = {}
                continue
        data[k] = p.content
        frontmatter_temp.update(p.metadata)
        local_frontmatter_temp[k] = p.metadata
        data["_raw"][k] = frontmatter.dumps(p)
        # data["md_dict"][k] = p.__dict__
        # data[k]["all"] = frontmatter.dumps(p)
        # _LOGGER.debug(data["md"][k])
        if len(p.metadata) > 0:
            # data[k]["metadata_yaml"] = yaml.dump(p.metadata)
            vars_temp.update(p.metadata)
            frontmatter_temp.update(p.metadata)

    if "variables" in data_block and data_block["variables"]:
        data.update(data_block["variables"])
        vars_temp.update(data_block["variables"])
        for k, v in data_block["variables"].items():
            if k[:11] == "frontmatter":
                frontmatter_temp.update({k[12:]: v})

    # vars_raw = yaml.dump(vars_temp)
    def get_frontmatter_formats(frontmatter_temp):
        if len(frontmatter_temp) == 0:
            frontmatter_raw = ""
            frontmatter_fenced = ""
        else:
            frontmatter_raw = yaml.dump(frontmatter_temp)
            frontmatter_fenced = f"---\n{frontmatter_raw}---\n"

        return {
            "raw": frontmatter_raw,
            "fenced": frontmatter_fenced,
            "dict": frontmatter_temp,
        }

    # Global vars behaves exactly like global frontmatter, except:
    # 1. It's all variables, not just those marked with frontmatter_*.
    # It's like what's in a main data array, except it includes metadata,
    # and excludes markdown content... Is that useful?
    data["_global_vars"] = vars_temp

    # Integrated, global frontmatter -- combines all frontmatter from .md files,
    # Plus any yaml data indexed with frontmatter_*,
    # Plus any variables indexed with frontmatter_* -- in that priority order.
    data["_global_frontmatter"] = get_frontmatter_formats(frontmatter_temp)

    # Local frontmatter (per markdown file)
    data["_local_frontmatter"] = {}
    for k, v in local_frontmatter_temp.items():
        data["_local_frontmatter"][k] = get_frontmatter_formats(v)

    return data


def load_template(cfg):
    if "jinja_template" not in cfg or not cfg["jinja_template"]:
        return None

    md_tpl = None
    root = cfg["mm_templates"] if "mm_templates" in cfg else None
    md_tpl = make_abspath(cfg["jinja_template"], cfg["_cfg_file_path"], root)
    _LOGGER.info(f"MM | jinja template: {md_tpl}")
    # # if os.path.isfile(cfg["md_template"]):
    # #     md_tpl = cfg["md_template"]
    # if "mm_templates" in cfg:
    #     md_tpl = os.path.join(cfg["mm_templates"], cfg["md_template"])
    # else:
    #     md_tpl = os.path.join(, cfg["md_template"])
    if not os.path.isfile(md_tpl):
        _LOGGER.debug(cfg)
        raise Exception(f"jinja_template file not found: {md_tpl}")

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
        _LOGGER.error(f"Unable to open jinja_template. Path:{md_tpl}")
    return t


class Target(object):
    """
    Holds 2 dicts: Original cfg data, and specific metadata for a target.
    Really there are 2 classes of variables in a target. One is the variables
    available for the template rendering. The second is the variables
    available to execute the command to produce the target, to which
    the rendered output is passed. Some variables need to be made available
    in both places. But really, I don't see a downside to just combining them.
    Therefore, I should merge these into one concept.
    """

    def __init__(self, root_cfg={}, target_name=None, vardata=None):
        self.root_cfg = root_cfg
        self.target_name = target_name
        target_meta = {}
        target_meta.update(self.root_cfg)
        target_meta["_now"] = date.today().strftime("%s")
        target_meta["_today"] = date.today().strftime("%Y-%m-%d")
        target_meta["today"] = target_meta["_today"]  # TODO: Remove this
        target_meta["now"] = target_meta["_now"]  # TODO: Remove this

        # Since a target has available to it all the variables in the _markemeld.yaml
        # config file, we start from there, then make a few changes:
        # 1. Elevate the variables in the given target up one level.
        # 2. To simplify debugging and reduce memory, remove the 'targets' key

        # _LOGGER.info(list(data["targets"].keys()))
        _LOGGER.debug(f"MM | Creating Target object for target: {target_name}")

        if target_name:
            if "targets" not in root_cfg:
                _LOGGER.error(f"No targets specified in config.")
                raise TargetError(f"No targets specified in config.")
            if target_name not in list(root_cfg["targets"].keys()):
                _LOGGER.error(f"target {target_name} not found")
                raise TargetError(f"Target {target_name} not found")
            target_meta = deep_update(target_meta, root_cfg["targets"][target_name])
            _LOGGER.debug(f'Config for this target: {root_cfg["targets"][target_name]}')

        del target_meta["targets"]
        if "version" in target_meta:
            del target_meta["version"]

        if vardata:
            cli_vars = {y[0]: y[1] for y in [x.split("=") for x in vardata]}
            target_meta.update(cli_vars)
        else:
            cli_vars = {}

        if not "command" in target_meta:
            # Generally, user should provide a `command`, but for simple default cases,
            # we can just route through pandoc as a default command.
            options_array = []
            if "latex_template" in target_meta:
                options_array.append("--template {latex_template}")
            if "output_file" in target_meta:
                options_array.append('--output "{output_file}"')
            options = " ".join(options_array)
            target_meta["command"] = f"pandoc {options}"

        _LOGGER.debug(f"target_meta: {target_meta}")
        self.target_meta = target_meta
        _LOGGER.debug(f"MM | Config file path: {self.target_meta['_cfg_file_path']}")
        if "output_file" in self.target_meta:
            _LOGGER.info(f"MM | Output file: {self.target_meta['output_file']}")


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

    def build_target(self, target_name, print_only=False, vardump=False):

        tgt = Target(self.cfg, target_name)
        _LOGGER.info(f"MM | Building target: {tgt.target_name}")

        # First, run any pre-builds
        if "prebuild" in tgt.target_meta:
            _LOGGER.info(f"MM | Run prebuilds for target: {tgt.target_name}")
            for pretgt in tgt.target_meta["prebuild"]:
                _LOGGER.info(f"MM | Prebuild target: {pretgt}")
                if pretgt in self.cfg["targets"]:
                    self.build_target(pretgt)
                else:
                    _LOGGER.warning(
                        f"MM | No target called {pretgt}, requested prebuild by target {tgt}."
                    )
                    return False

        # Next, meld the inputs. This can be time-consuming, it reads data to populate variables
        melded_input = self.meld_inputs(tgt)

        if "loop" in tgt.target_meta:
            return self.build_target_in_loop(tgt, melded_input, print_only, vardump)

        # Run command...
        return self.run_command_for_target(tgt, melded_input, print_only, vardump)

    def run_command_for_target(self, tgt, melded_input, print_only, vardump=False):
        _LOGGER.info(f"File path for this target: {tgt.target_meta['_filepath']}")
        if "type" in tgt.target_meta and tgt.target_meta["type"] == "raw":
            # Raw = No subprocess stdin printing. (so, it doesn't render anything)
            cmd_fmt = format_command(tgt)
            tgt.melded_output = None
            tgt.returncode = run_cmd(cmd_fmt, None, tgt.target_meta["_filepath"])
        elif "type" in tgt.target_meta and tgt.target_meta["type"] == "meta":
            # Meta = No command, it's a meta-target used for prebuilds or something else
            tgt.melded_output = None
            tgt.returncode = 0
        elif print_only:
            # Case 2: print_only means just render but run no command.
            # return print(tpl.render(data))  # one time
            tgt.melded_output = self.render_template(melded_input, tgt)
            tgt.returncode = 0
        elif vardump:
            tgt.melded_output = melded_input
            tgt.returncode = 0
        elif tgt.target_meta["command"]:
            cmd_fmt = format_command(tgt)
            _LOGGER.debug(cmd_fmt)
            if (
                "recursive_render" in tgt.target_meta
                and not tgt.target_meta["recursive_render"]
            ):
                melded_output = self.render_template(
                    melded_input, tgt, double=False
                ).encode()
            else:
                # Recursive rendering allows your template to include variables
                melded_output = self.render_template(
                    melded_input, tgt, double=True
                ).encode()
            tgt.melded_output = melded_output
            _LOGGER.debug(tgt.target_meta)
            tgt.returncode = run_cmd(
                cmd_fmt, melded_output, tgt.target_meta["_filepath"]
            )
        return tgt

    def build_target_in_loop(self, tgt, melded_input, print_only=False, vardump=False):
        #  Process each iteration of the loop
        loop_dat = recursive_get(
            melded_input, tgt.target_meta["loop"]["loop_data"].split(".")
        )
        _LOGGER.debug(loop_dat)
        _LOGGER.debug(tgt.root_cfg)
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_target_objects = {}
        for i in range(len(loop_dat)):
            loop_var_value = loop_dat[i]
            melded_input_copy = deepcopy(melded_input)
            tgt_copy = deepcopy(tgt)
            var = tgt_copy.target_meta["loop"]["assign_to"]
            _LOGGER.info(f"{var}: {loop_var_value}")
            melded_input_copy.update({var: loop_var_value})
            tgt_copy.target_meta.update({var: loop_var_value})
            _LOGGER.debug(tgt_copy.target_meta)
            # _LOGGER.debug(cmd_data)
            rendered_in = self.render_template(
                melded_input_copy, tgt_copy, double=False
            ).encode()
            return_target_objects[i] = self.run_command_for_target(
                tgt_copy, melded_input_copy, print_only, vardump
            )

        return return_target_objects

    def meld_inputs(self, target):
        data_copy = deepcopy(target.root_cfg)
        data_copy.update(target.target_meta)

        if not "version" in target.root_cfg or target.root_cfg["version"] < 1:
            _LOGGER.info("MM | Processing config version 0...")
            data_copy["yaml"] = {}
            data_copy["raw"] = {}
            data_copy["md"] = {}
            data_copy = populate_data_md_globs(target.target_meta, data_copy)
            data_copy = populate_data_yaml(target.target_meta, data_copy)
            data_copy = populate_data_yaml_keyed(target.target_meta, data_copy)
            data_copy = populate_data_md(target.target_meta, data_copy)
            if "data_variables" in target.target_meta:
                data_copy.update(target.target_meta["data_variables"])
        elif target.root_cfg["version"] >= 1:
            _LOGGER.info("MM | Processing config version 1...")
            if "data" in target.target_meta:
                processed_data_block = process_data_block(
                    target.target_meta["data"], target.target_meta["_filepath"]
                )
            else:
                processed_data_block = process_data_block(
                    {}, target.target_meta["_filepath"]
                )
            _LOGGER.debug("processed_data_block:", processed_data_block)
            data_copy.update(processed_data_block)
        k = list(data_copy.keys())
        _LOGGER.info(f"MM | Available keys: {k}")
        if MD_FILES_KEY in data_copy:
            _LOGGER.info(
                f"MM | Available keys [{MD_FILES_KEY}]: {list(data_copy[MD_FILES_KEY].keys())}"
            )
        if YAML_FILES_KEY in data_copy:
            _LOGGER.info(
                f"MM | Available keys [{YAML_FILES_KEY}]: {list(data_copy[YAML_FILES_KEY].keys())}"
            )
        return data_copy

    def render_template(self, melded_input, target, double=True):
        # print(melded_input)
        if "data" not in melded_input:
            melded_input["data"] = {}
        if "md_template" in target.target_meta:
            _LOGGER.error(
                "Please update your config! 'md_template' was renamed to 'jinja_template'."
            )
            target.target_meta["jinja_template"] = target.target_meta["md_template"]

        if (
            "jinja_template" in target.target_meta
            and target.target_meta["jinja_template"]
        ):
            tpl = load_template(target.target_meta)
        else:
            # cmd_data["jinja_template"] = None
            tpl = Template(tpl_generic)
            _LOGGER.error(
                "No jinja_template provided. Using generic markmeld jinja_template."
            )
        if double:
            return Template(tpl.render(melded_input)).render(melded_input)  # two times
        else:
            return tpl.render(melded_input)
