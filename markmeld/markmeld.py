import datetime
import frontmatter
import jinja2
import logmuse
import os
import subprocess
import yaml

from datetime import date
from jinja2 import Template
from logging import getLogger
from ubiquerg import VersionInHelpParser

from ._version import __version__

PKG_NAME = "markmeld"

_LOGGER = getLogger(PKG_NAME)

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
        required=True
    )

    return parser

def load_config_file(filepath):
    """
    Loads a configuration file.

    @param filepath Path to configuration file to load
    @return Loaded yaml data object.
    """

    with open(filepath, 'r') as f:
        cfg_data = f.read()

    return (load_config_data(cfg_data))


def load_config_data(cfg_data):
    cfg = yaml.load(cfg_data, Loader=yaml.SafeLoader)
    return cfg


def populate_yaml_data(cfg, data):
    # Load up yaml data
    _LOGGER.info(f"MM | Populating yaml data...")
    for d in cfg["data_yaml"]:
        _LOGGER.info(f"MM | {d}")
        with open(d, 'r') as f:
            data.update(yaml.load(f, Loader=yaml.SafeLoader))

    return data


def populate_md_data(cfg, data):
    # Load up markdown data
    _LOGGER.info(f"MM | Populating md data...")
    for k,v in cfg["data_md"].items():
        _LOGGER.info(f"MM | {k}")
        data[k] = frontmatter.load(v).__dict__
        data["md"][k] = frontmatter.load(v).__dict__

    return data

def populate_data_md_globs(cfg, data):
    import glob
    if 'data_md_globs' not in cfg:
        return data
    _LOGGER.info(f"MM | Populating md data globs...")
    for d in cfg["data_md_globs"]:
        g = glob.glob(d)

        for f in g:
            k = os.path.splitext(os.path.basename(f))[0]
            _LOGGER.info(f"MM | {k}:{f}")
            data[k] = frontmatter.load(f).__dict__
            data["md"][k] = frontmatter.load(f).__dict__

    return data

def load_template(cfg):
    with open(cfg["md_template"], 'r') as f:
        x= f.read()
    t = Template(x)
    return t

def main():

    parser = logmuse.add_logging_options(build_argparser())
    args, _ = parser.parse_known_args()

    global _LOGGER
    _LOGGER = logmuse.logger_via_cli(args, make_root=True)

    data = {"md": {}}
    cfg = load_config_file(args.config)
    # cfg = load_config_data(cfg_data)

    # all the data goes into a big dict, with markdown data under a '.content' attribute
    # for the file name
    # use this to populate the template.

    data = populate_yaml_data(cfg, data)
    data = populate_md_data(cfg, data)
    data = populate_data_md_globs(cfg, data)
    if 'data_variables' in cfg:
        data.update(cfg["data_variables"])

    t = load_template(cfg)

    today = date.today().strftime("%Y-%m-%d")
    file = cfg["output_file"].format(today=today)


    _LOGGER.info(f"MM | Today's date: {today}")
    _LOGGER.info(f"MM | latex_template: {cfg['latex_template']}")
    _LOGGER.info(f"MM | Output file: {file}")


    print(t.render(data))

    cmd_pandoc = f"pandoc \
        --template {latex_template} \
        -o {file}"
    cmd_pandoc

    # Call pandoc, passing the rendered template to stdin
    p = subprocess.Popen(cmd_pandoc, shell=True, stdin=subprocess.PIPE)
    p.communicate(input=t.render(data).encode())

    # Open the file
    return subprocess.call(["xdg-open", file])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
