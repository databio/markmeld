import argparse
import datetime
import frontmatter
import jinja2
import logmuse
import os
import subprocess
import sys
import time
import yaml

from datetime import date
from jinja2 import Template
from jinja2.filters import FILTERS, environmentfilter
from logging import getLogger
from ubiquerg import VersionInHelpParser

from ._version import __version__

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


def load_config_file(filepath):
    """
    Loads a configuration file.

    @param filepath Path to configuration file to load
    @return Loaded yaml data object.
    """

    with open(filepath, "r") as f:
        cfg_data = f.read()

    return load_config_data(cfg_data)


def load_config_data(cfg_data):
    cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    return cfg


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
        _LOGGER.info(f"MM | --> {k}")
        p = frontmatter.load(v)
        data[k] = p.__dict__
        data["md"][k] = p.__dict__
        data[k]["all"] = frontmatter.dumps(p)
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

        for file in files:
            k = os.path.splitext(os.path.basename(file))[0]
            _LOGGER.info(f"MM | {k}:{file}")
            p = frontmatter.load(file)
            data[k] = p.__dict__
            data["md"][k] = p.__dict__
            data[k]["all"] = frontmatter.dumps(p)
            if len(p.metadata) > 0:
                data[k]["metadata_yaml"] = yaml.dump(p.metadata)
    return data


def load_template(cfg):
    if "md_template" not in cfg:
        return None
    with open(cfg["md_template"], "r") as f:
        x = f.read()
    t = Template(x)
    return t


def meld(args, data, cmd_data, cfg):
    """
    Melds input markdown and yaml into a jinja output.
    """

    if "md_template" in cmd_data:
        t = load_template(cmd_data)
    else:
        cmd_data["md_template"] = None

    if 'latex_template' not in cmd_data:
        cmd_data["latex_template"] = None

    _LOGGER.info(f"MM | Today's date: {cmd_data['today']}")
    _LOGGER.info(f"MM | latex_template: {cmd_data['latex_template']}")
    _LOGGER.info(f"MM | Output file: {cmd_data['output_file']}")
    _LOGGER.info(f"MM | Output md_template: {cmd_data['md_template']}")

    def call_hook(cmd_data, tgt):
        if tgt in mm_targets:
            cmd = mm_targets[tgt].format(**cmd_data)
            _LOGGER.info(f"MM | Command: {cmd}")
            p = subprocess.Popen(cmd, shell=True)
            return p.communicate()
        elif tgt in cmd_data["targets"]:
            return meld(args, data, populate_cmd_data(cfg, tgt), cfg)
        else:
            _LOGGER.warning(f"MM | No target called {tgt}.")
            return False

    if "prebuild" in cmd_data:
        # prebuild hooks
        for tgt in cmd_data["prebuild"]:
            _LOGGER.info(f"MM | Run prebuild hooks: {tgt}")
            call_hook(cmd_data, tgt)
    if args.print:
        # return print(t.render(data))  # one time
        return print(Template(t.render(data)).render(data))  # two times
    elif cmd_data["md_template"]:
        cmd = cmd_data["command"]
        cmd_fmt = cmd.format(**cmd_data)
        _LOGGER.info(cmd_fmt)
        # Call command (pandoc), passing the rendered template to stdin
        p = subprocess.Popen(cmd_fmt, shell=True, stdin=subprocess.PIPE)
        # p.communicate(input=t.render(data).encode())
        p.communicate(input=Template(t.render(data)).render(data).encode())

    if "postbuild" in cmd_data:
        # postbuild hooks
        for tgt in cmd_data["postbuild"]:
            _LOGGER.info(f"MM | Run postbuild hooks: {tgt}")
            call_hook(cmd_data, tgt)

    return True


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

    if vardata:
        cli_vars = {y[0]: y[1] for y in [x.split("=") for x in vardata]}
        cmd_data.update(cli_vars)
    else:
        cli_vars = {}

    if not "command" in cmd_data:
        # default command
        cmd_data[
            "command"
        ] = """pandoc \
             --template {latex_template} \
             -o {output_file}"""

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

    # Add custom date formatter filter
    FILTERS["date"] = datetimeformat
    data["now"] = date.today().strftime("%s")

    # Set up cmd_data object
    cmd_data = populate_cmd_data(cfg, args.target, args.vars)

    # all the data goes into a big dict, with markdown data under a '.content' attribute
    # for the file name
    # use this to populate the template.

    data = populate_data_md_globs(cmd_data, data)
    data = populate_yaml_data(cmd_data, data)
    data = populate_md_data(cmd_data, data)
    if "data_variables" in cmd_data:
        data.update(cmd_data["data_variables"])

    if "output_file" in cmd_data:
        cmd_data["output_file"] = cmd_data["output_file"].format(**cmd_data)
    else:
        cmd_data["output_file"] = None

    # Meld it!
    meld(args, data, cmd_data, cfg)

    # Open the file
    if cmd_data["output_file"] and not "stopopen" in cmd_data:
        cmd_open = ["xdg-open", cmd_data["output_file"]]
        _LOGGER.info(" ".join(cmd_open))
        subprocess.call(cmd_open)

    return


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
