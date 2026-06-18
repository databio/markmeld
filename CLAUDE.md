# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Markmeld is a markdown melder that merges YAML and markdown content using Jinja2 templates to produce polished documents like resumes, proposals, manuscripts, and more. It's particularly powerful when combined with pandoc for various output formats (HTML, PDF via LaTeX).

Markmeld provides the core functionality around building PDF and other outputs from input markdown files.

## Key Commands

### Development
```bash
# Run tests
pytest

# Run specific test
pytest tests/test_markmeld.py::test_name

# Format code with black (used in CI)
black .

# Build demo documents
cd demo
mm default
```

## Architecture

### Core Components

**MarkdownMelder** (`markmeld/melder.py`): Main class that orchestrates the melding process
- `build_target()`: Builds a single target with optional loops and side targets
- `process_data()`: Extracts and processes data from YAML/markdown sources
- Handles template rendering, variable substitution, and output generation

**CLI** (`markmeld/cli.py`): Command-line interface using argparse
- Entry point: `mm` command
- Handles config loading, target selection, and various output modes

**Data Processing Flow**:
1. Load configuration from `_markmeld.yaml`
2. Process data sources (YAML files, markdown files, globs)
3. Extract frontmatter and merge content
4. Apply Jinja2 template with custom filters
5. Output to file or pipe to pandoc

### Configuration Structure

Markmeld uses `_markmeld.yaml` files with this structure:
- `imports`: Import other config files
- `targets`: Define output targets with:
  - `jinja_template`: Template file path
  - `output_file`: Output path (supports variables like `{today}`)
  - `data`: Sources specification
    - `md_files`, `md_globs`: Markdown sources
    - `yaml_files`, `yaml_globs`: YAML sources
    - `variables`: Direct variable definitions
  - `loop`: For mail-merge functionality
  - `prebuild`/`postbuild`: Side targets

### Key Features

**Template System**: Uses Jinja2 with custom filters:
- `date`: Format dates between different formats
- `extract_refs`: Extract bibliography references from text

**Data Sources**: Supports multiple input types:
- Markdown files with optional YAML frontmatter
- YAML files (keyed and unkeyed)
- Direct content strings (`md_content`, `yaml_content`)
- Remote templates via URLs
- Glob patterns for batch processing

**Advanced Features**:
- **Loop targets**: Mail merge functionality for generating multiple documents
- **Target factories**: Auto-generate targets using Python plugins
- **Side targets**: Pre/post-build hooks for tasks like updating bibliographies
- **Inheritance**: Targets can inherit configuration from others
- **Variable variables**: Dynamic variable resolution in templates

### Special Variables

Markmeld provides several special variables that are automatically available in command templates and output file paths:

**Always available**:
- `{today}`: Current date in YYYY-MM-DD format (e.g., "2025-10-31")
- `{now}`: Current timestamp in Unix epoch format
- `{target_name}`: Name of the current target being built

**Cloud/backend only** (when building via Sciquill web application):
- `{project_slug}`: URL-friendly slug of the project
- `{project_name}`: Human-readable name of the project

**Usage examples**:
```yaml
targets:
  my-target:
    output_file: "out/{target_name}-{today}.pdf"
    command: |
      pandoc input.md -o out/{target_name}.pdf
      echo "Built {target_name} on {today}"
```

Variables use Python's `string.Template.safe_substitute()`, which means:
- Undefined variables are left as-is (no errors)
- Variables can contain other variables (recursive expansion up to 5 levels)
- Both `{variable}` syntax is supported

## Authormark author source

A target (or the project root config) can pull its author/affiliation/CRediT
block from the [authormark](https://authormark.databio.org) service instead of
maintaining an inline author YAML block. Add a single key:

```yaml
# at the target level (or top level of _markmeld.yaml)
authormark: bkb52l34jb523jk5bkdbj3        # a capability slug
# or a full capability URL:
# authormark: https://authormark.databio.org/p/bkb52l34jb523jk5bkdbj3
```

At build time, `MarkdownMelder.preprocess_authormark` fetches the server-rendered
markmeld block and injects its top-level keys (`authors`, `affiliations`,
`author_contributions`, `byline_latex`, `title`, `affiliations_latex`, ...) into
the target's `data.variables`. Because `variables:` has high precedence, these
values override any leftover inline author block — authormark is the single
source of truth when the key is set.

**Base URL resolution** (highest first): `authormark_base_url` in config →
`MM_AUTHORMARK_BASE_URL` env var → the deployed default. A bare slug is joined
with the resolved base URL; a full URL is used directly.

**Caching:** the [`authormark-client`](https://pypi) `DirCache` lives under
`<cache_root>/authormark/` and is validated against the cheap `/p/<slug>/modified`
endpoint, so unchanged papers are not re-downloaded. Pass `--force-refresh` (or
`force_refresh=True` to `build_target`) to bypass the cache.

**Failure handling:** an empty key, a 404, or an unreachable service with no
cache cause `build_target` to return `None` (same as a failed google-doc
preprocess). If the service is unreachable but a cached block exists, the cached
block is used with a warning.

**Migration:** delete the inline author YAML block from the source document and
add the one `authormark:` key. No dual-path reconciliation is kept.

**Dependency:** the `authormark-client` package is an optional extra
(`pip install markmeld[authormark]` or `pip install authormark-client`). It is
imported lazily, only when the `authormark:` key is present.

## Testing

Tests are in `tests/` and use pytest. Key test files:
- `test_markmeld.py`: Core functionality tests
- `test_content_support.py`: Tests for different content input methods

Test data is in `tests/test_data/` with various configuration examples.
Add any new tests into `tests/test_*.py` and use pytest to ruth them.


## Using Markmeld 

### CLI Usage
```bash
# Initialize a config file
mm --init

# Build a target
mm <target_name>

# List available targets
mm -l

# Print output instead of running pandoc
mm <target_name> -p

# Dump content object for debugging
mm <target_name> -d
```



### Basic Usage as a Python Library
```python
from markmeld import MarkdownMelder, load_config_file

# Load configuration from file
cfg = load_config_file("_markmeld.yaml")

# Create MarkdownMelder instance
mm = MarkdownMelder(cfg)

# Build target (print_only=True renders without running command)
result = mm.build_target("my_target", print_only=True)

# Access rendered output
print(result.melded_output)
```

### Programmatic Configuration (No Files Needed) as a Python Library
```python
from markmeld import MarkdownMelder

config = {
    "_cfg_file_path": "/tmp/temp.yaml",  # Required for path resolution
    "targets": {
        "document": {
            "_workpath": "/tmp",  # Required working directory
            "_defpath": "/tmp",   # Required definition path
            "data": {
                "md_content": {
                    "body": "# Title\n\nContent here"
                },
                "yaml_content": {
                    "metadata": {"author": "John Doe", "date": "2024-01-01"}
                }
            },
            "jinja_template": "template.jinja",
            "command": None  # Just render, don't execute
        }
    }
}

mm = MarkdownMelder(config)
result = mm.build_target("document", print_only=True)
```

### Working with Build Results
```python
result = mm.build_target("target_name", print_only=True)

# Access rendered output
result.melded_output  # String of rendered content

# Access input data passed to template
result.melded_input   # Dict with all template variables

# Check return code (0 = success)
result.returncode     # Integer return code

# Access target metadata
result.meta          # Dict of target configuration
```

### Building with Subprocess Execution
```python
# To actually run commands (e.g., pandoc), omit print_only
result = mm.build_target("target_name")  # Runs command defined in config

# Or explicitly set print_only=False
result = mm.build_target("target_name", print_only=False)
```

### Loop Targets (Mail Merge)
```python
# When target has loop configuration, returns dict of results
results = mm.build_target("loop_target", print_only=True)

# Iterate through results
for idx, result in results.items():
    print(f"Iteration {idx}: {result.melded_output}")
```

## Common Workflows

### Adding a New Feature
1. Implement in appropriate module (`melder.py` for core logic, `cli.py` for CLI)
2. Add tests in `tests/`
3. Format code with `black`
4. Run full test suite with `pytest`

### Debugging Template Issues
1. Use `mm <target> -d` to dump the content object
2. Use `mm <target> -p` to print output without running pandoc
3. Check template syntax and variable names in Jinja2 template

### Working with Complex Documents
1. Structure content in YAML for lists/structured data
2. Use markdown for prose sections
3. Design Jinja2 template to combine and arrange content
4. Configure output pipeline (usually to pandoc)