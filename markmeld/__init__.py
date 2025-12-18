"""
Markmeld: A markdown melder for document generation.

Markmeld merges YAML and markdown content using Jinja2 templates to produce
polished documents like resumes, proposals, manuscripts, and more.
"""

import sys

from .melder import MarkdownMelder
from .cli import main
from .utilities import load_config_file, load_config_wrapper
from .document_checker import DocumentChecker, FigureReference, ValidationIssue

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
    from .google_drive import GoogleDriveProcessor
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
