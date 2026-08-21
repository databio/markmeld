"""Command-line interface for markmeld.

This module provides the CLI entry point for markmeld, handling argument parsing,
target building, and output management. The CLI is accessed via the `mm` command.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import logmuse
from ubiquerg import VersionInHelpParser

from . import __version__
from .exceptions import ConfigError, TargetError
from .melder import MarkdownMelder
from .resource_manager import get_filter_path, list_filters
from .utilities import get_file_open_cmd, load_config_wrapper

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
        help="Force refresh from remote sources, bypassing cache (Google Doc and authormark targets)",
    )

    parser.add_argument(
        "--cache-status",
        action="store_true",
        default=False,
        help="Show cache status for google-doc targets",
    )

    return parser


def build_csv2pdf_argparser() -> argparse.ArgumentParser:
    """Build the argument parser for the `mm csv2pdf` subcommand."""
    parser = argparse.ArgumentParser(
        prog="mm csv2pdf",
        description="Render a CSV file as a styled PDF table.",
    )
    parser.add_argument("input", help="Input CSV file path")
    parser.add_argument("output", help="Output PDF file path")
    parser.add_argument(
        "-w",
        "--width",
        help="Page width (e.g. 174mm, or 'auto')",
    )
    parser.add_argument(
        "--height",
        help="Page height (e.g. 50mm, or 'auto'; default auto-fits content)",
    )
    parser.add_argument(
        "-f",
        "--font-size",
        help="Font size (e.g. 6pt or 6)",
    )
    parser.add_argument(
        "--col-names",
        help="Comma-separated column header overrides",
    )
    parser.add_argument(
        "--col-widths",
        help="Comma-separated column width percentages (e.g. 20,30,50)",
    )
    parser.add_argument(
        "--col-align",
        help="Comma-separated column alignments (e.g. left,center,right)",
    )
    parser.add_argument(
        "--padding-v",
        help="Vertical cell padding in pixels",
    )
    parser.add_argument(
        "--padding-h",
        help="Horizontal cell padding in pixels",
    )
    return parser


def csv2pdf_main(argv) -> int:
    """Run the `mm csv2pdf` subcommand: render a CSV as a styled PDF table.

    Maps CLI arguments to the parameter names used in markdown figure syntax,
    then calls the same `prepare_table_parameters` / `df_to_pdf` pipeline used
    during document builds.
    """
    import pandas as pd

    from .figure_conversion import df_to_pdf, prepare_table_parameters

    parser = build_csv2pdf_argparser()
    args = parser.parse_args(argv)

    logmuse.init_logger(name="markmeld", level="INFO", devmode=True)

    params: dict[str, Any] = {}
    if args.width is not None:
        params["fig_width"] = args.width
    if args.height is not None:
        params["fig_height"] = args.height
    if args.font_size is not None:
        params["font-size"] = args.font_size
    if args.col_names is not None:
        params["col-names"] = args.col_names
    if args.col_widths is not None:
        params["col-widths"] = args.col_widths
    if args.col_align is not None:
        params["col-align"] = args.col_align
    if args.padding_v is not None:
        params["padding-v"] = args.padding_v
    if args.padding_h is not None:
        params["padding-h"] = args.padding_h

    df = pd.read_csv(args.input)
    table_params = prepare_table_parameters(params, df)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_to_pdf(df, str(output_path), **table_params)

    print(f"Wrote {output_path}")
    return 0


def main(test_args: dict[str, Any] | None = None) -> None:
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
    if test_args is None and len(sys.argv) > 1 and sys.argv[1] == "csv2pdf":
        sys.exit(csv2pdf_main(sys.argv[2:]))

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
            raise TargetError("No targets specified in config.")
        for t, k in cfg["targets"].items():
            if "abstract" in cfg["targets"][t]:
                continue
            sys.stdout.write(t + " ")
        sys.exit(0)

    if not args.target and not args.list:
        if "targets" not in cfg:
            raise TargetError("No targets specified in config.")
        tarlist = [x for x, k in cfg["targets"].items()]
        tarlist_txt = ", ".join(sorted(tarlist))
        _LOGGER.error(f"Targets: {tarlist_txt}.")
        sys.exit(0)
    if args.list:
        if "targets" not in cfg:
            raise TargetError("No targets specified in config.")

        tarlist = {}
        for t, k in cfg["targets"].items():
            if "abstract" in cfg["targets"][t]:
                continue
            tarlist[t] = k["description"] if "description" in k else "---"
        _LOGGER.error("Targets:")
        for k, v in tarlist.items():
            _LOGGER.error(f"  {k}: {v}")
        sys.exit(0)

    _LOGGER.debug("Melding...")  # Meld it!
    mm = MarkdownMelder(cfg)

    # Handle cache management for Google Doc targets
    if args.cache_status or args.clear_cache or args.force_refresh:
        from .const import GOOGLE_DOC_TARGET_TYPE, TARGET_TYPE_KEY
        from .melder import Target

        # Check if target is a google-doc type
        if args.target:
            tgt = Target(mm.cfg, args.target)
            if TARGET_TYPE_KEY in tgt.meta and tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE:
                from .google_drive import CloudCacheManager

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
                                    cache_dir = cache_manager.get_cache_dir(doc_id, "docs")
                                    if cache_dir.exists():
                                        _LOGGER.info(
                                            f"Cache exists for '{var_name}' document {doc_id}"
                                        )
                                        _LOGGER.info(f"Cache location: {cache_dir}")
                                        # Check for cached files
                                        cached_files = list(cache_dir.glob("*.md"))
                                        if cached_files:
                                            _LOGGER.info(f"Cached documents: {len(cached_files)}")
                                            for f in cached_files:
                                                _LOGGER.info(f"  - {f.name}")
                                    else:
                                        _LOGGER.info(
                                            f"No cache found for '{var_name}' document {doc_id}"
                                        )
                            sys.exit(0)

                        if args.clear_cache:
                            # Clear cache for all documents
                            for var_name, doc_id in google_docs.items():
                                if doc_id:
                                    _LOGGER.info(
                                        f"Clearing cache for '{var_name}' document {doc_id}"
                                    )
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
                # --force-refresh applies to any remote source (google-doc and
                # authormark) and is propagated to build_target separately, so
                # only the cache-status/clear-cache flags are google-doc-only.
                if args.cache_status or args.clear_cache:
                    _LOGGER.warning("Cache status/clear flags only work with google-doc targets")

    if args.explain:
        mm.describe_target(args.target)
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
        force_refresh=args.force_refresh,
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
                _LOGGER.info(json.dumps(tgt.melded_output, sort_keys=True, indent=2, default=str))
        else:
            print(json.dumps(built_target.melded_output, sort_keys=True, indent=2, default=str))

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
            and "stopopen" not in built_target.meta
            and not args.print
            and not args.dump
        ):
            file_open_cmd = get_file_open_cmd()
            cmd_open = [file_open_cmd, built_target.meta["output_file"]]
            _LOGGER.info(" ".join(cmd_open))
            subprocess.call(cmd_open)

    return
