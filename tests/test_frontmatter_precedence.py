"""
Tests for frontmatter precedence system.

Tests the variable precedence chain (lowest to highest):
1. frontmatter: (base frontmatter in target config)
2. md frontmatter (frontmatter from markdown files)
3. yaml_files (data from YAML files)
4. variables (direct variable definitions in config)
5. frontmatter_overrides: (final overrides in target config)

This is TDD - tests should fail until the implementation is done.
"""

import pytest
import tempfile
import os
import yaml
import shutil
from markmeld import MarkdownMelder


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


class TestFrontmatterPrecedence:
    """
    Tests for the full frontmatter precedence chain.

    Uses a single fixture with variables a-f placed across all sources:

    | Variable | frontmatter: | md frontmatter | yaml_files | variables | frontmatter_overrides: | Expected |
    |----------|-------------|----------------|------------|-----------|----------------------|----------|
    | `a`      | "base"      | -              | -          | -         | -                    | "base"   |
    | `b`      | "base"      | "doc"          | -          | -         | -                    | "doc"    |
    | `c`      | "base"      | "doc"          | "yaml"     | -         | -                    | "yaml"   |
    | `d`      | "base"      | "doc"          | "yaml"     | "var"     | -                    | "var"    |
    | `e`      | "base"      | "doc"          | "yaml"     | "var"     | "override"           | "override"|
    | `f`      | -           | -              | -          | -         | "override"           | "override"|
    """

    @pytest.fixture
    def precedence_fixture(self):
        """
        Create a complete test fixture with variables across all precedence levels.

        Returns dict with paths to temp files and cleanup function.
        """
        temp_dir = tempfile.mkdtemp()

        # Create jinja template that outputs all variables
        template_content = """a={{ a }}
b={{ b }}
c={{ c }}
d={{ d }}
e={{ e }}
f={{ f }}
"""
        template_path = os.path.join(temp_dir, "template.jinja")
        with open(template_path, 'w') as f:
            f.write(template_content)

        # Create markdown file with frontmatter (b, c, d, e all set to "doc")
        md_content = """---
b: "doc"
c: "doc"
d: "doc"
e: "doc"
---
# Test Document

Content here.
"""
        md_path = os.path.join(temp_dir, "document.md")
        with open(md_path, 'w') as f:
            f.write(md_content)

        # Create YAML file (c, d, e all set to "yaml")
        yaml_data = {
            "c": "yaml",
            "d": "yaml",
            "e": "yaml"
        }
        yaml_path = os.path.join(temp_dir, "data.yaml")
        with open(yaml_path, 'w') as f:
            yaml.dump(yaml_data, f)

        # Create the full target config
        target_data = {
            "_workpath": temp_dir,
            "_defpath": temp_dir,
            "jinja_template": template_path,
            "command": None,
            # Level 1: Base frontmatter (a, b, c, d, e all set to "base")
            "frontmatter": {
                "a": "base",
                "b": "base",
                "c": "base",
                "d": "base",
                "e": "base"
            },
            "data": {
                # Level 2: MD files (b, c, d, e set to "doc" via frontmatter)
                "md_files": {
                    "doc": md_path
                },
                # Level 3: YAML files unkeyed (c, d, e set to "yaml") - merged at top level
                "yaml_globs_unkeyed": [yaml_path],
                # Level 4: Variables (d, e set to "var")
                "variables": {
                    "d": "var",
                    "e": "var"
                }
            },
            # Level 5: Frontmatter overrides (e, f set to "override")
            "frontmatter_overrides": {
                "e": "override",
                "f": "override"
            }
        }

        config = {
            "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
            "targets": {
                "test_target": target_data
            }
        }

        yield {
            "config": config,
            "temp_dir": temp_dir,
            "template_path": template_path,
            "md_path": md_path,
            "yaml_path": yaml_path
        }

        # Cleanup
        shutil.rmtree(temp_dir)

    def test_precedence_a_base_frontmatter_only(self, precedence_fixture):
        """
        Variable 'a' is only defined in frontmatter: -> should be "base"

        This tests that base frontmatter provides default values.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "a=base" in result.melded_output

    def test_precedence_b_md_overwrites_base(self, precedence_fixture):
        """
        Variable 'b' is in frontmatter: ("base") and md frontmatter ("doc")
        -> md frontmatter should win, result should be "doc"

        This tests that markdown frontmatter overrides base frontmatter.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "b=doc" in result.melded_output

    def test_precedence_c_yaml_overwrites_md(self, precedence_fixture):
        """
        Variable 'c' is in frontmatter: ("base"), md frontmatter ("doc"),
        and yaml_files ("yaml") -> yaml_files should win, result should be "yaml"

        This tests that YAML data files override markdown frontmatter.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "c=yaml" in result.melded_output

    def test_precedence_d_variables_overwrites_yaml(self, precedence_fixture):
        """
        Variable 'd' is in all sources up through variables
        -> variables should win, result should be "var"

        This tests that direct variables override YAML data files.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "d=var" in result.melded_output

    def test_precedence_e_overrides_wins_all(self, precedence_fixture):
        """
        Variable 'e' is defined at ALL levels
        -> frontmatter_overrides should win, result should be "override"

        This tests that frontmatter_overrides has highest precedence.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "e=override" in result.melded_output

    def test_precedence_f_override_only(self, precedence_fixture):
        """
        Variable 'f' is ONLY defined in frontmatter_overrides
        -> result should be "override"

        This tests that frontmatter_overrides can introduce new variables.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        assert "f=override" in result.melded_output

    def test_precedence_full_chain(self, precedence_fixture):
        """
        Test the complete precedence chain in a single assertion.

        This validates the entire system works together correctly.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        # All variables should have their expected values
        assert "a=base" in result.melded_output, "Base frontmatter failed for 'a'"
        assert "b=doc" in result.melded_output, "MD frontmatter failed to override for 'b'"
        assert "c=yaml" in result.melded_output, "YAML files failed to override for 'c'"
        assert "d=var" in result.melded_output, "Variables failed to override for 'd'"
        assert "e=override" in result.melded_output, "Frontmatter overrides failed for 'e'"
        assert "f=override" in result.melded_output, "Frontmatter overrides failed for 'f'"

    def test_global_frontmatter_reflects_precedence(self, precedence_fixture):
        """
        Test that _global_frontmatter.dict reflects the final precedence result.

        Variables should be available in _global_frontmatter with their final values.
        """
        mm = MarkdownMelder(precedence_fixture["config"])
        result = mm.build_target("test_target", print_only=True)

        gf = result.melded_input.get('_global_frontmatter', {}).get('dict', {})

        # Check that _global_frontmatter contains the correct values
        # Note: This tests that the frontmatter system properly merges all sources
        assert gf.get('a') == "base", f"Expected 'base' for 'a', got '{gf.get('a')}'"
        assert gf.get('b') == "doc", f"Expected 'doc' for 'b', got '{gf.get('b')}'"
        assert gf.get('e') == "override", f"Expected 'override' for 'e', got '{gf.get('e')}'"
        assert gf.get('f') == "override", f"Expected 'override' for 'f', got '{gf.get('f')}'"


class TestFrontmatterSimpleCases:
    """
    Tests for basic frontmatter functionality in isolation.
    """

    def test_frontmatter_base_only(self):
        """
        Test that frontmatter: provides default values when nothing else is defined.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            # Create simple template
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}\nauthor={{ author }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "title": "My Document",
                    "author": "Test Author"
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "title=My Document" in result.melded_output
            assert "author=Test Author" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_overrides_only(self):
        """
        Test that frontmatter_overrides: works when nothing else is defined.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("version={{ version }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter_overrides": {
                    "version": "2.0"
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "version=2.0" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_in_global_frontmatter_dict(self):
        """
        Test that base frontmatter values appear in _global_frontmatter.dict
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("test={{ _global_frontmatter.dict.title }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "title": "Global Title"
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "test=Global Title" in result.melded_output
            assert result.melded_input['_global_frontmatter']['dict']['title'] == "Global Title"
        finally:
            shutil.rmtree(temp_dir)


class TestLegacyPrefixRemoved:
    """
    Tests verifying that the frontmatter_* prefix stripping behavior is removed.

    The old system required variables named 'frontmatter_title' to be stripped
    to 'title' in _global_frontmatter. The new system should NOT do this stripping
    when using frontmatter: and frontmatter_overrides: keys.
    """

    def test_frontmatter_prefix_not_stripped_from_base(self):
        """
        Test that variables in frontmatter: do NOT have 'frontmatter_' prefix stripped.

        If a user defines frontmatter: { title: "X" }, it should appear as 'title'
        not require 'frontmatter_title' naming convention.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}\nfm_title={{ _global_frontmatter.dict.title }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                # Using the new clean syntax - no 'frontmatter_' prefix needed
                "frontmatter": {
                    "title": "Clean Title"
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # The title should be accessible directly
            assert "title=Clean Title" in result.melded_output
            # And also in _global_frontmatter.dict
            assert "fm_title=Clean Title" in result.melded_output

            # Verify the structure - title should be at top level
            gf_dict = result.melded_input.get('_global_frontmatter', {}).get('dict', {})
            assert 'title' in gf_dict, "title should be in _global_frontmatter.dict"
            assert gf_dict['title'] == "Clean Title"
        finally:
            shutil.rmtree(temp_dir)


class TestFrontmatterEdgeCases:
    """
    Tests for edge cases and special scenarios in frontmatter handling.
    """

    def test_empty_frontmatter_sections(self):
        """
        Test that empty frontmatter: and frontmatter_overrides: are handled gracefully.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("output=test")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {},
                "frontmatter_overrides": {}
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "output=test" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_with_nested_values(self):
        """
        Test that nested values in frontmatter work correctly.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("name={{ author.name }}\nemail={{ author.email }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "author": {
                        "name": "John Doe",
                        "email": "john@example.com"
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "name=John Doe" in result.melded_output
            assert "email=john@example.com" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_overrides_nested_merge(self):
        """
        Test that frontmatter_overrides can override nested values.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("version={{ config.version }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "config": {
                        "version": "1.0",
                        "debug": False
                    }
                },
                "frontmatter_overrides": {
                    "config": {
                        "version": "2.0"
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Override should have replaced the nested value
            assert "version=2.0" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_with_list_values(self):
        """
        Test that list values in frontmatter work correctly.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("{% for tag in tags %}{{ tag }},{% endfor %}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "tags": ["python", "testing", "yaml"]
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "python," in result.melded_output
            assert "testing," in result.melded_output
            assert "yaml," in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_none_values_in_frontmatter(self):
        """
        Test that None/null values in frontmatter are passed through correctly.

        Note: Jinja2's `default` filter only replaces undefined variables, not None.
        Use `default('x', true)` to also replace None/falsy values.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            # Use default(value, true) to also handle None values
            with open(template_path, 'w') as f:
                f.write("value={{ value | default('default_value', true) }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "value": None
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Jinja default filter with second param true replaces None
            assert "value=default_value" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestLocalFrontmatter:
    """
    Tests for _local_frontmatter functionality - per-document frontmatter tracking.
    """

    def test_local_frontmatter_per_md_file(self):
        """
        Test that _local_frontmatter contains frontmatter from each markdown file separately.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            # Create template that outputs local frontmatter
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("doc1_title={{ _local_frontmatter.doc1.dict.title }}\n")
                f.write("doc2_title={{ _local_frontmatter.doc2.dict.title }}")

            # Create two markdown files with different frontmatter
            md1_path = os.path.join(temp_dir, "doc1.md")
            with open(md1_path, 'w') as f:
                f.write("---\ntitle: Document One\nauthor: Author A\n---\n# Doc 1")

            md2_path = os.path.join(temp_dir, "doc2.md")
            with open(md2_path, 'w') as f:
                f.write("---\ntitle: Document Two\nauthor: Author B\n---\n# Doc 2")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {
                        "doc1": md1_path,
                        "doc2": md2_path
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Verify local frontmatter is preserved per document
            assert "doc1_title=Document One" in result.melded_output
            assert "doc2_title=Document Two" in result.melded_output

            # Verify _local_frontmatter structure
            local_fm = result.melded_input.get('_local_frontmatter', {})
            assert 'doc1' in local_fm
            assert 'doc2' in local_fm
            assert local_fm['doc1']['dict']['title'] == "Document One"
            assert local_fm['doc2']['dict']['title'] == "Document Two"
        finally:
            shutil.rmtree(temp_dir)

    def test_local_frontmatter_includes_fenced_format(self):
        """
        Test that _local_frontmatter provides fenced YAML format for each document.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("{{ _local_frontmatter.doc.fenced }}")

            md_path = os.path.join(temp_dir, "doc.md")
            with open(md_path, 'w') as f:
                f.write("---\ntitle: Test\n---\nContent")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {"doc": md_path}
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Fenced format should include YAML delimiters
            assert "---" in result.melded_output
            assert "title:" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestMultipleMdFilesFrontmatter:
    """
    Tests for frontmatter behavior when multiple markdown files have conflicting keys.
    """

    def test_later_md_file_wins_in_global_frontmatter(self):
        """
        Test that when multiple md files define the same key, later ones override earlier.

        Note: The order depends on dict iteration order (Python 3.7+ preserves insertion order).
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("shared={{ shared }}")

            # First file sets shared to "first"
            md1_path = os.path.join(temp_dir, "first.md")
            with open(md1_path, 'w') as f:
                f.write("---\nshared: first\nunique1: value1\n---\n# First")

            # Second file sets shared to "second"
            md2_path = os.path.join(temp_dir, "second.md")
            with open(md2_path, 'w') as f:
                f.write("---\nshared: second\nunique2: value2\n---\n# Second")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {
                        "first": md1_path,
                        "second": md2_path
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # The second file should override the first
            assert "shared=second" in result.melded_output

            # Both unique values should be present in global frontmatter
            gf = result.melded_input.get('_global_frontmatter', {}).get('dict', {})
            assert gf.get('unique1') == 'value1'
            assert gf.get('unique2') == 'value2'
        finally:
            shutil.rmtree(temp_dir)


class TestYamlContentPrecedence:
    """
    Tests for yaml_content behavior in the precedence chain.
    """

    def test_yaml_content_available_as_keyed_data(self):
        """
        Test that yaml_content data is available under its key in templates.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("theme={{ settings.theme }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "yaml_content": {
                        "settings": {"theme": "dark", "lang": "en"}
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "theme=dark" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestMdContentPrecedence:
    """
    Tests for md_content behavior in the precedence chain.
    """

    def test_md_content_frontmatter_in_global(self):
        """
        Test that frontmatter from md_content is included in _global_frontmatter.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}")

            # md_content with frontmatter in the string
            md_with_fm = """---
title: From Content
author: Memory Author
---
# Content
"""
            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_content": {
                        "doc": md_with_fm
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "title=From Content" in result.melded_output

            # Check global frontmatter
            gf = result.melded_input.get('_global_frontmatter', {}).get('dict', {})
            assert gf.get('title') == "From Content"
            assert gf.get('author') == "Memory Author"
        finally:
            shutil.rmtree(temp_dir)

    def test_md_content_dict_format_frontmatter(self):
        """
        Test that md_content with dict format (content + frontmatter keys) works.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}\ncontent={{ doc }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_content": {
                        "doc": {
                            "content": "# Hello World",
                            "frontmatter": {"title": "Dict Format Title"}
                        }
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "title=Dict Format Title" in result.melded_output
            assert "content=# Hello World" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestKeyedYamlFiles:
    """
    Tests for keyed yaml_files behavior (different from yaml_globs_unkeyed).
    """

    def test_keyed_yaml_namespaced(self):
        """
        Test that keyed yaml_files are available under their key, not at top level.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("name={{ mydata.name }}\ntop_name={{ name | default('not_set') }}")

            # Create YAML file
            yaml_path = os.path.join(temp_dir, "data.yaml")
            with open(yaml_path, 'w') as f:
                yaml.dump({"name": "John", "age": 30}, f)

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "yaml_files": {
                        "mydata": yaml_path
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Keyed YAML should be under the key
            assert "name=John" in result.melded_output
            # Should NOT be at top level (unless explicitly made available elsewhere)
            assert "top_name=not_set" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_unkeyed_yaml_at_top_level(self):
        """
        Test that yaml_globs_unkeyed merges data at top level.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("name={{ name }}")

            # Create YAML file
            yaml_path = os.path.join(temp_dir, "data.yaml")
            with open(yaml_path, 'w') as f:
                yaml.dump({"name": "Jane", "role": "admin"}, f)

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "yaml_globs_unkeyed": [yaml_path]
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Unkeyed YAML should be at top level
            assert "name=Jane" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestVariablesOverrideMdFrontmatter:
    """
    Tests for data.variables overriding md frontmatter specifically.
    """

    def test_variables_override_md_frontmatter(self):
        """
        Test that variables in data block override frontmatter from markdown files.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("author={{ author }}")

            # MD file with frontmatter
            md_path = os.path.join(temp_dir, "doc.md")
            with open(md_path, 'w') as f:
                f.write("---\nauthor: MD Author\n---\n# Content")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {"doc": md_path},
                    "variables": {"author": "Variable Author"}
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Variables should override md frontmatter
            assert "author=Variable Author" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestFrontmatterWithNoData:
    """
    Tests for frontmatter sections when there is no data block at all.
    """

    def test_frontmatter_works_without_data_block(self):
        """
        Test that frontmatter: and frontmatter_overrides: work when data block is missing.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("base={{ base }}\noverride={{ override }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {"base": "base_value"},
                "frontmatter_overrides": {"override": "override_value"}
                # Note: no "data" block
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "base=base_value" in result.melded_output
            assert "override=override_value" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestFrontmatterInheritance:
    """
    Tests for frontmatter behavior with target inheritance.
    """

    def test_frontmatter_inherits_from_parent(self):
        """
        Test that frontmatter from parent targets is inherited.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}\nauthor={{ author }}")

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {
                    "base": {
                        "_workpath": temp_dir,
                        "_defpath": temp_dir,
                        "jinja_template": template_path,
                        "command": None,
                        "frontmatter": {
                            "title": "Base Title",
                            "author": "Base Author"
                        }
                    },
                    "child": {
                        "_workpath": temp_dir,
                        "_defpath": temp_dir,
                        "inherit_from": "base",
                        "frontmatter": {
                            "title": "Child Title"
                        }
                    }
                }
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("child", print_only=True)

            # Child's title should override, but author should be inherited
            assert "title=Child Title" in result.melded_output
            assert "author=Base Author" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_overrides_inherits_and_extends(self):
        """
        Test that frontmatter_overrides works correctly with inheritance.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("title={{ title }}\nversion={{ version }}")

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {
                    "base": {
                        "_workpath": temp_dir,
                        "_defpath": temp_dir,
                        "jinja_template": template_path,
                        "command": None,
                        "frontmatter": {
                            "title": "Base Title",
                            "version": "1.0"
                        }
                    },
                    "child": {
                        "_workpath": temp_dir,
                        "_defpath": temp_dir,
                        "inherit_from": "base",
                        "frontmatter_overrides": {
                            "version": "2.0"
                        }
                    }
                }
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("child", print_only=True)

            # Title from base, version overridden by child
            assert "title=Base Title" in result.melded_output
            assert "version=2.0" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestMissingFilesHandling:
    """
    Tests for how frontmatter handles missing or invalid files.
    """

    def test_missing_md_file_does_not_crash(self):
        """
        Test that a missing md file logs a warning but doesn't crash the build.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("doc={{ doc | default('missing') }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {
                        "doc": os.path.join(temp_dir, "nonexistent.md")
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Should not crash, doc should be empty string
            assert "doc=missing" in result.melded_output or "doc=" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)


class TestComplexPrecedenceScenarios:
    """
    Tests for complex real-world precedence scenarios.
    """

    def test_md_content_and_md_files_both_contribute_frontmatter(self):
        """
        Test that both md_content and md_files contribute to global frontmatter.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("file_var={{ file_var }}\ncontent_var={{ content_var }}")

            # MD file with frontmatter
            md_path = os.path.join(temp_dir, "doc.md")
            with open(md_path, 'w') as f:
                f.write("---\nfile_var: from_file\n---\n# File Doc")

            # MD content with frontmatter
            md_content_str = """---
content_var: from_content
---
# Content Doc
"""

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "data": {
                    "md_files": {"file_doc": md_path},
                    "md_content": {"content_doc": md_content_str}
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Both should contribute to global frontmatter
            assert "file_var=from_file" in result.melded_output
            assert "content_var=from_content" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_frontmatter_base_with_data_variables(self):
        """
        Test that data.variables override frontmatter: base values.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("shared={{ shared }}\nbase_only={{ base_only }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {
                    "shared": "base_value",
                    "base_only": "only_in_base"
                },
                "data": {
                    "variables": {
                        "shared": "variable_value"
                    }
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Variables should override frontmatter: base
            assert "shared=variable_value" in result.melded_output
            # But base_only should still come through
            assert "base_only=only_in_base" in result.melded_output
        finally:
            shutil.rmtree(temp_dir)

    def test_full_precedence_with_all_sources(self):
        """
        A comprehensive test with all data sources to verify full precedence chain.

        Sources (in order of precedence, lowest to highest):
        1. frontmatter: (base)
        2. md_files frontmatter
        3. md_content frontmatter
        4. yaml_globs_unkeyed
        5. data.variables
        6. frontmatter_overrides:
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("level1={{ level1 }}\n")
                f.write("level2={{ level2 }}\n")
                f.write("level3={{ level3 }}\n")
                f.write("level4={{ level4 }}\n")
                f.write("level5={{ level5 }}\n")
                f.write("level6={{ level6 }}")

            # MD file that sets levels 2-6 to "md_file"
            md_path = os.path.join(temp_dir, "doc.md")
            with open(md_path, 'w') as f:
                f.write("---\nlevel2: md_file\nlevel3: md_file\nlevel4: md_file\nlevel5: md_file\nlevel6: md_file\n---\n# Doc")

            # MD content that sets levels 3-6 to "md_content"
            md_content_str = """---
level3: md_content
level4: md_content
level5: md_content
level6: md_content
---
# Content
"""
            # YAML file that sets levels 4-6 to "yaml"
            yaml_path = os.path.join(temp_dir, "data.yaml")
            with open(yaml_path, 'w') as f:
                yaml.dump({
                    "level4": "yaml",
                    "level5": "yaml",
                    "level6": "yaml"
                }, f)

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                # Level 1: frontmatter base (all levels set to "base")
                "frontmatter": {
                    "level1": "base",
                    "level2": "base",
                    "level3": "base",
                    "level4": "base",
                    "level5": "base",
                    "level6": "base"
                },
                "data": {
                    "md_files": {"doc": md_path},
                    "md_content": {"content": md_content_str},
                    "yaml_globs_unkeyed": [yaml_path],
                    # Level 5: variables (levels 5-6 set to "variable")
                    "variables": {
                        "level5": "variable",
                        "level6": "variable"
                    }
                },
                # Level 6: frontmatter_overrides (only level6 set to "override")
                "frontmatter_overrides": {
                    "level6": "override"
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            # Verify precedence chain
            assert "level1=base" in result.melded_output, "Level 1 should be from frontmatter: base"
            assert "level2=md_file" in result.melded_output, "Level 2 should be from md_files"
            assert "level3=md_content" in result.melded_output, "Level 3 should be from md_content"
            assert "level4=yaml" in result.melded_output, "Level 4 should be from yaml_globs_unkeyed"
            assert "level5=variable" in result.melded_output, "Level 5 should be from data.variables"
            assert "level6=override" in result.melded_output, "Level 6 should be from frontmatter_overrides:"
        finally:
            shutil.rmtree(temp_dir)


class TestGlobalVarsStructure:
    """
    Tests for _global_vars structure which differs from _global_frontmatter.
    """

    def test_global_vars_contains_all_variables(self):
        """
        Test that _global_vars contains all variables, not just frontmatter-prefixed ones.
        """
        temp_dir = tempfile.mkdtemp()

        try:
            template_path = os.path.join(temp_dir, "template.jinja")
            with open(template_path, 'w') as f:
                f.write("gv_title={{ _global_vars.title }}")

            target_data = {
                "_workpath": temp_dir,
                "_defpath": temp_dir,
                "jinja_template": template_path,
                "command": None,
                "frontmatter": {"title": "Test Title"},
                "data": {
                    "variables": {"extra": "extra_value"}
                }
            }

            config = {
                "_cfg_file_path": os.path.join(temp_dir, "_markmeld.yaml"),
                "targets": {"test": target_data}
            }

            mm = MarkdownMelder(config)
            result = mm.build_target("test", print_only=True)

            assert "gv_title=Test Title" in result.melded_output

            # Verify _global_vars structure
            gv = result.melded_input.get('_global_vars', {})
            assert gv.get('title') == "Test Title"
            assert gv.get('extra') == "extra_value"
        finally:
            shutil.rmtree(temp_dir)
