import argparse
from ubiquerg import VersionInHelpParser

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
