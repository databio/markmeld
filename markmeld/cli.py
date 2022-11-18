import argparse
import logmuse
import os
import subprocess
import sys

from ubiquerg import VersionInHelpParser

from .exceptions import *
from .melder import MarkdownMelder
from .utilities import load_config_file
from ._version import __version__


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
        "-l",
        "--list",
        action="store_true",
        default=False,
        help="List targets with descriptions",
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
        "-d",
        "--dump",
        action="store_true",
        default=False,
        help="Dump content object as passed to jinja2.",
    )

    parser.add_argument(
        "-v",
        "--vars",
        nargs="+",
        default=None,
        help="Extra key=value variable pairs",
    )

    return parser


def main(test_args=None):
    """
    Main command-line interface function
    """
    parser = logmuse.add_logging_options(build_argparser())
    args, _ = parser.parse_known_args()
    if test_args:
        args.__dict__.update(test_args)
    global _LOGGER
    _LOGGER = logmuse.logger_via_cli(args, make_root=True)

    if not args.config:
        if os.path.exists("_markmeld.yaml"):
            args.config = "_markmeld.yaml"
        else:
            msg = "You must provide config file or be in a dir with _markmeld.yaml."
            _LOGGER.error(msg)
            raise ConfigError(msg)

    cfg = load_config_file(args.config, None, args.autocomplete)

    if args.autocomplete:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        for t, k in cfg["targets"].items():
            sys.stdout.write(t + " ")
        sys.exit(0)

    if not args.target and not args.list:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        tarlist = [x for x, k in cfg["targets"].items()]
        tarlist_txt = ", ".join(tarlist)
        _LOGGER.error(f"Targets: {tarlist_txt}.")
        sys.exit(0)
    if args.list:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        tarlist = {
            x: k["description"] if "description" in k else "No description"
            for x, k in cfg["targets"].items()
        }
        _LOGGER.error(f"Targets:")
        for k, v in tarlist.items():
            _LOGGER.error(f"  {k}: {v}")
        sys.exit(0)

    _LOGGER.debug("Melding...")  # Meld it!
    mm = MarkdownMelder(cfg)
    built_target = mm.build_target(
        args.target, print_only=args.print, vardump=args.dump
    )

    if args.print | args.dump:
        print(built_target.melded_output)

    # Open the file
    if (
        "output_file" in built_target.target_meta
        and built_target.target_meta["output_file"]
    ):
        output_file = built_target.target_meta["output_file"]
    else:
        output_file = None
    if (
        built_target.returncode == 0
        and output_file
        and not "stopopen" in built_target.target_meta
        and not args.print
        and not args.dump
    ):
        cmd_open = ["xdg-open", output_file]
        _LOGGER.info(" ".join(cmd_open))
        subprocess.call(cmd_open)
    else:
        _LOGGER.info(f"Return code: {built_target.returncode}")

    return
