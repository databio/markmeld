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
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config = {"targets": {target_name: target_data}}
        yaml.dump(config, f)
        config_file = f.name
    
    # Load and set paths
    with open(config_file, 'r') as f:
        cfg = yaml.load(f, Loader=yaml.SafeLoader)
    cfg['_cfg_file_path'] = config_file
    cfg['targets'][target_name]['_workpath'] = os.path.dirname(config_file)
    cfg['targets'][target_name]['_defpath'] = os.path.dirname(config_file)
    
    return cfg, config_file


def test_md_content_raw_string():
    """Test that raw markdown strings can be provided via md_content"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("{{ doc1 }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "md_content": {
                "doc1": "# Hello World\n\nThis is a test."
            }
        },
        "jinja_template": template_file,
        "command": None
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
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("Title: {{ _global_frontmatter.dict.title }}\n{{ doc2 }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "md_content": {
                "doc2": {
                    "content": "# Document\n\nContent here.",
                    "frontmatter": {"title": "Test Doc", "author": "Test Author"}
                }
            }
        },
        "jinja_template": template_file,
        "command": None
    }
    
    cfg, config_file = create_test_config("test_target", target_data)
    
    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Title: Test Doc" in result.melded_output
        assert "# Document" in result.melded_output
        # Check that frontmatter is available in _global_frontmatter
        assert result.melded_input['_global_frontmatter']['dict']['title'] == "Test Doc"
        assert result.melded_input['_global_frontmatter']['dict']['author'] == "Test Author"
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_md_content_frontmatter_post_object():
    """Test that python-frontmatter Post objects can be provided via md_content"""
    post = frontmatter.Post("# Post Content\n\nThis is a post.")
    post.metadata = {"date": "2024-01-01", "category": "test"}
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("Category: {{ _global_frontmatter.dict.category }}\n{{ doc3 }}")
        template_file = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config = {"targets": {"test_target": {
            "data": {"md_content": {}},
            "jinja_template": template_file,
            "command": None
        }}}
        yaml.dump(config, f)
        config_file = f.name
    
    # Load config and add Post object programmatically
    with open(config_file, 'r') as f:
        cfg = yaml.load(f, Loader=yaml.SafeLoader)
    cfg['_cfg_file_path'] = config_file
    cfg['targets']['test_target']['_workpath'] = os.path.dirname(config_file)
    cfg['targets']['test_target']['_defpath'] = os.path.dirname(config_file)
    cfg['targets']['test_target']['data']['md_content']['doc3'] = post
    
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
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("Theme: {{ settings.theme }}, Lang: {{ settings.lang }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "yaml_content": {
                "settings": {"theme": "dark", "lang": "en"}
            }
        },
        "jinja_template": template_file,
        "command": None
    }
    
    cfg, config_file = create_test_config("test_target", target_data)
    
    try:
        mm = MarkdownMelder(cfg)
        result = mm.build_target("test_target", print_only=True)
        assert result.melded_output
        assert "Theme: dark" in result.melded_output
        assert "Lang: en" in result.melded_output
        # Check that the data is available as expected
        assert result.melded_input['settings']['theme'] == "dark"
        assert result.melded_input['settings']['lang'] == "en"
    finally:
        os.unlink(config_file)
        os.unlink(template_file)


def test_yaml_content_string():
    """Test that YAML strings can be provided via yaml_content"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("DB: {{ config.database.host }}:{{ config.database.port }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "yaml_content": {
                "config": "database:\n  host: localhost\n  port: 5432"
            }
        },
        "jinja_template": template_file,
        "command": None
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
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("---\ntitle: From File\n---\n# File Content\n\nFrom file.")
        md_file = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("{{ file_doc }}\n---\n{{ memory_doc }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "md_files": {
                "file_doc": md_file
            },
            "md_content": {
                "memory_doc": "# Memory Content\n\nFrom memory."
            }
        },
        "jinja_template": template_file,
        "command": None
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


def test_yaml_content_frontmatter_key():
    """Test that yaml_content with frontmatter prefix updates global frontmatter"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jinja', delete=False) as f:
        f.write("Author: {{ _global_frontmatter.dict.author }}")
        template_file = f.name
    
    target_data = {
        "data": {
            "yaml_content": {
                "frontmatter_extra": {"author": "YAML Author"}
            }
        },
        "jinja_template": template_file,
        "command": None
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