import datetime
import frontmatter
import jinja2
import os
import re
import sys
import time
import yaml
from pathlib import Path

from copy import deepcopy
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from datetime import date
from jinja2 import Template
from jinja2.filters import FILTERS, pass_environment
import logging

from ubiquerg import expandpath
from ubiquerg import is_url

from .const import (
    GOOGLE_DOCS_KEY,
    TARGET_TYPE_KEY,
    GOOGLE_DOC_TARGET_TYPE,
    EXTRACT_SECTIONS_KEY,
    AUTHORMARK_KEY,
    AUTHORMARK_BASE_URL_KEY,
    AUTHORMARK_BASE_URL_ENV,
    AUTHORMARK_DEFAULT_BASE_URL,
)
from .exceptions import *
from .utilities import *
from .api_handler import APIHandler

MD_FILES_KEY = "md_files"
MD_GLOBS_KEY = "md_globs"
YAML_FILES_KEY = "yaml_files"
YAML_GLOBS_KEY = "yaml_globs"
YAML_GLOBS_UNKEYED_KEY = "yaml_globs_unkeyed"
REMOTE_NOTES_KEY = "remote_notes"
MD_CONTENT_KEY = "md_content"
YAML_CONTENT_KEY = "yaml_content"

_LOGGER = logging.getLogger(__name__)


class MarkdownResult(NamedTuple):
    """Result of parsing a markdown source."""

    key: str
    content: str
    raw: str
    metadata: Dict[str, Any]
    md_info: Dict[str, Any]


tpl_generic = """
{{ _global_frontmatter.fenced}}{{ content }}
"""


@pass_environment
def datetimeformat(
    environment: Any,
    value: Any,
    to_format: str = "%Y-%m-%d",
    from_format: str = "%Y-%m-%d",
) -> str:
    """Format a date/time value from one format to another.

    A Jinja2 filter that converts date strings between different formats.
    Handles Unix timestamps when from_format is '%s'.

    Args:
        environment: The Jinja2 environment (automatically passed).
        value: The date value to format.
        to_format: The target strftime format string.
        from_format: The source strftime format string. Use '%s' for Unix timestamps.

    Returns:
        Formatted date string, or original value if parsing fails.
    """
    if from_format == "%s":
        value = time.ctime(int(value))
        from_format = "%a %b %d %H:%M:%S %Y"
    value = str(value)
    try:
        return datetime.datetime.strptime(value, from_format).strftime(to_format)
    except ValueError as ve:
        _LOGGER.warning(ve)
        return value


@pass_environment
def extract_refs(environment: Any, value: str) -> List[str]:
    """Extract BibTeX reference keys from a string.

    A Jinja2 filter used by the nih_biosketch template to find references
    in prose blocks for adding citations to NIH "contributions" sections.
    References are denoted by [@BibTexKey] format.

    Args:
        environment: The Jinja2 environment (automatically passed).
        value: The string from which to extract references.

    Returns:
        List of extracted BibTeX reference keys without the @ prefix.

    Raises:
        Exception: If value cannot be processed (e.g., not a string type).
    """
    try:
        m = re.findall("@([a-zA-Z0-9_]+)", value)
    except TypeError as TE:
        valtype = type(value)
        msg = f"Error: Can't extract references from a '{valtype}'."
        msg += "Your template may refer to a variable incorrectly. "
        msg += f"value: '{value}'"
        raise Exception(msg)

    _LOGGER.debug(f"Extracted refs: {m}")
    return m


# Add custom date formatter filter
FILTERS["date"] = datetimeformat
# Add custom reference extraction filter
FILTERS["extract_refs"] = extract_refs

# m = extract_refs("abc; hello @test;me @second one; and finally @three")
# m


def get_frontmatter_formats(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    """Convert frontmatter dict to multiple format representations.

    Given a dictionary of content, returns three versions:
    the original dict, a YAML-dumped string, and a fenced YAML string.

    Args:
        frontmatter: A dict representing YAML frontmatter for a markdown file.

    Returns:
        Dict with keys:
            - 'raw': YAML-dumped string (empty string if frontmatter is empty)
            - 'fenced': YAML with --- fences (empty string if frontmatter is empty)
            - 'dict': Original frontmatter dictionary
    """
    if len(frontmatter) == 0:
        frontmatter_raw = ""
        frontmatter_fenced = ""
    else:
        frontmatter_raw = yaml.dump(frontmatter)
        frontmatter_fenced = f"---\n{frontmatter_raw}---\n"

    return {
        "raw": frontmatter_raw,
        "fenced": frontmatter_fenced,
        "dict": frontmatter,
    }


# Default section-extraction map: lift a body "# Abstract" heading into the
# `abstract` variable automatically, with no config. Targets can override or
# opt out via the target-level `extract_sections:` key (see
# resolve_extract_sections).
DEFAULT_EXTRACT_SECTIONS = {"abstract": ["Abstract"]}

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$", re.MULTILINE)


def extract_body_section(
    content: str, heading_names: list
) -> Tuple[Optional[str], str]:
    """Find a markdown section by heading text and split it out of the body.

    Returns (section_text, remaining_content). section_text is None if no
    matching heading is found (remaining_content is then the original).
    Matching is case-insensitive on the heading text; among matches the
    shallowest (lowest '#'-count) heading wins. The section spans from the
    matched heading to the next heading of the same-or-shallower level.
    """
    wanted = {h.strip().lower() for h in heading_names}
    headings = [
        (m.start(), m.end(), len(m.group(1)), m.group(2).strip())
        for m in _HEADING_RE.finditer(content)
    ]
    matches = [h for h in headings if h[3].lower() in wanted]
    if not matches:
        return None, content
    start_pos, head_end, level, _text = min(matches, key=lambda h: (h[2], h[0]))
    section_end = len(content)
    for h_start, _h_end, h_level, _h_text in headings:
        if h_start > start_pos and h_level <= level:
            section_end = h_start
            break
    section_text = content[head_end:section_end].strip()
    remaining = (content[:start_pos] + content[section_end:]).strip()
    return section_text, remaining


def resolve_extract_sections(target_meta: dict) -> dict:
    """Merge the built-in defaults with a target's extract_sections key.

    Resolution semantics:
      - key absent            -> DEFAULT_EXTRACT_SECTIONS (abstract on)
      - False / None / {}     -> disable all extraction ({} returned)
      - {var: None}           -> drop that section from the effective map
      - {var: [X, Y]} / "X"   -> override heading list for that section
    """
    if EXTRACT_SECTIONS_KEY not in target_meta:
        return dict(DEFAULT_EXTRACT_SECTIONS)
    user = target_meta[EXTRACT_SECTIONS_KEY]
    if not user:  # False / None / {} -> disable all
        return {}
    effective = dict(DEFAULT_EXTRACT_SECTIONS)
    for var_name, headings in user.items():
        if headings is None:  # opt out of this section
            effective.pop(var_name, None)
        else:
            effective[var_name] = headings if isinstance(headings, list) else [headings]
    return effective


def _parse_markdown_source(
    key: str,
    post: Any,
    path: Optional[str] = None,
    ext: str = "md",
    extract_sections: Optional[Dict[str, list]] = None,
) -> MarkdownResult:
    """Parse a markdown source into a structured result.

    Args:
        key: The variable name for this content.
        post: A frontmatter Post object with .content and .metadata.
        path: Optional path/identifier for the source.
        ext: File extension for metadata tracking.
        extract_sections: Optional {var_name: heading_names} map. For each entry
            not already set in the file's frontmatter, the matching body section
            is lifted into post.metadata[var_name] and stripped from the body.

    Returns:
        MarkdownResult with parsed content, raw text, and metadata.
    """
    for var_name, heading_names in (extract_sections or {}).items():
        if var_name in post.metadata:  # frontmatter precedence -- always wins
            continue
        section_text, remaining = extract_body_section(post.content, heading_names)
        if section_text is not None:
            post.metadata[var_name] = section_text
            post.content = remaining

    return MarkdownResult(
        key=key,
        content=post.content,
        raw=frontmatter.dumps(post),
        metadata=post.metadata,
        md_info={
            "content": post.content,
            "frontmatter": post.metadata,
            "path": path,
            "ext": ext,
        },
    )


def process_data(
    data_block: Dict[str, Any],
    filepath: str,
    frontmatter_base: Optional[Dict[str, Any]] = None,
    frontmatter_overrides: Optional[Dict[str, Any]] = None,
    extract_sections: Optional[Dict[str, list]] = None,
) -> Dict[str, Any]:
    """Process a data block and extract metadata from all sources.

    The data_block is the 'data:' section from a target in _markmeld.yaml.
    This function reads all specified sources and builds a flat namespace
    of variables available to the Jinja2 template.

    PRECEDENCE MODEL (lowest to highest -- later sources override earlier):

        1. frontmatter:            -- base defaults from target config
        2. md frontmatter          -- YAML frontmatter inside .md files
        3. yaml data               -- standalone .yaml files
        4. variables:              -- explicit variables from target config
        5. frontmatter_overrides:  -- overrides that always win

    Sources within the same level (e.g., multiple md_files) are processed
    in iteration order. The last one wins for any overlapping keys.

    Args:
        data_block: The data configuration block from the target.
        filepath: Path to the config file for resolving relative paths.
        frontmatter_base: Base frontmatter values (level 1).
        frontmatter_overrides: Override frontmatter values (level 5).
        extract_sections: {var_name: heading_names} map of body sections to lift
            into variables (see resolve_extract_sections). Applied per markdown
            source; frontmatter values take precedence.

    Returns:
        Dictionary containing processed data including:
        - Content keyed by variable names
        - '_raw': Raw content for each source
        - '_md': Metadata about markdown sources
        - '_yaml': Metadata about YAML sources
        - '_global_frontmatter': Merged frontmatter from all sources
        - '_local_frontmatter': Per-file frontmatter
        - '_global_vars': All template variables
    """
    _LOGGER.info(f"MM | Processing data block...")
    data = {"_raw": {}, "_md": {}, "_yaml": {}}  # Initialize return value
    frontmatter_temp = {}
    local_frontmatter_temp = {}
    vars_temp = {}

    def _apply_markdown_result(result: MarkdownResult):
        """Apply a parsed markdown result to the accumulator dicts."""
        data[result.key] = result.content
        data["_md"][result.key] = result.md_info
        data["_raw"][result.key] = result.raw
        frontmatter_temp.update(result.metadata)
        local_frontmatter_temp[result.key] = result.metadata
        if result.metadata:
            vars_temp.update(result.metadata)

    # Process frontmatter: section first (base defaults - lowest precedence)
    if frontmatter_base:
        for k, v in frontmatter_base.items():
            frontmatter_temp[k] = v
            vars_temp[k] = v
            data[k] = v

    md_files = {}
    yaml_files = {}
    unkeyed_yaml_files = []
    remote_notes = {}
    md_content = {}
    yaml_content = {}

    if MD_GLOBS_KEY in data_block and data_block[MD_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating md data globs...")
        md_files.update(globs_to_dict(data_block[MD_GLOBS_KEY], filepath))
    if YAML_GLOBS_KEY in data_block and data_block[YAML_GLOBS_KEY]:
        _LOGGER.info(f"MM | Populating yaml data globs...")
        yaml_files.update(globs_to_dict(data_block[YAML_GLOBS_KEY], filepath))
    if YAML_GLOBS_UNKEYED_KEY in data_block and data_block[YAML_GLOBS_UNKEYED_KEY]:
        _LOGGER.info(f"MM | Populating unkeyed yaml globs...")
        tmp_files = globs_to_dict(data_block[YAML_GLOBS_UNKEYED_KEY], filepath)
        yaml_files.update(tmp_files)
        unkeyed_yaml_files = tmp_files
    if MD_FILES_KEY in data_block and data_block[MD_FILES_KEY]:
        md_files.update(data_block[MD_FILES_KEY])
    if YAML_FILES_KEY in data_block and data_block[YAML_FILES_KEY]:
        yaml_files.update(data_block[YAML_FILES_KEY])
    if REMOTE_NOTES_KEY in data_block and data_block[REMOTE_NOTES_KEY]:
        remote_notes.update(data_block[REMOTE_NOTES_KEY])
        apih = APIHandler()
    if MD_CONTENT_KEY in data_block and data_block[MD_CONTENT_KEY]:
        md_content.update(data_block[MD_CONTENT_KEY])
    if YAML_CONTENT_KEY in data_block and data_block[YAML_CONTENT_KEY]:
        yaml_content.update(data_block[YAML_CONTENT_KEY])

    # Process md_files BEFORE yaml_files (see precedence model in docstring)
    for k, v in md_files.items():
        _LOGGER.info(f"MM | Processing md file {k}:{v}")
        if not v:
            data[k] = v
            continue
        if is_url(v):  # Do url stuff
            import requests

            response = requests.get(v)
            p = frontmatter.loads(response.text)
        else:
            vabs = make_abspath(v, filepath)
            if os.path.exists(vabs):
                p = frontmatter.load(vabs)
            else:
                _LOGGER.warning(f"Skipping file that does not exist: {vabs}")
                data[k] = ""  # Populate with empty values
                data["_raw"][k] = {}
                continue
        _apply_markdown_result(
            _parse_markdown_source(
                k,
                p,
                path=os.path.relpath(v, os.path.dirname(filepath)),
                ext=get_file_extension(v),
                extract_sections=extract_sections,
            )
        )

    for k, v in remote_notes.items():
        _LOGGER.info(f"MM | Processing remote note {k}:{v}")
        if not v:
            data[k] = v
            continue
        note_content = apih.fetch_note_content(v)
        p = frontmatter.loads(note_content)
        _apply_markdown_result(
            _parse_markdown_source(k, p, path=v, extract_sections=extract_sections)
        )

    for k, v in md_content.items():
        _LOGGER.info(f"MM | Processing md content {k}")
        if not v:
            data[k] = v
            continue

        if isinstance(v, str):
            p = frontmatter.loads(v)
        elif isinstance(v, dict):
            content_str = v.get("content", "")
            p = frontmatter.loads(content_str)
            if "frontmatter" in v and isinstance(v["frontmatter"], dict):
                p.metadata.update(v["frontmatter"])
        elif hasattr(v, "content") and hasattr(v, "metadata"):
            p = v
        else:
            _LOGGER.warning(f"Unsupported content type for {k}: {type(v)}")
            data[k] = ""
            data["_raw"][k] = {}
            continue

        _apply_markdown_result(
            _parse_markdown_source(k, p, extract_sections=extract_sections)
        )

    # Process yaml_files AFTER md so yaml values can override md frontmatter
    for k, v in yaml_files.items():
        _LOGGER.info(f"MM | Processing yaml file {k}: {v}")
        vabs = make_abspath(v, filepath)
        if not os.path.exists(vabs):
            _LOGGER.error(f"File not found: {vabs}")
        else:
            with open(vabs, "r") as f:
                yaml_dict = yaml.load(f, Loader=yaml.SafeLoader)
                _LOGGER.debug(yaml_dict)
                if k in unkeyed_yaml_files:
                    data.update(yaml_dict)
                    data["_yaml"].update(yaml_dict)
                    # For unkeyed yaml files, also update vars_temp and frontmatter_temp
                    vars_temp.update(yaml_dict)
                    frontmatter_temp.update(yaml_dict)
                else:
                    data[k] = yaml_dict
                    data["_yaml"][k] = {
                        "content": yaml_dict,
                        "path": os.path.relpath(v, os.path.dirname(filepath)),
                        "ext": get_file_extension(v),
                    }
                    vars_temp[k] = yaml_dict
                    # Keyed yaml files starting with "frontmatter" merge into global frontmatter
                    if k[:11] == "frontmatter":
                        frontmatter_temp.update(yaml_dict)
                data["_raw"][k] = yaml.dump(yaml_dict)

    for k, v in yaml_content.items():
        _LOGGER.info(f"MM | Processing yaml content {k}")
        if isinstance(v, dict):
            yaml_dict = v
        elif isinstance(v, str):
            yaml_dict = yaml.load(v, Loader=yaml.SafeLoader)
        else:
            _LOGGER.warning(f"Unsupported yaml content type for {k}: {type(v)}")
            continue

        data[k] = yaml_dict
        data["_yaml"][k] = {
            "content": yaml_dict,
            "path": None,
            "ext": "yaml",
        }
        vars_temp[k] = yaml_dict
        data["_raw"][k] = yaml.dump(yaml_dict)

    if "variables" in data_block and data_block["variables"]:
        data.update(data_block["variables"])
        vars_temp.update(data_block["variables"])

    # Process frontmatter_overrides: section last (highest precedence - always wins)
    if frontmatter_overrides:
        frontmatter_temp.update(frontmatter_overrides)
        vars_temp.update(frontmatter_overrides)
        data.update(frontmatter_overrides)

    # Make frontmatter variables available at top level
    # This allows templates to access variables like {{ author }} instead of {{ _global_vars.author }}
    data.update(vars_temp)

    # Global vars behaves exactly like global frontmatter, except:
    # 1. It's all variables, not just those marked with frontmatter_*.
    # It's like what's in a main data array, except it includes metadata,
    # and excludes markdown content... Is that useful?
    data["_global_vars"] = vars_temp

    # Integrated, global frontmatter from all sources in precedence order
    data["_global_frontmatter"] = get_frontmatter_formats(frontmatter_temp)

    # Local frontmatter (per markdown file)
    data["_local_frontmatter"] = {}
    for k, v in local_frontmatter_temp.items():
        data["_local_frontmatter"][k] = get_frontmatter_formats(v)

    return data


def get_file_extension(path: str) -> str:
    """Get the file extension from a file path.

    Args:
        path: The file path to extract extension from.

    Returns:
        The file extension including the dot (e.g., '.md', '.yaml').
    """
    basename = os.path.basename(path)
    splitext = os.path.splitext(basename)
    ext = splitext[1]
    return ext


def assess_variable_matches(template_source: str, provided_vars: dict) -> dict:
    """
    Compare variables referenced in a Jinja2 template against provided variables.

    Args:
        template_source: The raw Jinja2 template source string
        provided_vars: Dict of variables that will be passed to the template

    Returns:
        dict with keys:
            - 'template_vars': set of variables referenced in the template
            - 'provided_vars': set of top-level keys provided to the template
            - 'missing': set of variables in template but not provided
            - 'unused': set of variables provided but not in template
    """
    from jinja2 import Environment, meta

    env = Environment()
    try:
        parsed = env.parse(template_source)
        template_vars = meta.find_undeclared_variables(parsed)
    except Exception as e:
        _LOGGER.warning(f"Could not parse template for variable analysis: {e}")
        return {
            "template_vars": set(),
            "provided_vars": set(),
            "missing": set(),
            "unused": set(),
        }

    provided_keys = set(provided_vars.keys())

    missing = template_vars - provided_keys
    unused = provided_keys - template_vars

    # Filter out internal/special variables that start with underscore
    missing = {v for v in missing if not v.startswith("_")}
    unused = {v for v in unused if not v.startswith("_")}

    return {
        "template_vars": template_vars,
        "provided_vars": provided_keys,
        "missing": missing,
        "unused": unused,
    }


def load_template(cfg: Dict[str, Any]) -> Optional[Template]:
    """Load a Jinja2 template from a file or URL.

    Reads the jinja_template path from configuration and loads the template
    content. Supports both local files and remote URLs.

    Args:
        cfg: Configuration dictionary containing 'jinja_template' path and
            optional 'mm_templates' base directory.

    Returns:
        Jinja2 Template object with .source attribute containing raw content,
        or None if no jinja_template is configured.

    Raises:
        Exception: If template file is not found or URL returns an error.
    """

    if "jinja_template" not in cfg or not cfg["jinja_template"]:
        return None

    jinja_tpl = None
    root = cfg["mm_templates"] if "mm_templates" in cfg else None

    # Substitute variables in jinja_template path
    jinja_template_raw = cfg["jinja_template"]
    from .utilities import MyTemplate

    jinja_template_substituted = MyTemplate(jinja_template_raw).safe_substitute(**cfg)

    # If it's an absolute path after substitution, use it directly
    # Otherwise, make it absolute relative to the config file
    if os.path.isabs(jinja_template_substituted):
        jinja_tpl = jinja_template_substituted
    else:
        jinja_tpl = make_abspath(
            jinja_template_substituted, cfg["_cfg_file_path"], root
        )
    _LOGGER.info(f"MM | jinja template: {jinja_tpl}")
    # # if os.path.isfile(cfg["md_template"]):
    # #     jinja_tpl = cfg["md_template"]
    # if "mm_templates" in cfg:
    #     jinja_tpl = os.path.join(cfg["mm_templates"], cfg["md_template"])
    # else:
    #     jinja_tpl = os.path.join(, cfg["md_template"])

    try:
        if is_url(jinja_tpl):
            import requests

            response = requests.get(jinja_tpl)
            if response.status_code != 200:
                raise Exception(
                    f"Error retrieving jinja template '{jinja_tpl}': {response.status_code}"
                )
            jinja_tpl_contents = response.text

        else:
            if not os.path.isfile(jinja_tpl):
                _LOGGER.debug(cfg)
                raise Exception(f"jinja_template file not found: {jinja_tpl}")

            with open(jinja_tpl, "r") as f:
                jinja_tpl_contents = f.read()
        t = Template(jinja_tpl_contents)
        t.source = jinja_tpl_contents
    except TypeError:
        raise Exception(f"Unable to open jinja_template. Path: {jinja_tpl}")
    return t


def resolve_authormark_source(
    slug_or_url: str, cfg: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """Resolve an ``authormark:`` config value into a (base_url, slug) pair.

    The config value is either a bare capability slug
    (``bkb52l34jb523jk5bkdbj3``) or a full capability URL
    (``https://<host>/p/<slug>``). When it is a bare slug, the base URL is
    resolved from configuration in this precedence order:

        1. ``authormark_base_url`` in the config (highest)
        2. the ``MM_AUTHORMARK_BASE_URL`` environment variable
        3. a hardcoded default pointing at the deployed authormark host

    Args:
        slug_or_url: The raw ``authormark:`` config value.
        cfg: The project/root config dict (used to read ``authormark_base_url``).

    Returns:
        A tuple of ``(base_url, slug)`` where ``base_url`` has no trailing
        slash and ``slug`` is the bare capability slug.

    Raises:
        ValueError: If ``slug_or_url`` is empty/None, or a URL is given that
            does not look like a ``/p/<slug>`` capability URL.
    """
    if cfg is None:
        cfg = {}

    if not slug_or_url or not str(slug_or_url).strip():
        raise ValueError("authormark key present but empty.")

    value = str(slug_or_url).strip()

    if is_url(value):
        # Full capability URL: split into base + slug. The capability path is
        # ``/p/<slug>`` (optionally with an extension like ``.yaml``).
        from urllib.parse import urlsplit

        parts = urlsplit(value)
        path = parts.path.rstrip("/")
        marker = "/p/"
        if marker not in path:
            raise ValueError(
                f"authormark URL does not look like a capability URL "
                f"(expected '/p/<slug>'): {value}"
            )
        prefix, _, tail = path.partition(marker)
        slug = tail.split("/")[0]
        # Strip any trailing extension (.yaml/.json/.tex/...) from the slug.
        if "." in slug:
            slug = slug.split(".", 1)[0]
        if not slug:
            raise ValueError(f"Could not extract a slug from authormark URL: {value}")
        base_url = f"{parts.scheme}://{parts.netloc}{prefix}".rstrip("/")
        return base_url, slug

    # Bare slug: resolve the base URL from config/env/default.
    base_url = (
        cfg.get(AUTHORMARK_BASE_URL_KEY)
        or os.environ.get(AUTHORMARK_BASE_URL_ENV)
        or AUTHORMARK_DEFAULT_BASE_URL
    )
    return base_url.rstrip("/"), value


class Target:
    """Represents a single build target in markmeld.

    Holds configuration data, metadata, and build state for a target.
    Combines variables for template rendering with variables for command
    execution into a unified concept.

    Attributes:
        root_cfg: The root configuration dictionary from _markmeld.yaml.
        target_name: Name of this target.
        meta: Merged metadata dictionary for this target.
        messages: List of status messages from building.
        returncode: Return code from command execution (None if not run).
        stdout: Captured stdout from subprocess.
        stderr: Captured stderr from subprocess.
        melded_input: Data dictionary passed to template (set during build).
        melded_output: Rendered template output (set during build).
    """

    def __init__(
        self,
        root_cfg: Optional[Dict[str, Any]] = None,
        target_name: Optional[str] = None,
        vardata: Optional[List[str]] = None,
    ) -> None:
        """Initialize a Target object.

        Args:
            root_cfg: The root configuration dictionary from _markmeld.yaml.
            target_name: Name of the target to build.
            vardata: Optional list of "key=value" strings for CLI variables.

        Raises:
            TargetError: If targets are not specified or target_name not found.
        """
        if root_cfg is None:
            root_cfg = {}
        self.root_cfg = root_cfg
        self.target_name = target_name

        # Initialize some local variables
        self.messages = []  # A list of messages
        self.returncode = None
        self.stdout = ""  # Capture stdout from subprocess
        self.stderr = ""  # Capture stderr from subprocess

        meta = {}
        # Old way would update based on root config:
        # meta.update(self.root_cfg)
        meta["_now"] = date.today().strftime("%s")
        meta["_today"] = date.today().strftime("%Y-%m-%d")
        meta["today"] = meta["_today"]  # TODO: Remove this
        meta["now"] = meta["_now"]  # TODO: Remove this
        meta["target_name"] = target_name

        # Since a target has available to it all the variables in the _markmeld.yaml
        # config file, we start from there, then make a few changes:
        # 1. Elevate the variables in the given target up one level.
        # 2. To simplify debugging and reduce memory, remove the 'targets' key

        # _LOGGER.info(list(data["targets"].keys()))
        _LOGGER.debug(f"MM | Creating Target object for target: {target_name}")

        if target_name:
            if "targets" not in root_cfg:
                error_msg = f"No targets specified in config."
                _LOGGER.error(error_msg)
                raise TargetError(error_msg)
            if target_name not in list(root_cfg["targets"].keys()):
                error_msg = f"Target {target_name} not found"
                _LOGGER.error(error_msg)
                raise TargetError(error_msg)
            meta = deep_update(meta, self.resolve_target_inheritance(target_name))
            _LOGGER.debug(f'Config for this target: {root_cfg["targets"][target_name]}')

        # del meta["targets"]
        meta["_cfg_file_path"] = root_cfg["_cfg_file_path"]
        if "version" in meta:
            del meta["version"]

        if vardata:
            cli_vars = {y[0]: y[1] for y in [x.split("=") for x in vardata]}
            meta.update(cli_vars)
        else:
            cli_vars = {}

        # Inject embedded resource variables EARLY (before command generation)
        # This allows user variables containing resource references to be expanded
        from .resource_manager import inject_resource_variables

        meta = inject_resource_variables(meta)

        # Expand template variables in meta values (e.g., bibdb: "{mm-csl-nature}")
        # before the pandoc command is generated
        from .utilities import expand_dict_templates

        expand_dict_templates(meta)

        if "command" not in meta:
            meta["command"] = self._build_default_command(meta)

        _LOGGER.debug(f"meta: {meta}")
        self.meta = meta
        _LOGGER.debug(f"MM | Config file path: {self.meta['_cfg_file_path']}")
        if "output_file" in self.meta:
            _LOGGER.info(f"MM | Output file: {self.meta['output_file']}")

    @staticmethod
    def _build_default_command(meta: Dict[str, Any]) -> str:
        """Build a default pandoc command from target metadata."""
        from .resource_manager import get_filter_path

        options_array = []

        if "latex_template" in meta:
            options_array.append('--template "{latex_template}"')

        if "bibdb" in meta:
            options_array.append('--bibliography "{bibdb}"')

        if "csl" in meta:
            options_array.append('--csl "{csl}"')

        # Citation group targets: add the consistent-citations Lua filter
        # and skip --citeproc (the filter handles citeproc internally)
        has_citation_group = (
            "_citation_group_sources" in meta and meta["_citation_group_sources"]
        )

        if has_citation_group:
            filter_path = get_filter_path("consistent-citations")
            if filter_path:
                options_array.append(f'--lua-filter "{filter_path}"')
                # Add citation_group_sources as metadata
                for source_path in meta["_citation_group_sources"]:
                    options_array.append(
                        f"--metadata=citation_group_sources:{source_path}"
                    )
                # Add suppress-bibliography and bibliography-only metadata if set
                if meta.get("suppress-bibliography"):
                    options_array.append("--metadata=suppress-bibliography:true")
                if meta.get("bibliography-only"):
                    options_array.append("--metadata=bibliography-only:true")
        elif "citeproc" in meta and meta["citeproc"]:
            options_array.append("--citeproc")

        if "lua_filters" in meta and meta["lua_filters"]:
            filters_list = meta["lua_filters"]
            if isinstance(filters_list, str):
                filters_list = [filters_list]
            for filter_ref in filters_list:
                options_array.append(f'--lua-filter "{filter_ref}"')

        # Unconditional, and last so it also cleans up anything citeproc or an
        # earlier filter inserted. Authors paste "≤", "×" and friends into prose
        # from Word and email; pdflatex (pandoc's default engine) has no inputenc
        # mapping for the Mathematical Operators block, so one pasted character
        # kills the whole PDF. Fixing it here rather than in a LaTeX template
        # covers every template at once -- including the ones that live in a
        # Google Drive sync cache and cannot be version controlled. The filter
        # installs itself only for LaTeX output; every other writer is untouched.
        unicode_filter = get_filter_path("unicode-symbols")
        if unicode_filter:
            options_array.append(f'--lua-filter "{unicode_filter}"')

        if "output_file" in meta:
            options_array.append('-o "{output_file}"')

        if "pandoc_extra_args" in meta and meta["pandoc_extra_args"]:
            extra_args = meta["pandoc_extra_args"]
            if isinstance(extra_args, list):
                options_array.extend(extra_args)
            else:
                options_array.append(extra_args)

        options = " ".join(options_array)
        return f"pandoc {options}"

    def __repr__(self) -> str:
        """Return YAML representation of target metadata."""
        return yaml.dump(self.__dict__["meta"], default_flow_style=False)

    def add_message(self, message: str, status: str = "success") -> None:
        """Add a status message to the target's message list.

        Args:
            message: The message text to add.
            status: Message status, either 'success' or 'fail'.
        """
        if status == "fail":
            _LOGGER.warning(message)
        self.messages.append({"status": status, "message": message})

    def report(self, print_output: bool = False, dump_output: bool = False) -> None:
        """Report the results of building this target.

        Logs status messages, stdout/stderr from commands, and success/failure status.
        Moved from CLI to make it accessible for API usage.

        Args:
            print_output: Whether output was printed only (no command run).
            dump_output: Whether output was dumped for debugging.
        """
        color_red = "\x1b[31;20m"
        color_reset = "\x1b[0m"
        color_green = "\x1b[32;20m"

        # Report any messages collected during build
        for item in self.messages:
            if item["status"] == "fail":
                color_code = color_red
            else:
                color_code = color_green
            _LOGGER.info(
                f"{color_code}{item['status']}: {item['message']}{color_reset}"
            )

        # Print captured stdout/stderr from subprocess commands
        if self.stdout and self.stdout.strip():
            _LOGGER.info("Command output (stdout):")
            print(self.stdout)

        if self.stderr and self.stderr.strip():
            _LOGGER.info("Command errors (stderr):")
            print(self.stderr)

        # Report success/failure
        if self.returncode != 0:
            _LOGGER.error(
                f"{color_red}Building target '{self.target_name}' failed.{color_reset}"
            )
            return

        # Report output location
        if "output_file" in self.meta and self.meta["output_file"]:
            _LOGGER.info(
                f"Target '{self.target_name}' built successfully -> {self.meta['output_file']}"
            )
        else:
            _LOGGER.info(f"Target '{self.target_name}' built successfully")

        _LOGGER.info(f"Return code: {self.returncode}")

    def resolve_target_inheritance(self, target_name: str) -> Dict[str, Any]:
        """Resolve configuration inheritance for a target.

        Recursively resolves the 'inherit_from' chain to build the complete
        configuration for a target, merging parent configurations in order.

        Args:
            target_name: Name of the target to resolve.

        Returns:
            Merged configuration dictionary for the target.

        Raises:
            TargetError: If an inherited target is not found.
        """
        root_cfg = self.root_cfg
        if "targets" not in root_cfg:
            error_msg = f"No targets specified in config."
            _LOGGER.debug(error_msg)
            return {}
        if target_name not in list(root_cfg["targets"].keys()):
            error_msg = f"Target inherits from target '{target_name}', which was not found. Did you forget an import?"
            _LOGGER.error(error_msg)
            raise TargetError(error_msg)
            # return {}
        # _LOGGER.debug(f"Root cft targets: {root_cfg['targets']}")

        if "inherit_from" not in root_cfg["targets"][target_name]:
            ## base case
            return root_cfg["targets"][target_name]
        else:
            ## recurse
            accumulated = {}
            # root_cfg["targets"][target_name]
            inherit_from = root_cfg["targets"][target_name]["inherit_from"]
            # del accumulated["inherit_from"]
            if not isinstance(inherit_from, list):
                inherit_from = [inherit_from]
            for base_target in inherit_from:
                _LOGGER.info(f"Loading from base target: {base_target}")
                base_target_data = self.resolve_target_inheritance(base_target)
                accumulated = deep_update(accumulated, base_target_data)

            accumulated = deep_update(accumulated, root_cfg["targets"][target_name])
            return accumulated


class MarkdownMelder:
    """Main class for the markmeld package.

    Responsible for building targets specified in the markmeld config file.
    Orchestrates template rendering, data processing, and command execution.

    Attributes:
        cfg: The configuration dictionary from _markmeld.yaml.
        target_objects: Cache of built Target objects.
    """

    def __init__(self, cfg: Dict[str, Any]) -> None:
        """Initialize a MarkdownMelder instance.

        Args:
            cfg: The configuration dictionary from _markmeld.yaml.
        """
        _LOGGER.info("Initializing MarkdownMelder...")
        self.cfg = cfg
        self.target_objects = {}
        # Build citation group lookup: target_name -> group_name
        self._citation_group_map = {}
        if "citation_groups" in cfg:
            for group_name, target_list in cfg["citation_groups"].items():
                for tgt_name in target_list:
                    self._citation_group_map[tgt_name] = group_name

    def get_cache_root(self) -> str:
        """
        Get the cache root directory from configuration.

        Returns:
            Path to cache root directory (defaults to ".cache" if not configured)
        """
        cache_root = self.cfg.get("_cache_root", ".cache")
        _LOGGER.debug(
            f"get_cache_root() returning: {cache_root} (found in config: {'_cache_root' in self.cfg})"
        )
        return cache_root

    def _update_bibliography_path(
        self, content: str, cached_bib_path: Union[str, List[str]]
    ) -> str:
        """Update the bibliography path in document frontmatter to the cached file.

        Args:
            content: The markdown content with frontmatter.
            cached_bib_path: Path to the cached bibliography file(s).

        Returns:
            Updated markdown content with bibliography path pointing to cached file.
        """
        import frontmatter
        import re

        # Parse the content to extract frontmatter
        post = frontmatter.loads(content)

        # Update the bibliography field to point to the cached file
        if cached_bib_path:
            post.metadata["bibliography"] = cached_bib_path
            _LOGGER.debug(f"Updated bibliography path to: {cached_bib_path}")

        # Convert back to string with frontmatter
        return frontmatter.dumps(post)

    def open_target(self, target_name: str) -> Union[str, bool]:
        """Get the output file path for a target if it should be opened.

        Args:
            target_name: Name of the target.

        Returns:
            Output file path string if target has output and should be opened,
            False otherwise.
        """
        tgt = Target(self.cfg, target_name)

        if tgt.meta["output_file"] and "stopopen" not in tgt.meta:
            return tgt.meta["output_file"]
        else:
            return False

    def describe_target(self, target_name: str) -> bool:
        """Log description of a target's configuration.

        Args:
            target_name: Name of the target to describe.

        Returns:
            Always returns True.
        """
        tgt = Target(self.cfg, target_name)
        _LOGGER.info(f"MM | Describing target: {tgt.target_name}")
        _LOGGER.info(tgt)
        return True

    def preprocess_google_doc(self, tgt: Target) -> Optional[Target]:
        """Preprocess a Google Doc target by fetching document and figures.

        Downloads the Google Doc content and associated figures to local cache,
        then transforms the target's data configuration to use the cached content.

        Args:
            tgt: Target object with google-doc type configuration.

        Returns:
            Modified Target object with local cached content, or None on failure.
        """
        try:
            # Extract Google Doc configuration
            if "data" not in tgt.meta or GOOGLE_DOCS_KEY not in tgt.meta["data"]:
                _LOGGER.error(
                    f"Google Doc target missing 'data.{GOOGLE_DOCS_KEY}' configuration"
                )
                return None

            google_docs = tgt.meta["data"][GOOGLE_DOCS_KEY]

            # google_docs should now be a dict like:
            # { "manuscript": "doc_id_1", "data": "doc_id_2" }
            if not isinstance(google_docs, dict):
                _LOGGER.error(
                    f"Google Doc target 'data.{GOOGLE_DOCS_KEY}' must be a dictionary mapping variable names to document IDs"
                )
                return None

            if not google_docs:
                _LOGGER.error(
                    f"Google Doc target 'data.{GOOGLE_DOCS_KEY}' dictionary is empty"
                )
                return None

            force_refresh = tgt.meta.get("force_refresh", False)

            # Initialize Google Drive processor with cache root
            from .google_drive import GoogleDriveProcessor

            cache_root = self.get_cache_root()
            _LOGGER.info(f"MM | Using cache root from config: {cache_root}")
            _LOGGER.debug(
                f"MM | Initializing GoogleDriveProcessor with cache_root: {cache_root}"
            )
            gdp = GoogleDriveProcessor(cache_root=cache_root)

            md_content = {}

            # Process each Google Doc
            for var_name, doc_id in google_docs.items():
                if not doc_id:
                    _LOGGER.warning(f"Skipping empty doc_id for variable '{var_name}'")
                    md_content[var_name] = ""
                    continue

                # Ensure doc_id is a string (handle tuple/list configurations)
                if not isinstance(doc_id, str):
                    _LOGGER.error(
                        f"Document ID for '{var_name}' must be a string, got {type(doc_id)}: {doc_id}"
                    )
                    raise ValueError(
                        f"Document ID for '{var_name}' must be a string, got {type(doc_id)}: {doc_id}"
                    )

                _LOGGER.info(f"MM | Fetching Google Doc '{var_name}': {doc_id}")

                # Process document, figures, and bibliography in one pass
                _LOGGER.info(
                    f"MM | Processing document '{var_name}' and all associated figures/CSVs/bibliography..."
                )
                result = gdp.process_document_figures(
                    doc_id,
                    None,  # No folder_id needed - method will find parent folder automatically
                    skip_unchanged=(not force_refresh),
                )

                # Store content using the variable name as the key
                md_content[var_name] = result["document"]

                # Log figure processing results
                if "results" in result:
                    results = result["results"]
                    if results.get("processed"):
                        _LOGGER.info(
                            f"MM | Processed {len(results['processed'])} figures/CSVs for '{var_name}'"
                        )
                    if results.get("skipped"):
                        _LOGGER.info(
                            f"MM | Skipped {len(results['skipped'])} unchanged figures/CSVs for '{var_name}'"
                        )
                    if results.get("failed"):
                        _LOGGER.warning(
                            f"MM | Failed to process {len(results['failed'])} figures/CSVs for '{var_name}'"
                        )

                # Extract bibliography info (processed during same document download)
                bib_result = result.get("bibliography_info", {})

                if bib_result and bib_result.get("bibliography_path"):
                    # Update the frontmatter to point to the cached bibliography
                    _LOGGER.info(
                        f"MM | Updating bibliography path to cached location..."
                    )
                    md_content[var_name] = self._update_bibliography_path(
                        md_content[var_name], bib_result["bibliography_path"]
                    )

                    # Log bibliography processing results
                    if "results" in bib_result:
                        bib_results = bib_result["results"]
                        if bib_results.get("processed"):
                            _LOGGER.info(
                                f"MM | Downloaded {len(bib_results['processed'])} bibliography files for '{var_name}'"
                            )
                        if bib_results.get("skipped"):
                            _LOGGER.info(
                                f"MM | Used cached {len(bib_results['skipped'])} bibliography files for '{var_name}'"
                            )
                        if bib_results.get("failed"):
                            _LOGGER.warning(
                                f"MM | Failed to download {len(bib_results['failed'])} bibliography files for '{var_name}'"
                            )

            # Transform target data: preserve existing fields (like variables),
            # remove processed google_docs, add md_content
            existing_data = tgt.meta.get("data", {})
            _LOGGER.info(
                f"MM | Existing data keys before transform: {list(existing_data.keys())}"
            )
            if "variables" in existing_data:
                _LOGGER.info(f"MM | Preserving variables: {existing_data['variables']}")
            existing_data.pop(GOOGLE_DOCS_KEY, None)  # Remove processed google_docs
            tgt.meta["data"] = deep_update(
                existing_data, {"md_content": md_content}, warn_override=False
            )
            _LOGGER.info(
                f"MM | Final data keys after transform: {list(tgt.meta['data'].keys())}"
            )

            # Remove the type field so it processes as a normal target
            del tgt.meta[TARGET_TYPE_KEY]

            _LOGGER.info("MM | Google Doc preprocessing complete")
            return tgt

        except Exception as e:
            _LOGGER.error(f"Error preprocessing Google Doc: {e}")
            import traceback

            _LOGGER.error(f"Full traceback:\n{traceback.format_exc()}")
            return None

    def preprocess_authormark(self, tgt: Target) -> Optional[Target]:
        """Fetch a paper's author block from authormark and inject it as data.

        When a target (or the project root config) has an ``authormark:`` key,
        the author/affiliation/CRediT graph is fetched at build time from the
        authormark service and merged into the target's ``data.variables`` block
        under the same top-level names a manuscript template already uses for an
        inline author YAML block (``authors``, ``affiliations``,
        ``author_contributions``, ``byline_latex``, ``title``,
        ``affiliations_latex``, ...).

        Routing through ``variables:`` gives these keys high precedence, so when
        ``authormark:`` is set authormark is the single source of truth and any
        leftover inline author block is overridden.

        The client's ``/modified``-based cache (a :class:`DirCache` co-located
        with the rest of markmeld's cache) keeps build-to-build fetches cheap;
        ``force_refresh`` on the target meta bypasses the cache.

        Args:
            tgt: Target object whose meta (or the root config) carries an
                ``authormark`` key.

        Returns:
            Modified Target object with the author variables injected, or None
            on failure (consistent with ``preprocess_google_doc``).
        """
        # Lazy import so markmeld does not hard-require authormark-client unless
        # the authormark key is actually used (mirrors the google_drive import).
        try:
            from authormark_client import AuthormarkClient, DirCache
        except ImportError as e:
            _LOGGER.error(
                "authormark key is set but the 'authormark-client' package is "
                f"not installed: {e}. Install it with "
                "`pip install authormark-client`."
            )
            return None

        # The target value wins over the project/root value.
        slug_or_url = tgt.meta.get(AUTHORMARK_KEY, self.cfg.get(AUTHORMARK_KEY))

        try:
            base_url, slug = resolve_authormark_source(slug_or_url, self.cfg)
        except ValueError as e:
            _LOGGER.error(f"Invalid authormark configuration: {e}")
            return None

        force_refresh = tgt.meta.get("force_refresh", False)

        # Co-locate the authormark cache under the same cache root tree as the
        # google-doc caching, namespaced by 'authormark'.
        cache_root = self.get_cache_root()
        authormark_cache_dir = os.path.join(cache_root, "authormark")
        cache = DirCache(authormark_cache_dir)

        api_key = tgt.meta.get("authormark_api_key", self.cfg.get("authormark_api_key"))

        client = AuthormarkClient(base_url=base_url, api_key=api_key, cache=cache)
        try:
            try:
                # use_cache=False forces a full fetch (and refreshes the cache),
                # which is the force-refresh path. Otherwise the client probes
                # the cheap /modified endpoint and reuses the cached payload when
                # the version/etag still matches.
                author_data = client.get_markmeld_data(
                    slug, use_cache=not force_refresh
                )
            except Exception as e:
                # On a network/service error, fall back to a valid cache entry
                # if one exists (cache-as-fallback); otherwise fail clearly.
                from authormark_client import make_key

                cached = cache.get(make_key(base_url, slug))
                if cached is not None:
                    _LOGGER.warning(
                        f"authormark unreachable for slug '{slug}' at {base_url} "
                        f"({e}); falling back to cached author block."
                    )
                    author_data = cached.data
                else:
                    _LOGGER.error(
                        f"authormark unreachable for slug '{slug}' at {base_url} "
                        f"and no cache is available: {e}"
                    )
                    return None
        finally:
            client.close()

        if not isinstance(author_data, dict) or not author_data:
            _LOGGER.error(
                f"authormark returned no usable author data for slug '{slug}'."
            )
            return None

        # Inject directly into the data block's `variables:` (high precedence).
        existing_data = tgt.meta.setdefault("data", {})
        variables = existing_data.setdefault("variables", {})
        variables.update(author_data)

        # Remove the authormark keys so meld_inputs/process_data does not
        # re-encounter them (mirrors the google_docs pop).
        tgt.meta.pop(AUTHORMARK_KEY, None)
        tgt.meta.pop("authormark_api_key", None)

        _LOGGER.info(
            f"MM | Injected authormark author block for slug '{slug}' "
            f"({len(author_data)} keys) from {base_url}"
        )
        return tgt

    def _resolve_citation_group_sources(self, target_name: str) -> Optional[List[str]]:
        """Resolve absolute file paths for all markdown sources in a target's citation group.

        Args:
            target_name: Name of the target to resolve group sources for.

        Returns:
            List of absolute file paths to markdown source files for all targets
            in the citation group, in group order. Returns None if the target is
            not in a citation group.
        """
        if target_name not in self._citation_group_map:
            return None

        group_name = self._citation_group_map[target_name]
        group_targets = self.cfg["citation_groups"][group_name]
        source_paths = []

        for sibling_name in group_targets:
            if sibling_name not in self.cfg.get("targets", {}):
                _LOGGER.warning(
                    f"Citation group target '{sibling_name}' not found in config"
                )
                continue
            sibling_cfg = self.cfg["targets"][sibling_name]
            data_block = sibling_cfg.get("data", {})
            md_files = data_block.get("md_files", {})

            # Get the workpath for resolving relative paths
            workpath = sibling_cfg.get(
                "_workpath", os.path.dirname(self.cfg.get("_cfg_file_path", ""))
            )

            for key, md_path in md_files.items():
                if os.path.isabs(md_path):
                    abs_path = md_path
                else:
                    abs_path = os.path.normpath(os.path.join(workpath, md_path))
                if os.path.exists(abs_path):
                    source_paths.append(abs_path)
                else:
                    _LOGGER.warning(f"Citation group source file not found: {abs_path}")

        return source_paths if source_paths else None

    def _run_pandoc_citation_group(self, markdown_content: str, tgt: "Target") -> str:
        """Run pandoc with the consistent-citations filter for citation group processing.

        This is used when print_only=True to still process citations consistently.
        Pipes the markdown through pandoc with the Lua filter, outputting plain text.

        Args:
            markdown_content: Rendered markdown content to process.
            tgt: Target object with metadata.

        Returns:
            Pandoc-processed output as plain text.
        """
        import subprocess
        import tempfile

        from .resource_manager import get_filter_path

        filter_path = get_filter_path("consistent-citations")
        if not filter_path:
            _LOGGER.error("consistent-citations filter not found")
            return markdown_content

        citation_group_sources = tgt.meta.get("_citation_group_sources", [])
        workpath = tgt.meta.get("_workpath", ".")

        # Build pandoc command for plain text output with citation processing
        cmd_parts = ["pandoc", "--from=markdown", "--to=plain"]
        cmd_parts.append(f'--lua-filter="{filter_path}"')

        # Add bibliography if specified
        if "bibdb" in tgt.meta:
            bibdb = tgt.meta["bibdb"]
            if not os.path.isabs(bibdb):
                bibdb = os.path.normpath(os.path.join(workpath, bibdb))
            cmd_parts.append(f'--bibliography="{bibdb}"')

        # Add CSL if specified
        if "csl" in tgt.meta:
            csl = tgt.meta["csl"]
            if not os.path.isabs(csl):
                csl = os.path.normpath(os.path.join(workpath, csl))
            cmd_parts.append(f'--csl="{csl}"')

        # Add citation_group_sources as metadata
        for source_path in citation_group_sources:
            cmd_parts.append(f"--metadata=citation_group_sources:{source_path}")

        # Add suppress-bibliography and bibliography-only as metadata if set
        if tgt.meta.get("suppress-bibliography"):
            cmd_parts.append("--metadata=suppress-bibliography:true")
        if tgt.meta.get("bibliography-only"):
            cmd_parts.append("--metadata=bibliography-only:true")

        cmd = " ".join(cmd_parts)
        _LOGGER.info(f"MM | Citation group pandoc command: {cmd}")

        # Determine cwd
        if os.path.isdir(workpath):
            cwd = workpath
        else:
            cwd = os.path.dirname(workpath)

        p = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = p.communicate(input=markdown_content.encode())

        if p.returncode != 0:
            _LOGGER.error(
                f"Pandoc citation group processing failed: {stderr.decode('utf-8', errors='replace')}"
            )
            return markdown_content

        if stderr:
            _LOGGER.debug(f"Pandoc stderr: {stderr.decode('utf-8', errors='replace')}")

        return stdout.decode("utf-8", errors="replace")

    def _run_pandoc_citeproc(self, markdown_content: str, tgt: "Target") -> str:
        """Run pandoc with --citeproc for normal citation processing.

        Used in print_only mode for targets that have a bibliography but are
        not in a citation group.

        Args:
            markdown_content: Rendered markdown content to process.
            tgt: Target object with metadata.

        Returns:
            Pandoc-processed output as plain text.
        """
        import subprocess

        workpath = tgt.meta.get("_workpath", ".")

        cmd_parts = ["pandoc", "--from=markdown", "--to=plain", "--citeproc"]

        if "bibdb" in tgt.meta:
            bibdb = tgt.meta["bibdb"]
            if not os.path.isabs(bibdb):
                bibdb = os.path.normpath(os.path.join(workpath, bibdb))
            cmd_parts.append(f'--bibliography="{bibdb}"')

        if "csl" in tgt.meta:
            csl = tgt.meta["csl"]
            if not os.path.isabs(csl):
                csl = os.path.normpath(os.path.join(workpath, csl))
            cmd_parts.append(f'--csl="{csl}"')

        cmd = " ".join(cmd_parts)
        _LOGGER.info(f"MM | Citeproc pandoc command: {cmd}")

        if os.path.isdir(workpath):
            cwd = workpath
        else:
            cwd = os.path.dirname(workpath)

        p = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = p.communicate(input=markdown_content.encode())

        if p.returncode != 0:
            _LOGGER.error(
                f"Pandoc citeproc processing failed: {stderr.decode('utf-8', errors='replace')}"
            )
            return markdown_content

        return stdout.decode("utf-8", errors="replace")

    def build_target(
        self,
        target_name: str,
        print_only: bool = False,
        vardump: bool = False,
        report: bool = True,
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
        vardata: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> Union[Target, Dict[int, Target], None]:
        """Build a target by processing inputs and running the command.

        Main entry point for building targets. Handles preprocessing for
        special target types (e.g., Google Doc), runs prebuilds, melds inputs,
        renders templates, executes commands, and runs postbuilds.

        Args:
            target_name: Name of the target to build.
            print_only: If True, render template but don't run command.
            vardump: If True, dump variables instead of rendering.
            report: If True, log build results.
            input_file: Override content source with an external file path.
            output_file: Override output file path.
            vardata: Optional list of "key=value" strings for CLI variable overrides.
            force_refresh: If True, bypass remote caches (Google Doc and
                authormark) and refetch from source.

        Returns:
            Target object with build results, dict of Target objects for loop
            targets (keyed by iteration index), or None if preprocessing fails.
        """
        from pathlib import Path

        tgt = Target(self.cfg, target_name, vardata=vardata)
        _LOGGER.info(
            f"MM | Building target: {tgt.target_name} from file {tgt.meta['_cfg_file_path']}"
        )

        # Propagate the CLI/caller force-refresh flag onto the target meta so the
        # preprocessing hooks (Google Doc, authormark) can bypass their caches.
        if force_refresh:
            tgt.meta["force_refresh"] = True

        # Inject citation group sources if this target is in a citation group
        citation_group_sources = self._resolve_citation_group_sources(target_name)
        if citation_group_sources:
            tgt.meta["_citation_group_sources"] = citation_group_sources
            # Rebuild the command now that we have citation group info
            # (the original command was built in Target.__init__ before injection)
            tgt.meta["command"] = Target._build_default_command(tgt.meta)
            _LOGGER.info(
                f"MM | Citation group sources for '{target_name}': {citation_group_sources}"
            )

        # Inject ad-hoc input file into target data
        if input_file:
            input_path = str(Path(input_file).resolve())
            tgt.meta.setdefault("data", {})
            tgt.meta["data"].setdefault("md_files", {})
            tgt.meta["data"]["md_files"]["content"] = input_path

        # Override output file
        if output_file:
            tgt.meta["output_file"] = str(Path(output_file).resolve())
        elif input_file and not tgt.meta.get("output_file"):
            input_path = Path(input_file).resolve()
            tgt.meta["output_file"] = str(input_path.with_suffix(".pdf"))

        # Check for Google Doc type and preprocess if needed
        if (
            TARGET_TYPE_KEY in tgt.meta
            and tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE
        ):
            _LOGGER.info("MM | Processing Google Doc target...")
            tgt = self.preprocess_google_doc(tgt)
            if not tgt:
                _LOGGER.error("Failed to preprocess Google Doc target")
                return tgt

        # Check for an authormark author-block source (target or root config)
        # and inject the fetched author variables before melding.
        if AUTHORMARK_KEY in tgt.meta or AUTHORMARK_KEY in self.cfg:
            _LOGGER.info("MM | Processing authormark author block...")
            tgt = self.preprocess_authormark(tgt)
            if not tgt:
                _LOGGER.error("Failed to preprocess authormark author block")
                return tgt

        # First, run any pre-builds
        prebuild_results = self.build_side_targets(tgt, "prebuild")
        if not prebuild_results:
            _LOGGER.debug("Failed building prebuild side targets")
            return tgt

        # Next, meld the inputs. This can be time-consuming, it reads data to populate variables
        tgt.melded_input = self.meld_inputs(tgt)
        _LOGGER.debug(f"Melded input: {tgt.melded_input}")
        if "loop" in tgt.meta:
            result = self.build_target_in_loop(tgt, print_only, vardump, report)
            return result

        # Run command...
        result = self.run_command_for_target(tgt, print_only, vardump)

        # Run postprocess commands (shell commands in _workpath)
        if (
            "postprocess" in tgt.meta
            and tgt.meta["postprocess"]
            and result.returncode == 0
        ):
            postprocess_result = self.run_postprocess(result)
            if not postprocess_result:
                return result

        # Finally, run any postbuilds
        postbuild_results = self.build_side_targets(tgt, "postbuild")
        if not postbuild_results:
            _LOGGER.debug("Failed building postbuild side targets")
            return tgt

        # Report the result if requested
        if report:
            result.report(print_output=print_only, dump_output=vardump)

        return result

    def run_postprocess(self, tgt: Target) -> bool:
        """Run postprocess shell commands for a target.

        Postprocess commands run in _workpath (the output directory) after
        the main build completes. This allows post-processing of build outputs
        (e.g., splitting PDFs) without needing separate targets.

        Args:
            tgt: Target object with postprocess commands in meta.

        Returns:
            True if postprocess succeeded, False otherwise.
        """
        postprocess_cmd = tgt.meta["postprocess"]
        workpath = tgt.meta.get("_workpath", ".")

        _LOGGER.info(f"MM | Running postprocess for target: {tgt.target_name}")
        _LOGGER.info(f"MM | Postprocess command: {postprocess_cmd}")
        _LOGGER.info(f"MM | Postprocess working directory: {workpath}")

        # Format command with target variables (like {today}, etc.)
        from .utilities import MyTemplate

        cmd_formatted = MyTemplate(postprocess_cmd).safe_substitute(**tgt.meta)

        returncode, stdout, stderr = run_cmd(cmd_formatted, None, workpath)

        if stdout:
            tgt.stdout += f"\n[postprocess stdout]\n{stdout}"
        if stderr:
            tgt.stderr += f"\n[postprocess stderr]\n{stderr}"

        if returncode != 0:
            tgt.add_message(f"Postprocess failed with return code {returncode}", "fail")
            tgt.returncode = returncode
            return False

        tgt.add_message(f"Postprocess completed successfully", "success")
        return True

    def build_side_targets(self, tgt: Target, side_list_key: str = "prebuild") -> bool:
        """Build side targets (prebuilds or postbuilds) for a target.

        Side targets accompany a main target and are built either before
        (prebuild) or after (postbuild) the main target.

        Args:
            tgt: The main target whose side targets should be built.
            side_list_key: Key in target metadata containing list of side target
                names ('prebuild' or 'postbuild').

        Returns:
            True if all side targets built successfully, False otherwise.
        """
        if side_list_key in tgt.meta:
            _LOGGER.info(f"MM | Run {side_list_key} for target: {tgt.target_name}")
            for side_tgt in tgt.meta[side_list_key]:
                _LOGGER.info(f"MM | {side_list_key} target: {side_tgt}")
                if side_tgt in self.cfg["targets"]:
                    self.build_target(side_tgt, report=False)
                    tgt.add_message(
                        f"MM | Built {side_list_key} target '{side_tgt}' requested by target '{tgt.target_name}' from file '{tgt.meta['_cfg_file_path']}'",
                        "success",
                    )
                else:
                    tgt.add_message(
                        f"MM | No target called '{side_tgt}', requested prebuild by target '{tgt.target_name}' from file '{tgt.meta['_cfg_file_path']}'",
                        "fail",
                    )
                    return False
        return True

    def run_command_for_target(
        self, tgt: Target, print_only: bool, vardump: bool = False
    ) -> Target:
        """Execute the command for a target.

        Handles different target types (raw, meta, normal) and either renders
        the template, dumps variables, or runs the configured command.

        Args:
            tgt: Target object with melded_input already populated.
            print_only: If True, render template but don't run command.
            vardump: If True, return variables instead of rendering.

        Returns:
            Target object with melded_output and returncode set.
        """
        _LOGGER.info(f"Defined path for this target: {tgt.meta['_defpath']}")
        _LOGGER.info(f"Working path for this target: {tgt.meta['_workpath']}")

        # Create output folder if it doesn't exist (before any processing)
        if "output_file" in tgt.meta and tgt.meta["output_file"]:
            output_dir = os.path.dirname(tgt.meta["output_file"])
            if output_dir:
                # Build absolute path relative to working directory
                workpath = tgt.meta.get("_workpath", ".")
                abs_output_dir = (
                    os.path.join(workpath, output_dir)
                    if not os.path.isabs(output_dir)
                    else output_dir
                )

                if not os.path.exists(abs_output_dir):
                    _LOGGER.warning(
                        f"Missing output folder. Creating output folder: '{abs_output_dir}' for file '{tgt.meta['output_file']}'"
                    )
                    os.makedirs(abs_output_dir, exist_ok=True)

        if "type" in tgt.meta and tgt.meta["type"] == "raw":
            # Raw = No subprocess stdin printing. (so, it doesn't render anything)
            cmd_fmt = format_command(tgt)
            tgt.melded_output = None
            raw_cwd = tgt.meta.get("_defpath", tgt.meta["_workpath"])
            tgt.returncode, tgt.stdout, tgt.stderr = run_cmd(cmd_fmt, None, raw_cwd)
        elif "type" in tgt.meta and tgt.meta["type"] == "meta":
            # Meta = No command, it's a meta-target used for prebuilds or something else
            tgt.melded_output = None
            tgt.returncode = 0
        elif print_only:
            # Case 2: print_only means just render but run no command.
            tgt.melded_output = self.render_template(tgt.melded_input, tgt)
            # If this target is in a citation group, run pandoc with the
            # consistent-citations filter to produce processed output
            if tgt.meta.get("_citation_group_sources"):
                tgt.melded_output = self._run_pandoc_citation_group(
                    tgt.melded_output, tgt
                )
            elif tgt.meta.get("bibdb"):
                # For targets with bibliography, run pandoc with citeproc
                # to resolve citations even in print_only mode
                tgt.melded_output = self._run_pandoc_citeproc(tgt.melded_output, tgt)
            tgt.returncode = 0
        elif vardump:
            tgt.melded_output = tgt.melded_input
            tgt.returncode = 0
        elif tgt.meta["command"]:
            cmd_fmt = format_command(tgt)
            _LOGGER.debug(f"Running regular command: '{cmd_fmt}'")
            tgt.melded_output = self.render_template(tgt.melded_input, tgt)
            _LOGGER.debug(
                f"melded_output length: {len(tgt.melded_output) if tgt.melded_output else 0} characters"
            )
            if tgt.melded_output == "" or tgt.melded_output is None:
                _LOGGER.error("No input detected. Check variable names")
                tgt.returncode = 2
            else:
                # Run figure reference analysis if we have markdown content
                if tgt.melded_output and isinstance(tgt.melded_output, str):
                    try:
                        from .document_checker import DocumentChecker

                        dc = DocumentChecker()
                        analysis_report = dc.generate_figure_analysis_report(
                            tgt.melded_output
                        )
                        if analysis_report:
                            # Log the analysis report as warnings
                            for line in analysis_report.split("\n"):
                                if line.strip():
                                    _LOGGER.warning(line)
                    except Exception as e:
                        _LOGGER.debug(f"Could not analyze figure references: {e}")

                # Convert local SVG figures to PDF before passing to pandoc
                if tgt.melded_output and isinstance(tgt.melded_output, str):
                    try:
                        from .figure_conversion import process_local_figures

                        tgt.melded_output = process_local_figures(
                            tgt.melded_output,
                            defpath=tgt.meta["_defpath"],
                            cache_dir=(
                                Path(tgt.meta["_cache_root"]).parent
                                if "_cache_root" in tgt.meta
                                else Path(tgt.meta.get("_workpath", "."))
                            ),
                        )
                    except Exception as e:
                        _LOGGER.warning(f"Could not process local figures: {e}")
                        import traceback

                        _LOGGER.warning(traceback.format_exc())

                tgt.returncode, tgt.stdout, tgt.stderr = run_cmd(
                    cmd_fmt, tgt.melded_output.encode(), tgt.meta["_workpath"]
                )
        return tgt

    def build_target_in_loop(
        self,
        tgt: Target,
        print_only: bool = False,
        vardump: bool = False,
        report: bool = True,
    ) -> Dict[int, Target]:
        """Build a target multiple times using loop configuration.

        Implements mail-merge functionality by iterating over a data collection
        and building the target once for each item.

        Args:
            tgt: Target object with loop configuration in meta.
            print_only: If True, render template but don't run command.
            vardump: If True, dump variables instead of rendering.
            report: If True, log build results for each iteration.

        Returns:
            Dictionary mapping iteration index to Target objects.

        Raises:
            Exception: If loop_data variable is not found.
        """
        # Process each iteration of the loop
        melded_input = tgt.melded_input
        loop_data_var = tgt.meta["loop"]["loop_data"].split(".")
        _LOGGER.debug(f"Retrieve loop data variable named {loop_data_var}")
        loop_dat = recursive_get(melded_input, loop_data_var)
        _LOGGER.debug(f"Loop dat: {loop_dat}")
        _LOGGER.debug(f"Target melded_input: {tgt.melded_input}")
        if not loop_dat:
            _LOGGER.error(f"Loop data not found: {loop_data_var}")
            raise Exception(f"Loop data not found: {loop_data_var}")
        n = len(loop_dat)
        _LOGGER.info(f"Loop found: {n} elements.")
        _LOGGER.debug(loop_dat)

        return_target_objects = {}
        for i in range(len(loop_dat)):
            loop_var_value = loop_dat[i]
            tgt_copy = deepcopy(tgt)
            var = tgt_copy.meta["loop"]["assign_to"]
            _LOGGER.info(f"{var}: {loop_var_value}")
            tgt_copy.melded_input.update({var: loop_var_value})
            tgt_copy.meta.update({var: loop_var_value})
            _LOGGER.debug(tgt_copy.meta)
            # _LOGGER.debug(cmd_data)
            self.render_template(tgt_copy.melded_input, tgt_copy, double=False)
            return_target_objects[i] = self.run_command_for_target(
                tgt_copy, print_only, vardump
            )

        # Report loop results if requested
        if report:
            successful_builds = sum(
                1 for t in return_target_objects.values() if t.returncode == 0
            )
            _LOGGER.info(
                f"Built loop target '{tgt.target_name}': {successful_builds}/{len(return_target_objects)} successful"
            )
            for i, loop_tgt in return_target_objects.items():
                _LOGGER.info(
                    f"  Loop iteration {i}: Return code: {loop_tgt.returncode}. Output: {loop_tgt.meta.get('output_file', 'N/A')}"
                )

        return return_target_objects

    def meld_inputs(self, tgt: Target) -> Dict[str, Any]:
        """Process and merge all inputs for a target.

        Reads data sources specified in the target configuration, processes
        frontmatter, and merges everything into a single data dictionary
        for template rendering.

        Args:
            tgt: Target object to process inputs for.

        Returns:
            Merged data dictionary ready for template rendering.
        """
        data_copy = deepcopy(tgt.meta)

        if "version" in tgt.root_cfg and not tgt.root_cfg["version"] >= 1:
            _LOGGER.error("Can't process this config version.")

        _LOGGER.info("MM | Processing config version 1...")
        # Extract frontmatter sections from target meta (not from data block)
        frontmatter_base = tgt.meta.get("frontmatter", None)
        frontmatter_overrides = tgt.meta.get("frontmatter_overrides", None)
        extract_sections = resolve_extract_sections(tgt.meta)

        if "data" in tgt.meta:
            processed_data_block = process_data(
                tgt.meta["data"],
                tgt.meta["_workpath"],
                frontmatter_base=frontmatter_base,
                frontmatter_overrides=frontmatter_overrides,
                extract_sections=extract_sections,
            )
        else:
            processed_data_block = process_data(
                {},
                tgt.meta["_workpath"],
                frontmatter_base=frontmatter_base,
                frontmatter_overrides=frontmatter_overrides,
                extract_sections=extract_sections,
            )
        _LOGGER.debug("processed_data_block: %s", processed_data_block)
        data_copy.update(processed_data_block)

        # Expand template variables in data_copy values (e.g., bibdb: "{mm-csl-nature}")
        from .utilities import expand_dict_templates

        expand_dict_templates(data_copy)

        k = list(data_copy.keys())
        _LOGGER.debug(f"MM | Available keys: {k}")
        if MD_FILES_KEY in data_copy:
            _LOGGER.debug(
                f"MM | Available keys [{MD_FILES_KEY}]: {list(data_copy[MD_FILES_KEY].keys())}"
            )
        if YAML_FILES_KEY in data_copy:
            _LOGGER.debug(
                f"MM | Available keys [{YAML_FILES_KEY}]: {list(data_copy[YAML_FILES_KEY].keys())}"
            )
        return data_copy

    def render_template(
        self,
        melded_input: Dict[str, Any],
        target: Target,
        double: Optional[bool] = None,
    ) -> str:
        """Render the Jinja2 template with the melded input data.

        Args:
            melded_input: Data dictionary to pass to the template.
            target: Target object containing template configuration.
            double: Whether to render twice (recursive rendering). If None,
                uses target's recursive_render setting (defaults to True).

        Returns:
            Rendered template string.

        Raises:
            Exception: If using deprecated 'md_template' instead of 'jinja_template'.
        """
        if "data" not in melded_input:
            melded_input["data"] = {}
        if "md_template" in target.meta:
            raise Exception(
                "Please update your config! 'md_template' was renamed to 'jinja_template'."
            )

        if "jinja_template" in target.meta and target.meta["jinja_template"]:
            tpl = load_template(target.meta)
        else:
            # cmd_data["jinja_template"] = None
            tpl = Template(tpl_generic)
            tpl.source = tpl_generic
            _LOGGER.error(
                "No jinja_template provided. Using generic markmeld jinja_template."
            )

        # Check for variable mismatches before rendering
        if hasattr(tpl, "source") and tpl.source:
            mismatch_report = assess_variable_matches(tpl.source, melded_input)
            if mismatch_report["missing"]:
                _LOGGER.warning(
                    f"Template references variables not provided: {mismatch_report['missing']}"
                )
            # Log unused vars at debug level (less critical)
            if mismatch_report["unused"]:
                _LOGGER.debug(
                    f"Provided variables not used in template: {mismatch_report['unused']}"
                )

        if double is None:
            if (
                "recursive_render" in target.meta
                and not target.meta["recursive_render"]
            ):
                double = False
            else:
                # Recursive rendering allows your template to include variables
                double = True

        if double:
            return Template(tpl.render(melded_input)).render(melded_input)  # two times
        else:
            return tpl.render(melded_input)
