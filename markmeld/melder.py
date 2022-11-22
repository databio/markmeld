import datetime
import frontmatter
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
from .utilities import *

MD_FILES_KEY = "md_files"
MD_GLOBS_KEY = "md_globs"
YAML_FILES_KEY = "yaml_files"
YAML_GLOBS_KEY = "yaml_globs"
YAML_GLOBS_UNKEYED_KEY = "yaml_globs_unkeyed"

_LOGGER = getLogger(PKG_NAME)

tpl_generic = """
{{ _global_frontmatter.fenced}}{{ content }}
"""


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


def get_frontmatter_formats(frontmatter):
    """
    Given a dictionary of content, return 3 versions of it: the dict, a yaml dumped version, and a fenced yaml dumped

    @param dict frontmatter A dict representing some yaml frontmatter for a md file
    """
    if len(frontmatter) == 0:
        frontmatter_raw = ""
        frontmatter_fenced = ""
    else:
        frontmatter_raw = yaml.dump(frontmatter)
        frontmatter_fenced = f"---\n{frontmatter_raw}---\n"

    return {
        "raw": frontmatter_raw,
        "fenced": frontmatter_fenced,
        "dict": frontmatter,
    }


def process_data(data_block, filepath):
    _LOGGER.info(f"MM | Processing data block...")
    data = {"_raw": {}, "_md": {}, "_yaml": {}}  # Initialize return value
    frontmatter_temp = {}
    local_frontmatter_temp = {}
    vars_temp = {}

    md_files = {}
    yaml_files = {}
    unkeyed_yaml_files = []

    if MD_GLOBS_KEY in data_block and data_block[MD_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating md data globs...")
        md_files.update(globs_to_dict(data_block[MD_GLOBS_KEY], filepath))
    if YAML_GLOBS_KEY in data_block and data_block[YAML_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating yaml data globs...")
        yaml_files.update(globs_to_dict(data_block[YAML_GLOBS_KEY], filepath))
    if YAML_GLOBS_UNKEYED_KEY in data_block and data_block[YAML_GLOBS_UNKEYED_KEY]:
        _LOGGER.info(f"MM | Populating unkeyed yaml globs...")
        tmp_files = globs_to_dict(data_block[YAML_GLOBS_UNKEYED_KEY], filepath)
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
                    data["_yaml"].update(yaml_dict)
                else:
                    data[k] = yaml_dict
                    data["_yaml"][k] = yaml_dict
                    vars_temp[k] = yaml_dict
                data["_raw"][k] = yaml.dump(yaml_dict)
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
        data["_md"][k] = p.content
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

    # Global vars behaves exactly like global frontmatter, except:
    # 1. It's all variables, not just those marked with frontmatter_*.
    # It's like what's in a main data array, except it includes metadata,
    # and excludes markdown content... Is that useful?
    data["_global_vars"] = vars_temp

    # Integrated, global frontmatter from 3 sources, in order:
    # .md frontmatter, yaml data named frontmatter_*, variables named frontmatter_*
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
        meta = {}
        # Old way would update based on root config:
        # meta.update(self.root_cfg)
        meta["_now"] = date.today().strftime("%s")
        meta["_today"] = date.today().strftime("%Y-%m-%d")
        meta["today"] = meta["_today"]  # TODO: Remove this
        meta["now"] = meta["_now"]  # TODO: Remove this

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
            if "inherit_from" in root_cfg["targets"][target_name]:
                inherit_from = root_cfg["targets"][target_name]["inherit_from"]
                if type(inherit_from) is not list:
                    inherit_from = [inherit_from]
                for base_target in inherit_from:
                    _LOGGER.info(f"Loading from base target: {base_target}")
                    meta = deep_update(meta, root_cfg["targets"][base_target])
            meta = deep_update(meta, root_cfg["targets"][target_name])
            _LOGGER.debug(f'Config for this target: {root_cfg["targets"][target_name]}')

        # del meta["targets"]
        meta["_cfg_file_path"] = root_cfg["_cfg_file_path"]
        if "version" in meta:
            del meta["version"]

        if vardata:
            cli_vars = {y[0]: y[1] for y in [x.split("=") for x in vardata]}
            meta.update(cli_vars)
        else:
            cli_vars = {}

        if not "command" in meta:
            # Generally, user should provide a `command`, but for simple default cases,
            # we can just route through pandoc as a default command.
            options_array = []
            if "latex_template" in meta:
                options_array.append('--template "{latex_template}"')
            if "output_file" in meta:
                options_array.append('--output "{output_file}"')
            options = " ".join(options_array)
            meta["command"] = f"pandoc {options}"

        _LOGGER.debug(f"meta: {meta}")
        self.meta = meta
        _LOGGER.debug(f"MM | Config file path: {self.meta['_cfg_file_path']}")
        if "output_file" in self.meta:
            _LOGGER.info(f"MM | Output file: {self.meta['output_file']}")


def build_side_targets(tgt, side_list_key="prebuild"):
    """
    Builds side targets for a target, which are prebuilds or postbuilds.

    Side targets accompany a target, are built either before (prebuild)
    or after (postbuild) a main target.

    @param tgt Target The main target to build
    @param side_list_key Iterable[str] The key of the target that contains a list of side targets. e.g. "prebuild" or "postbuild"
    """
    if side_list_key in tgt.meta:
        _LOGGER.info(f"MM | Run {side_list_key} for target: {tgt.target_name}")
        for side_tgt in tgt.meta[side_list_key]:
            _LOGGER.info(f"MM | {side_list_key} target: {side_tgt}")
            if side_tgt in self.cfg["targets"]:
                self.build_target(side_tgt)
            else:
                _LOGGER.warning(
                    f"MM | No target called {side_tgt}, requested prebuild by target {tgt}."
                )
                return False
    return True


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

        if tgt.meta["output_file"] and not "stopopen" in tgt.meta:
            return tgt.meta["output_file"]
        else:
            return False

    def build_target(self, target_name, print_only=False, vardump=False):

        tgt = Target(self.cfg, target_name)
        _LOGGER.info(f"MM | Building target: {tgt.target_name}")

        # First, run any pre-builds
        if not build_side_targets(tgt, "prebuild"):
            return False

        # Next, meld the inputs. This can be time-consuming, it reads data to populate variables
        tgt.melded_input = self.meld_inputs(tgt)
        _LOGGER.debug(f"Melded input: {tgt.melded_input}")
        if "loop" in tgt.meta:
            return self.build_target_in_loop(tgt, print_only, vardump)

        # Run command...
        result = self.run_command_for_target(tgt, print_only, vardump)

        # Finally, run any postbuilds
        if not build_side_targets(tgt, "postbuild"):
            return False

        return result

    def run_command_for_target(self, tgt, print_only, vardump=False):

        _LOGGER.info(f"File path for this target: {tgt.meta['_filepath']}")
        if "type" in tgt.meta and tgt.meta["type"] == "raw":
            # Raw = No subprocess stdin printing. (so, it doesn't render anything)
            cmd_fmt = format_command(tgt)
            tgt.melded_output = None
            tgt.returncode = run_cmd(cmd_fmt, None, tgt.meta["_filepath"])
        elif "type" in tgt.meta and tgt.meta["type"] == "meta":
            # Meta = No command, it's a meta-target used for prebuilds or something else
            tgt.melded_output = None
            tgt.returncode = 0
        elif print_only:
            # Case 2: print_only means just render but run no command.
            # return print(tpl.render(data))  # one time
            tgt.melded_output = self.render_template(tgt.melded_input, tgt)
            tgt.returncode = 0
        elif vardump:
            tgt.melded_output = tgt.melded_input
            tgt.returncode = 0
        elif tgt.meta["command"]:
            cmd_fmt = format_command(tgt)
            _LOGGER.debug(cmd_fmt)
            tgt.melded_output = self.render_template(tgt.melded_input, tgt)
            tgt.returncode = run_cmd(
                cmd_fmt, tgt.melded_output.encode(), tgt.meta["_filepath"]
            )
        return tgt

    def build_target_in_loop(self, tgt, print_only=False, vardump=False):
        #  Process each iteration of the loop
        melded_input = tgt.melded_input
        loop_data_var = tgt.meta["loop"]["loop_data"].split(".")
        _LOGGER.debug(f"Retrieve loop data variable named {loop_data_var}")
        loop_dat = recursive_get(melded_input, loop_data_var)
        _LOGGER.debug(f"Loop dat: {loop_dat}")
        _LOGGER.debug(f"Target melded_input: {tgt.melded_input}")
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_target_objects = {}
        for i in range(len(loop_dat)):
            loop_var_value = loop_dat[i]
            melded_input_copy = deepcopy(melded_input)
            tgt_copy = deepcopy(tgt)
            var = tgt_copy.meta["loop"]["assign_to"]
            _LOGGER.info(f"{var}: {loop_var_value}")
            tgt_copy.melded_input.update({var: loop_var_value})
            tgt_copy.meta.update({var: loop_var_value})
            _LOGGER.debug(tgt_copy.meta)
            # _LOGGER.debug(cmd_data)
            rendered_in = self.render_template(
                tgt_copy.melded_input, tgt_copy, double=False
            ).encode()
            return_target_objects[i] = self.run_command_for_target(
                tgt_copy, print_only, vardump
            )

        return return_target_objects

    def meld_inputs(self, tgt):
        # data_copy = deepcopy(tgt.root_cfg)
        # data_copy.update(tgt.meta)
        data_copy = deepcopy(tgt.meta)

        if "version" in tgt.root_cfg and not tgt.root_cfg["version"] >= 1:
            _LOGGER.error("Can't process this config version.")

        _LOGGER.info("MM | Processing config version 1...")
        if "data" in tgt.meta:
            processed_data_block = process_data(tgt.meta["data"], tgt.meta["_filepath"])
        else:
            processed_data_block = process_data({}, tgt.meta["_filepath"])
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

    def render_template(self, melded_input, target, double=None):
        # print(melded_input)
        if "data" not in melded_input:
            melded_input["data"] = {}
        if "md_template" in target.meta:
            _LOGGER.error(
                "Please update your config! 'md_template' was renamed to 'jinja_template'."
            )
            target.meta["jinja_template"] = target.meta["md_template"]

        if "jinja_template" in target.meta and target.meta["jinja_template"]:
            tpl = load_template(target.meta)
        else:
            # cmd_data["jinja_template"] = None
            tpl = Template(tpl_generic)
            _LOGGER.error(
                "No jinja_template provided. Using generic markmeld jinja_template."
            )

        if double is None:
            if (
                "recursive_render" in target.meta
                and not target.meta["recursive_render"]
            ):
                double = False
            else:
                # Recursive rendering allows your template to include variables
                double = True

        if double:
            return Template(tpl.render(melded_input)).render(melded_input)  # two times
        else:
            return tpl.render(melded_input)
