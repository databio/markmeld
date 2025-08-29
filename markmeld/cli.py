import argparse
import logmuse
import os
import subprocess
import sys

from ubiquerg import VersionInHelpParser

from .exceptions import *
from .melder import MarkdownMelder
from .utilities import load_config_wrapper, get_file_open_cmd
from ._version import __version__
from .filter_manager import list_filters, get_filter_path, validate_filter_name

tpl = """imports: null
version: 1
targets:
  target_name:
    jinja_template: null
    output_file: "{today}.pdf"
    data:
      md_files: null
      md_globs: null
      yaml_files: null
      yaml_globs: null
      variables: null
"""


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
        "-i",
        "--init",
        dest="init",
        metavar="I",
        nargs="?",
        const="_markmeld.yaml",
        help="Initilize config file",
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
        "-d",
        "--dump",
        action="store_true",
        default=False,
        help="Dump content object as passed to jinja2.",
    )

    parser.add_argument(
        "-e",
        "--explain",
        action="store_true",
        default=False,
        help="Explain parameters of a target instead of building it.",
    )

    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        default=False,
        help="Print output of jinja template instead of piping it to command (pandoc).",
    )

    parser.add_argument(
        "-t",
        "--template",
        action="store_true",
        default=False,
        help="Show the template that will be used for this recipe.",
    )

    parser.add_argument(
        "-v",
        "--vars",
        nargs="+",
        default=None,
        help="Extra key=value variable pairs",
    )

    parser.add_argument(
        "-f",
        "--filters",
        dest="filters",
        metavar="FILTER",
        nargs="?",
        const="__list__",
        help="List available filters or get path to specific filter",
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

    # Handle filter commands
    if args.filters is not None:
        if args.filters == "__list__":
            # List all available filters
            filters = list_filters()
            if filters:
                _LOGGER.info("Available filters:")
                for filter_name in filters:
                    _LOGGER.info(f"  {filter_name}")
            else:
                _LOGGER.info("No filters found")
        else:
            # Get path to specific filter
            filter_path = get_filter_path(args.filters)
            if filter_path:
                # Just print the path, nothing else
                print(filter_path)
            else:
                _LOGGER.error(f"Filter '{args.filters}' not found")
                available = list_filters()
                if available:
                    _LOGGER.error(f"Available filters: {', '.join(available)}")
                sys.exit(1)
        sys.exit(0)

    if args.init:
        global tpl
        _LOGGER.info(f"Initializing config file at: {args.init}")
        if os.path.exists(args.init):
            msg = "File already exists! Won't initialize."
            raise ConfigError(msg)
        with open(args.init, "w") as f:
            f.write(tpl)
        _LOGGER.info(f"File initialized to:\n{tpl}")
        sys.exit(0)

    if not args.config:
        if os.path.exists("_markmeld.yaml"):
            args.config = "_markmeld.yaml"
        else:
            msg = "You must provide config file or be in a dir with _markmeld.yaml."
            _LOGGER.error(msg)
            raise ConfigError(msg)

    cfg = load_config_wrapper(args.config, None, args.autocomplete)

    if args.autocomplete:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        for t, k in cfg["targets"].items():
            if "abstract" in cfg["targets"][t]:
                continue
            sys.stdout.write(t + " ")
        sys.exit(0)

    if not args.target and not args.list:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")
        tarlist = [x for x, k in cfg["targets"].items()]
        tarlist_txt = ", ".join(sorted(tarlist))
        _LOGGER.error(f"Targets: {tarlist_txt}.")
        sys.exit(0)
    if args.list:
        if "targets" not in cfg:
            raise TargetError(f"No targets specified in config.")

        tarlist = {}
        for t, k in cfg["targets"].items():
            if "abstract" in cfg["targets"][t]:
                continue
            tarlist[t] = k["description"] if "description" in k else "---"
        _LOGGER.error(f"Targets:")
        for k, v in tarlist.items():
            _LOGGER.error(f"  {k}: {v}")
        sys.exit(0)

    _LOGGER.debug("Melding...")  # Meld it!
    mm = MarkdownMelder(cfg)

    if args.explain:
        explained_target = mm.describe_target(args.target)
        sys.exit(0)

    if args.template:
        from .melder import Target, load_template

        tgt = Target(mm.cfg, args.target)
        tpl = load_template(tgt.meta)
        _LOGGER.info("Template content:")
        _LOGGER.info(tpl.source)
        sys.exit(0)

    built_target = mm.build_target(
        args.target, print_only=args.print, vardump=args.dump, report=False
    )

    if args.dump:
        import json

        _LOGGER.info("Dumping JSON output passed to jinja template...")
        if type(built_target) == dict:  # Multi-output target
            for i, tgt in built_target.items():
                _LOGGER.info(f"\n\nOutput {i}:")
                _LOGGER.info(
                    json.dumps(tgt.melded_output, sort_keys=True, indent=2, default=str)
                )
        else:
            print(
                json.dumps(
                    built_target.melded_output, sort_keys=True, indent=2, default=str
                )
            )

    if args.print:
        if type(built_target) == dict:  # Multi-output target
            for i, tgt in built_target.items():
                _LOGGER.info(f"\n\nOutput {i}:")
                _LOGGER.info(tgt.melded_output)
        else:
            print(built_target.melded_output)

    # Report results using the Target's report method
    if type(built_target) == dict:
        # Multi-output target
        for i, tgt in built_target.items():
            tgt.report(print_output=args.print, dump_output=args.dump)
    else:
        built_target.report(print_output=args.print, dump_output=args.dump)
        
        # Handle file opening (keep this in CLI only)
        if (
            built_target.returncode == 0
            and "output_file" in built_target.meta 
            and built_target.meta["output_file"]
            and not "stopopen" in built_target.meta
            and not args.print
            and not args.dump
        ):
            file_open_cmd = get_file_open_cmd()
            cmd_open = [file_open_cmd, built_target.meta["output_file"]]
            _LOGGER.info(" ".join(cmd_open))
            subprocess.call(cmd_open)

    return
