"""Command-line interface for markmeld.

This module provides the CLI entry point for markmeld, handling argument parsing,
target building, and output management. The CLI is accessed via the `mm` command.
"""

import argparse
import logmuse
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from ubiquerg import VersionInHelpParser

from .exceptions import ConfigError, TargetError
from .melder import MarkdownMelder
from .utilities import load_config_wrapper, get_file_open_cmd
from ._version import __version__
from .resource_manager import list_filters, get_filter_path

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


def build_argparser() -> argparse.ArgumentParser:
    """Build the argument parser for the markmeld CLI.

    Creates and configures an ArgumentParser with all markmeld command-line
    options including target selection, output modes, cache management,
    and filter listing.

    Returns:
        Configured argument parser ready for use.
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
        help="Initialize config file",
    )

    parser.add_argument(
        "--input",
        help="Override content source with an external file path",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Override output file path",
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

    # Cache management flags for Google Doc targets
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        default=False,
        help="Clear cached Google Docs before building (for google-doc targets)",
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        default=False,
        help="Force refresh from Google Drive, bypassing cache (for google-doc targets)",
    )

    parser.add_argument(
        "--cache-status",
        action="store_true",
        default=False,
        help="Show cache status for google-doc targets",
    )

    return parser


def main(test_args: Optional[Dict[str, Any]] = None) -> None:
    """Run the markmeld command-line interface.

    Main entry point for the `mm` command. Handles argument parsing,
    configuration loading, target building, and output display.

    Args:
        test_args: Optional dictionary of arguments for testing purposes.
            If provided, these override parsed command-line arguments.

    Raises:
        ConfigError: If config file is missing or invalid.
        TargetError: If target doesn't exist or has configuration issues.
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

    # Handle cache management for Google Doc targets
    if args.cache_status or args.clear_cache or args.force_refresh:
        from .melder import Target
        from .const import TARGET_TYPE_KEY, GOOGLE_DOC_TARGET_TYPE
        
        # Check if target is a google-doc type
        if args.target:
            tgt = Target(mm.cfg, args.target)
            if TARGET_TYPE_KEY in tgt.meta and tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE:
                from .google_drive import CloudCacheManager
                from .google_drive import GoogleDriveProcessor
                
                # Get google_docs dictionary from target configuration
                if "data" in tgt.meta and "google_docs" in tgt.meta["data"]:
                    google_docs = tgt.meta["data"]["google_docs"]
                    
                    # google_docs should now be a dictionary
                    if isinstance(google_docs, dict) and google_docs:
                        cache_manager = CloudCacheManager()
                        
                        if args.cache_status:
                            # Show cache status for all documents
                            for var_name, doc_id in google_docs.items():
                                if doc_id:
                                    cache_dir = cache_manager.get_cache_dir(doc_id, 'docs')
                                    if cache_dir.exists():
                                        _LOGGER.info(f"Cache exists for '{var_name}' document {doc_id}")
                                        _LOGGER.info(f"Cache location: {cache_dir}")
                                        # Check for cached files
                                        cached_files = list(cache_dir.glob("*.md"))
                                        if cached_files:
                                            _LOGGER.info(f"Cached documents: {len(cached_files)}")
                                            for f in cached_files:
                                                _LOGGER.info(f"  - {f.name}")
                                    else:
                                        _LOGGER.info(f"No cache found for '{var_name}' document {doc_id}")
                            sys.exit(0)
                        
                        if args.clear_cache:
                            # Clear cache for all documents
                            for var_name, doc_id in google_docs.items():
                                if doc_id:
                                    _LOGGER.info(f"Clearing cache for '{var_name}' document {doc_id}")
                                    doc_cache_root = cache_manager.cache_root / doc_id
                                    if doc_cache_root.exists():
                                        import shutil
                                        shutil.rmtree(doc_cache_root)
                                        _LOGGER.info(f"Cache cleared successfully for '{var_name}'")
                                    else:
                                        _LOGGER.info(f"No cache to clear for '{var_name}'")
                        
                        if args.force_refresh:
                            # Set flag to bypass cache
                            _LOGGER.info("Force refresh enabled - will bypass cache")
                            # This will be handled in preprocess_google_doc
                            tgt.meta["force_refresh"] = True
            else:
                if args.cache_status or args.clear_cache or args.force_refresh:
                    _LOGGER.warning("Cache management flags only work with google-doc targets")

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
        args.target,
        print_only=args.print,
        vardump=args.dump,
        report=False,
        input_file=args.input,
        output_file=args.output,
        vardata=args.vars,
    )

    # Check if build failed before attempting to use built_target
    if built_target is None:
        _LOGGER.error("Build failed. Check error messages above for details.")
        sys.exit(1)

    if args.dump:
        import json

        _LOGGER.info("Dumping JSON output passed to jinja template...")
        if isinstance(built_target, dict):  # Multi-output target
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
        if isinstance(built_target, dict):  # Multi-output target
            for i, tgt in built_target.items():
                _LOGGER.info(f"\n\nOutput {i}:")
                _LOGGER.info(tgt.melded_output)
        else:
            print(built_target.melded_output)

    # Report results using the Target's report method
    if isinstance(built_target, dict):
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
