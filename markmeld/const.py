"""Constants used throughout the markmeld package."""

PKG_NAME = "markmeld"

# Platform-specific file opener commands
# https://stackoverflow.com/a/1857/13175187
FILE_OPENER_MAP = {"Linux": "xdg-open", "Darwin": "open", "Windows": "start"}

# Google Doc target type constants
GOOGLE_DOCS_KEY = "google_docs"
TARGET_TYPE_KEY = "type"
GOOGLE_DOC_TARGET_TYPE = "google-doc"

# Section-extraction constants (lift a body heading into a template variable)
EXTRACT_SECTIONS_KEY = "extract_sections"
EXTRACT_TITLE_KEY = "extract_title"

# Authormark author-block source constants
AUTHORMARK_KEY = "authormark"
AUTHORMARK_BASE_URL_KEY = "authormark_base_url"
AUTHORMARK_BASE_URL_ENV = "MM_AUTHORMARK_BASE_URL"
# Default authormark host (the deployed public capability-URL API).
AUTHORMARK_DEFAULT_BASE_URL = "https://authormark.databio.org"

# Target-config keys an authormark payload's `metadata:` block may set.
# Deliberately narrow: the payload comes from a remote service, and keys
# like `command`, `prebuild`, and `postbuild` are executed as subprocesses.
AUTHORMARK_ALLOWED_META_KEYS = frozenset(
    {
        EXTRACT_TITLE_KEY,
        EXTRACT_SECTIONS_KEY,
    }
)

# Sub-directory of the cache root holding project-level files shared by every
# target, such as the Drive bibliography (`<cache_root>/_project/bib/`).
PROJECT_CACHE_SUBDIR = "_project"

# Target key naming where the `bibliography` file comes from. markmeld acts only on
# BIB_SOURCE_GDRIVE; other values (e.g. sciquill's "lumenoia") are ignored.
BIB_SOURCE_KEY = "bib_source"
BIB_SOURCE_GDRIVE = "gdrive"
