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
