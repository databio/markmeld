"""Constants used throughout the markmeld package."""

PKG_NAME = "markmeld"

# Platform-specific file opener commands
# https://stackoverflow.com/a/1857/13175187
FILE_OPENER_MAP = {"Linux": "xdg-open", "Darwin": "open", "Windows": "start"}

# Google Doc target type constants
GOOGLE_DOCS_KEY = "google_docs"
TARGET_TYPE_KEY = "type"
GOOGLE_DOC_TARGET_TYPE = "google-doc"
