"""
Markmeld: A markdown melder for document generation.

Markmeld merges YAML and markdown content using Jinja2 templates to produce
polished documents like resumes, proposals, manuscripts, and more.
"""

import sys

__version__ = "0.4.0-dev4"

from .cli import main
from .document_checker import DocumentChecker, FigureReference, ValidationIssue
from .melder import MarkdownMelder
from .utilities import load_config_file, load_config_wrapper

__all__ = [
    "MarkdownMelder",
    "load_config_file",
    "load_config_wrapper",
    "DocumentChecker",
    "FigureReference",
    "ValidationIssue",
]

# Optional Google Drive functionality
try:
    from .google_drive import GoogleDriveProcessor  # noqa: F401

    __all__.append("GoogleDriveProcessor")
except ImportError:
    # Google dependencies not installed
    pass

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
