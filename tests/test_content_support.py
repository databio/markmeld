"""
Tests for direct content support (md_content and yaml_content)
"""

import pytest
import tempfile
import os
import yaml
import frontmatter
from markmeld import MarkdownMelder, load_config_file


def create_test_config(target_name, target_data):
    """Helper to create a test config with proper paths"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config = {"targets": {target_name: target_data}}
        yaml.dump(config, f)
        config_file = f.name

    # Load and set paths
    with open(config_file, "r") as f:
        cfg = yaml.load(f, Loader=yaml.SafeLoader)
    cfg["_cfg_file_path"] = config_file
    cfg["targets"][target_name]["_workpath"] = os.path.dirname(config_file)
    cfg["targets"][target_name]["_defpath"] = os.path.dirname(config_file)

    return cfg, config_file


def test_md_content_raw_string():
    """Test that raw markdown strings can be provided via md_content"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("{{ doc1 }}")
        template_file = f.name

    target_data = {
        "data": {"md_content": {"doc1": "# Hello World\n\nThis is a test."}},
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "# Hello World" in result.melded_output
        assert "This is a test." in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_md_content_with_frontmatter():
    """Test that markdown content with frontmatter can be provided via md_content"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("Title: {{ _global_frontmatter.dict.title }}\n{{ doc2 }}")
        template_file = f.name

    target_data = {
        "data": {
            "md_content": {
                "doc2": {
                    "content": "# Document\n\nContent here.",
                    "frontmatter": {"title": "Test Doc", "author": "Test Author"},
                }
            }
        },
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Title: Test Doc" in result.melded_output
        assert "# Document" in result.melded_output
        # Check that frontmatter is available in _global_frontmatter
        assert result.melded_input["_global_frontmatter"]["dict"]["title"] == "Test Doc"
        assert (
            result.melded_input["_global_frontmatter"]["dict"]["author"]
            == "Test Author"
        )
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_md_content_frontmatter_post_object():
    """Test that python-frontmatter Post objects can be provided via md_content"""
    post = frontmatter.Post("# Post Content\n\nThis is a post.")
    post.metadata = {"date": "2024-01-01", "category": "test"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("Category: {{ _global_frontmatter.dict.category }}\n{{ doc3 }}")
        template_file = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config = {
            "targets": {
                "test_target": {
                    "data": {"md_content": {}},
                    "jinja_template": template_file,
                    "command": None,
                }
            }
        }
        yaml.dump(config, f)
        config_file = f.name

    # Load config and add Post object programmatically
    with open(config_file, "r") as f:
        cfg = yaml.load(f, Loader=yaml.SafeLoader)
    cfg["_cfg_file_path"] = config_file
    cfg["targets"]["test_target"]["_workpath"] = os.path.dirname(config_file)
    cfg["targets"]["test_target"]["_defpath"] = os.path.dirname(config_file)
    cfg["targets"]["test_target"]["data"]["md_content"]["doc3"] = post

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Category: test" in result.melded_output
        assert "# Post Content" in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_yaml_content_dict():
    """Test that YAML dicts can be provided via yaml_content"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("Theme: {{ settings.theme }}, Lang: {{ settings.lang }}")
        template_file = f.name

    target_data = {
        "data": {"yaml_content": {"settings": {"theme": "dark", "lang": "en"}}},
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Theme: dark" in result.melded_output
        assert "Lang: en" in result.melded_output
        # Check that the data is available as expected
        assert result.melded_input["settings"]["theme"] == "dark"
        assert result.melded_input["settings"]["lang"] == "en"
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_yaml_content_string():
    """Test that YAML strings can be provided via yaml_content"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("DB: {{ config.database.host }}:{{ config.database.port }}")
        template_file = f.name

    target_data = {
        "data": {
            "yaml_content": {"config": "database:\n  host: localhost\n  port: 5432"}
        },
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "DB: localhost:5432" in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_combined_file_and_content():
    """Test that file-based and content-based sources can be combined"""
    # Create a test markdown file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("---\ntitle: From File\n---\n# File Content\n\nFrom file.")
        md_file = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("{{ file_doc }}\n---\n{{ memory_doc }}")
        template_file = f.name

    target_data = {
        "data": {
            "md_files": {"file_doc": md_file},
            "md_content": {"memory_doc": "# Memory Content\n\nFrom memory."},
        },
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "# File Content" in result.melded_output
        assert "From file." in result.melded_output
        assert "# Memory Content" in result.melded_output
        assert "From memory." in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(md_file)


def test_frontmatter_section():
    """Test that frontmatter: section updates global frontmatter (replaces legacy frontmatter_* prefix)"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write("Author: {{ _global_frontmatter.dict.author }}")
        template_file = f.name

    target_data = {
        "frontmatter": {"author": "YAML Author"},
        "jinja_template": template_file,
        "command": None,
    }

    cfg, config_file = create_test_config("test_target", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Author: YAML Author" in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


# ---------------------------------------------------------------------------
# Section extraction (extract_sections): lift a body "# Abstract" heading into
# the `abstract` variable automatically.
# ---------------------------------------------------------------------------

# Template that surfaces both the extracted abstract and the (stripped) body so
# tests can assert on each separately.
_EXTRACT_TEMPLATE = "ABSTRACT:{{ abstract }}|BODY:{{ body }}"


def _write_template(text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jinja", delete=False) as f:
        f.write(text)
    return f.name


def _run_extract_target(target_data):
    template_file = _write_template(_EXTRACT_TEMPLATE)
    target_data.setdefault("jinja_template", template_file)
    target_data.setdefault("command", None)
    cfg, config_file = create_test_config("test_target", target_data)
    try:
        mm = MarkdownMelder(cfg)
        return mm.build_target("test_target", print_only=True)
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_extract_abstract_default_on():
    """Default-on: an H1 '# Abstract' body section is lifted into `abstract`."""
    body = "# Abstract\n\nThis is the abstract.\n\n# Introduction\n\nIntro body."
    result = _run_extract_target({"data": {"md_content": {"body": body}}})
    assert "ABSTRACT:This is the abstract." in result.melded_output
    # Abstract heading + text stripped from body; other sections remain.
    assert "# Abstract" not in result.melded_output
    assert "This is the abstract." not in result.melded_output.split("BODY:")[1]
    assert "# Introduction" in result.melded_output
    assert "Intro body." in result.melded_output


def test_extract_abstract_h2_section_span():
    """An H2 '## Abstract' section ends at the next H2; later sections stay."""
    body = "## Abstract\n\nAbstract prose here.\n\n" "## Methods\n\nMethods prose here."
    result = _run_extract_target({"data": {"md_content": {"body": body}}})
    assert "ABSTRACT:Abstract prose here." in result.melded_output
    body_out = result.melded_output.split("BODY:")[1]
    assert "Abstract prose here." not in body_out
    assert "## Methods" in body_out
    assert "Methods prose here." in body_out


def test_extract_abstract_frontmatter_wins():
    """Frontmatter abstract wins; the body '# Abstract' is left untouched."""
    body = "# Abstract\n\nBody abstract text.\n\n# Intro\n\nIntro."
    md_content = {"body": {"content": body, "frontmatter": {"abstract": "FM abstract"}}}
    result = _run_extract_target({"data": {"md_content": md_content}})
    assert "ABSTRACT:FM abstract" in result.melded_output
    # Body untouched: still contains the heading and its prose.
    assert "# Abstract" in result.melded_output
    assert "Body abstract text." in result.melded_output


def test_extract_abstract_opt_out():
    """extract_sections {abstract: null} leaves the body heading in place."""
    body = "# Abstract\n\nBody abstract text."
    result = _run_extract_target(
        {
            "extract_sections": {"abstract": None},
            "data": {"md_content": {"body": body}},
        }
    )
    # No abstract var injected; body untouched.
    assert "ABSTRACT:|BODY:" in result.melded_output
    assert "# Abstract" in result.melded_output
    assert "Body abstract text." in result.melded_output


def test_extract_abstract_disable_all():
    """extract_sections: false disables extraction entirely."""
    body = "# Abstract\n\nBody abstract text."
    result = _run_extract_target(
        {
            "extract_sections": False,
            "data": {"md_content": {"body": body}},
        }
    )
    assert "ABSTRACT:|BODY:" in result.melded_output
    assert "# Abstract" in result.melded_output
    assert "Body abstract text." in result.melded_output


def test_extract_abstract_shallowest_wins():
    """With Abstract at both H1 and H2, the H1 section is captured."""
    body = (
        "# Abstract\n\nTop-level abstract.\n\n"
        "## Details\n\n### Abstract\n\nNested abstract.\n"
    )
    result = _run_extract_target({"data": {"md_content": {"body": body}}})
    assert "ABSTRACT:Top-level abstract." in result.melded_output
    # H1 abstract spans to end of doc (no same-or-shallower heading follows),
    # so the whole thing is lifted out.
    body_out = result.melded_output.split("BODY:")[1]
    assert "Top-level abstract." not in body_out


def test_extract_abstract_override_heading_names():
    """extract_sections {abstract: [Summary]} picks up '# Summary', ignores '# Abstract'."""
    body = "# Summary\n\nSummary prose.\n\n# Abstract\n\nAbstract prose."
    result = _run_extract_target(
        {
            "extract_sections": {"abstract": ["Summary"]},
            "data": {"md_content": {"body": body}},
        }
    )
    assert "ABSTRACT:Summary prose." in result.melded_output
    body_out = result.melded_output.split("BODY:")[1]
    assert "Summary prose." not in body_out
    # The '# Abstract' heading is not in the override list, so it stays.
    assert "# Abstract" in body_out
    assert "Abstract prose." in body_out


def test_extract_abstract_via_md_files():
    """Extraction also applies to md_files sources (same code path)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Abstract\n\nFile abstract text.\n\n# Body\n\nBody text.")
        md_file = f.name
    try:
        result = _run_extract_target({"data": {"md_files": {"body": md_file}}})
        assert "ABSTRACT:File abstract text." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "File abstract text." not in body_out
        assert "# Body" in body_out
    finally:
        os.unlink(md_file)
