# tpl_generic = """
# {{ data }}
# """

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
        loop_dat = recursive_get(data, cmd_data["loop"]["loop_data"].split("."))
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_codes = []
        for i in loop_dat:
            var = cmd_data["loop"]["assign_to"]
            _LOGGER.info(f"{var}: {i}")
            data.update({var: i})
            cmd_data.update({var: i})
            _LOGGER.debug(cmd_data)
            return_codes.append(
                meld_output(
                    data, deepcopy(cmd_data), cfg, print_only=args.print, in_loop=True
                )
            )

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


if not "version" in tgt.root_cfg or tgt.root_cfg["version"] < 1:
    _LOGGER.info("MM | Processing config version 0...")
    data_copy["yaml"] = {}
    data_copy["raw"] = {}
    data_copy["md"] = {}
    data_copy = populate_data_md_globs(tgt.meta, data_copy)
    data_copy = populate_data_yaml(tgt.meta, data_copy)
    data_copy = populate_data_yaml_keyed(tgt.meta, data_copy)
    data_copy = populate_data_md(tgt.meta, data_copy)
    if "data_variables" in tgt.meta:
        data_copy.update(tgt.meta["data_variables"])
