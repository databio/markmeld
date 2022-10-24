
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

from .utilities import format_command, recursive_get, run_cmd 
from .utilities import *

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
{{ data }}
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
        if is_url(v):  # Do url stuff
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


def resolve_globs(globs, cfg_path):
    return_items = {}
    for item in globs:
        path = os.path.join(os.path.dirname(cfg_path), item)
        _LOGGER.info(f"MM | Glob path: {path}")
        files = glob.glob(path)
        for file in files:
            k = os.path.splitext(os.path.basename(file))[0]
            _LOGGER.info(f"MM | [key:value] {k}:{file}")
            return_items[k] = file
    return return_items

def process_data_block(data_block, cfg):
    _LOGGER.info(f"MM | Processing data block...")
    data = {"md":{}, "md_raw": {}, "yaml":{}, "yaml_raw": {}}  # Initialize return value
    md_files = {}
    yaml_files = {}
    if "md_globs" in data_block:
        _LOGGER.info(f"MM | Populating md data globs...")
        md_files.update(resolve_globs(data_block["md_globs"], cfg["_cfg_file_path"]))
    if "yaml_globs" in data_block:
        _LOGGER.info(f"MM | Populating yaml data globs...")
        yaml_files.update(resolve_globs(data_block["yaml_globs"], cfg["_cfg_file_path"]))
    if "md" in data_block:
        md_files.update(data_block["md"])
    if "yaml" in data_block:
        yaml_files.update(data_block["yaml"])

    for k,v in yaml_files.items():
        _LOGGER.info(f"MM | Processing yaml file {k}: {v}")
        vabs = make_abspath(v, cfg)
        if not os.path.exists(vabs):
        	_LOGGER.error(f"File not found: {vabs}")
        else:
            with open(vabs, "r") as f:
                yaml_dict = yaml.load(f, Loader=yaml.SafeLoader)
                print(yaml_dict)
                # data[k] = yaml_dict
                data["yaml"][k] = yaml_dict
                data["yaml_raw"][k] = yaml.dump(yaml_dict)
                # 2022-08-12 Original way: data[k]["raw"] = yaml.dump(yaml_dict)
                # But this doesn't work in the case that data[k] is a list 
                # (if the yaml file is an array, not an object)
                # So I changed it put the raw value under ["raw"][k] instead of [k]["raw"]

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
            vabs = make_abspath(v, cfg)
            if os.path.exists(vabs):
                p = frontmatter.load(vabs)
            else:
                _LOGGER.warning(f"Skipping file that does not exist: {vabs}")
                # data[k] = {}
                data["md"][k] = {}  # Populate array with empty values
                # data[k]["all"] = ""
                data["md_all"][k] = {}
                continue
        data["md"][k] = p.__dict__
        data["md_all"]  = frontmatter.dumps(p)
        # data["md_dict"][k] = p.__dict__
        # data[k]["all"] = frontmatter.dumps(p)
        _LOGGER.debug(data[k])
        if len(p.metadata) > 0:
            # data[k]["metadata_yaml"] = yaml.dump(p.metadata)
            data["md_metadata"] = yaml.dump(p.metadata)

    if "variables" in data_block:
        data.update(data_block["variables"])

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
    if "jinja_template" not in cfg or not cfg["jinja_template"]:
        return None

    md_tpl = None
    root = cfg["mm_templates"] if "mm_templates" in cfg else None
    md_tpl = make_abspath(cfg["jinja_template"], cfg, root)

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
    Holds 2 dicts: real data and metadata for a target
    """
    def __init__(self, data={}, target_name=None):
        self.data = data
        self.data["now"] = date.today().strftime("%s")
        self.target_name = target_name
        self.target_meta = populate_cmd_data(self.data, target_name)
        # I feel like this shouldn't be necessary...
        self.target_meta["_filepath"] = self.data["_cfg_file_path"]
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
            _LOGGER.debug(tgt.target_meta)
            tgt.returncode = run_cmd(cmd_fmt, melded_output, tgt.target_meta["_filepath"])

        return tgt

    def build_target_in_loop(self, tgt, melded_input, print_only=False):
        #  Process each iteration of the loop
        loop_dat = recursive_get(melded_input,tgt.target_meta["loop"]["loop_data"].split("."))
        _LOGGER.debug(loop_dat)
        _LOGGER.debug(tgt.data)
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

        if not "version" in data_copy:
            data_copy["yaml"] = {}
            data_copy["raw"] = {}
            data_copy = populate_data_md_globs(target.target_meta, data_copy)
            data_copy = populate_yaml_data(target.target_meta, data_copy)
            data_copy = populate_yaml_keyed(target.target_meta, data_copy)
            data_copy = populate_md_data(target.target_meta, data_copy)
            if "data_variables" in target.target_meta:
                data_copy.update(target.target_meta["data_variables"])
        elif data_copy["version"] == 2:
            print("V2")
            processed_data_block = process_data_block(target.target_meta["data"], data_copy)
            print("processed_data_block", processed_data_block)
            data_copy.update(processed_data_block)

        return data_copy

    def render_template(self, melded_input, target, double=True):
        # print(melded_input)
        if "data" not in melded_input:
            melded_input["data"] = {}
        if "md_template" in target.target_meta:
            _LOGGER.error("Please update your config! 'md_template' was renamed to 'jinja_template'.")
            target.target_meta['jinja_template'] = target.target_meta['md_template']

        if "jinja_template" in target.target_meta and target.target_meta["jinja_template"]:
            print(target.target_meta)
            tpl = load_template(target.target_meta)
        else:
            # cmd_data["jinja_template"] = None
            tpl = Template(tpl_generic)
            _LOGGER.error("No jinja_template provided. Using generic markmeld jinja_template.")
        if double:
            return Template(tpl.render(melded_input)).render(melded_input)  # two times
        else:
            return tpl.render(melded_input)


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

