"""Tests for ad-hoc input file support (--input and -o flags)"""

import os
import tempfile
import yaml
import pytest
from markmeld import MarkdownMelder


def create_test_config(target_name, target_data):
    """Helper to create a test config with proper paths"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config = {"targets": {target_name: target_data}}
        yaml.dump(config, f)
        config_file = f.name

    with open(config_file, 'r') as f:
        cfg = yaml.load(f, Loader=yaml.SafeLoader)
    cfg['_cfg_file_path'] = config_file
    cfg['targets'][target_name]['_workpath'] = os.path.dirname(config_file)
    cfg['targets'][target_name]['_defpath'] = os.path.dirname(config_file)
    return cfg, config_file


def test_input_file_injects_content():
    """--input should inject an external file as md_files.content"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("---\ntitle: External Letter\n---\nDear Sir,\n\nPlease accept this.")
        input_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("{{ content }}")
        template_file = f.name

    target_data = {
        "jinja_template": template_file,
        "command": None,
    }
    cfg, config_file = create_test_config("signature", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("signature", print_only=True, input_file=input_file)
        assert result.melded_output
        assert "Dear Sir," in result.melded_output
        assert "Please accept this." in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(input_file)


def test_input_file_frontmatter_available():
    """--input file's frontmatter should be available to the template"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("---\ntitle: My Letter\nrecipient: Dr. Smith\n---\nBody text here.")
        input_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("To: {{ recipient }}\n{{ content }}")
        template_file = f.name

    target_data = {
        "jinja_template": template_file,
        "command": None,
    }
    cfg, config_file = create_test_config("signature", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("signature", print_only=True, input_file=input_file)
        assert result.melded_output
        assert "To: Dr. Smith" in result.melded_output
        assert "Body text here." in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(input_file)


def test_output_file_override():
    """--output should override the target's output_file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("Content")
        input_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("{{ content }}")
        template_file = f.name

    target_data = {
        "jinja_template": template_file,
        "output_file": "original.pdf",
        "command": None,
    }
    cfg, config_file = create_test_config("signature", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target(
            "signature", print_only=True,
            input_file=input_file, output_file="/tmp/custom_output.pdf",
        )
        assert result.meta["output_file"] == "/tmp/custom_output.pdf"
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(input_file)


def test_output_file_defaults_from_input():
    """When --input is given without -o and target has no output_file, default to {input_stem}.pdf"""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', delete=False, prefix='letter_'
    ) as f:
        f.write("Content")
        input_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("{{ content }}")
        template_file = f.name

    target_data = {
        "jinja_template": template_file,
        "command": None,
    }
    cfg, config_file = create_test_config("signature", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("signature", print_only=True, input_file=input_file)
        expected = input_file.replace(".md", ".pdf")
        assert result.meta["output_file"] == expected
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(input_file)


def test_input_merges_with_existing_data():
    """--input should merge with existing target data, not replace it"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("Letter body")
        input_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("Org: {{ org }}\n{{ content }}")
        template_file = f.name

    target_data = {
        "jinja_template": template_file,
        "command": None,
        "data": {
            "variables": {"org": "ACME Corp"},
        },
    }
    cfg, config_file = create_test_config("signature", target_data)

    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("signature", print_only=True, input_file=input_file)
        assert result.melded_output
        assert "Org: ACME Corp" in result.melded_output
        assert "Letter body" in result.melded_output
    finally:
        os.unlink(config_file)
        os.unlink(template_file)
        os.unlink(input_file)
