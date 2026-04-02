"""
Regression test: keyed yaml files named frontmatter_* must merge into _global_frontmatter.

When _manuscript.yaml is loaded as yaml_files.frontmatter_manuscript, its keys
(title, author, abstract, etc.) should appear in _global_frontmatter so that
pandoc templates can access them via $title$, $author$, etc.

This was broken on the cloud branch when process_data() was refactored and the
`if k[:11] == "frontmatter": frontmatter_temp.update(yaml_dict)` line was
accidentally dropped.
"""

import pytest
import markmeld


CFG_PATH = "tests/test_data/frontmatter_yaml/_markmeld.yaml"


@pytest.fixture
def mm():
    cfg = markmeld.load_config_wrapper(CFG_PATH)
    return markmeld.MarkdownMelder(cfg)


class TestFrontmatterYamlMerge:
    """Keyed yaml files named frontmatter_* merge into _global_frontmatter."""

    def test_title_in_global_frontmatter(self, mm):
        """Title from frontmatter_manuscript yaml should appear in rendered output."""
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        assert "title:" in output, (
            "title from _manuscript.yaml should be in the YAML frontmatter block"
        )
        assert "Test Paper Title From YAML" in output

    def test_abstract_in_global_frontmatter(self, mm):
        """Abstract from frontmatter_manuscript yaml should appear in rendered output."""
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        assert "abstract" in output.lower(), (
            "abstract from _manuscript.yaml should be in the YAML frontmatter block"
        )
        assert "abstract from _manuscript.yaml" in output.lower()

    def test_author_in_global_frontmatter(self, mm):
        """Author list from frontmatter_manuscript yaml should appear in rendered output."""
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        assert "Jane Doe" in output, (
            "Author name from _manuscript.yaml should be in the YAML frontmatter block"
        )

    def test_manuscript_content_still_present(self, mm):
        """The manuscript body content should still be in the output."""
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        assert "Introduction" in output
        assert "methods" in output.lower()

    def test_frontmatter_has_fenced_yaml(self, mm):
        """Output should start with a YAML frontmatter block (---)."""
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        assert output.strip().startswith("---"), (
            "Rendered output should start with YAML frontmatter block"
        )


class TestNonFrontmatterYamlUnchanged:
    """Keyed yaml files NOT named frontmatter_* should NOT merge into global frontmatter."""

    def test_regular_yaml_not_in_frontmatter(self):
        """A yaml file with a key not starting with 'frontmatter' stays keyed."""
        cfg = markmeld.load_config_wrapper(CFG_PATH)
        # Temporarily add a non-frontmatter yaml to the config
        cfg["targets"]["manuscript"]["data"]["yaml_files"]["metadata_extra"] = (
            "tests/test_data/frontmatter_yaml/_manuscript.yaml"
        )
        mm = markmeld.MarkdownMelder(cfg)
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output
        # The title should still be there (from frontmatter_manuscript)
        assert "Test Paper Title From YAML" in output
        # But "metadata_extra" as a key name should NOT cause a second merge
        # (it doesn't start with "frontmatter")
