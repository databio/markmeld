"""
Tests for frontmatter/variable precedence, content sources (md_content /
yaml_content), section extraction, and target inheritance.
"""

import pytest
import yaml
import frontmatter
import markmeld

CFG_PATH = "tests/test_data/frontmatter_yaml/_markmeld.yaml"


class TestPrecedenceChain:
    """
    Variable precedence, lowest to highest:
    frontmatter: < md_files < md_content < yaml < data.variables < frontmatter_overrides:
    """

    def test_full_precedence_with_all_sources(self, mm_target, tmp_path):
        template = "".join(f"level{n}={{{{ level{n} }}}}\n" for n in range(1, 7))
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(
            yaml.dump({"level4": "yaml", "level5": "yaml", "level6": "yaml"})
        )

        result = mm_target(
            template,
            frontmatter={f"level{n}": "base" for n in range(1, 7)},
            md_files={
                "doc": "---\nlevel2: md_file\nlevel3: md_file\nlevel4: md_file\n"
                "level5: md_file\nlevel6: md_file\n---\n# Doc"
            },
            data={
                "md_content": {
                    "content": "---\nlevel3: md_content\nlevel4: md_content\n"
                    "level5: md_content\nlevel6: md_content\n---\n# Content"
                },
                "yaml_globs_unkeyed": [str(yaml_path)],
                "variables": {"level5": "variable", "level6": "variable"},
            },
            frontmatter_overrides={"level6": "override"},
        )

        assert "level1=base" in result.melded_output
        assert "level2=md_file" in result.melded_output
        assert "level3=md_content" in result.melded_output
        assert "level4=yaml" in result.melded_output
        assert "level5=variable" in result.melded_output
        assert "level6=override" in result.melded_output

        gf = result.melded_input.get("_global_frontmatter", {}).get("dict", {})
        assert gf.get("level1") == "base"
        assert gf.get("level6") == "override"

    def test_frontmatter_base_only(self, mm_target):
        result = mm_target(
            "title={{ title }}\nauthor={{ author }}",
            frontmatter={"title": "My Document", "author": "Test Author"},
        )
        assert "title=My Document" in result.melded_output
        assert "author=Test Author" in result.melded_output

    def test_frontmatter_overrides_only(self, mm_target):
        """frontmatter_overrides: can introduce a variable with nothing else defined."""
        result = mm_target(
            "version={{ version }}", frontmatter_overrides={"version": "2.0"}
        )
        assert "version=2.0" in result.melded_output

    def test_variables_override_md_frontmatter(self, mm_target):
        result = mm_target(
            "author={{ author }}",
            md_files={"doc": "---\nauthor: MD Author\n---\n# Content"},
            data={"variables": {"author": "Variable Author"}},
        )
        assert "author=Variable Author" in result.melded_output


class TestFrontmatterStructure:
    """_global_frontmatter, _global_vars, and _local_frontmatter structure."""

    def test_frontmatter_in_global_frontmatter_dict(self, mm_target):
        result = mm_target(
            "test={{ _global_frontmatter.dict.title }}",
            frontmatter={"title": "Global Title"},
        )
        assert "test=Global Title" in result.melded_output
        assert (
            result.melded_input["_global_frontmatter"]["dict"]["title"]
            == "Global Title"
        )

    def test_frontmatter_prefix_not_stripped_from_base(self, mm_target):
        """frontmatter: {title: X} needs no legacy 'frontmatter_title' naming."""
        result = mm_target(
            "title={{ title }}\nfm_title={{ _global_frontmatter.dict.title }}",
            frontmatter={"title": "Clean Title"},
        )
        assert "title=Clean Title" in result.melded_output
        assert "fm_title=Clean Title" in result.melded_output
        gf_dict = result.melded_input.get("_global_frontmatter", {}).get("dict", {})
        assert gf_dict["title"] == "Clean Title"

    def test_global_vars_contains_all_variables(self, mm_target):
        result = mm_target(
            "gv_title={{ _global_vars.title }}",
            frontmatter={"title": "Test Title"},
            data={"variables": {"extra": "extra_value"}},
        )
        assert "gv_title=Test Title" in result.melded_output
        gv = result.melded_input.get("_global_vars", {})
        assert gv.get("title") == "Test Title"
        assert gv.get("extra") == "extra_value"

    def test_local_frontmatter_per_md_file(self, mm_target):
        result = mm_target(
            "doc1_title={{ _local_frontmatter.doc1.dict.title }}\n"
            "doc2_title={{ _local_frontmatter.doc2.dict.title }}",
            md_files={
                "doc1": "---\ntitle: Document One\nauthor: Author A\n---\n# Doc 1",
                "doc2": "---\ntitle: Document Two\nauthor: Author B\n---\n# Doc 2",
            },
        )
        assert "doc1_title=Document One" in result.melded_output
        assert "doc2_title=Document Two" in result.melded_output
        local_fm = result.melded_input.get("_local_frontmatter", {})
        assert local_fm["doc1"]["dict"]["title"] == "Document One"
        assert local_fm["doc2"]["dict"]["title"] == "Document Two"

    def test_local_frontmatter_includes_fenced_format(self, mm_target):
        result = mm_target(
            "{{ _local_frontmatter.doc.fenced }}",
            md_files={"doc": "---\ntitle: Test\n---\nContent"},
        )
        assert "---" in result.melded_output
        assert "title:" in result.melded_output

    def test_later_md_file_wins_in_global_frontmatter(self, mm_target):
        result = mm_target(
            "shared={{ shared }}",
            md_files={
                "first": "---\nshared: first\nunique1: value1\n---\n# First",
                "second": "---\nshared: second\nunique2: value2\n---\n# Second",
            },
        )
        assert "shared=second" in result.melded_output
        gf = result.melded_input.get("_global_frontmatter", {}).get("dict", {})
        assert gf.get("unique1") == "value1"
        assert gf.get("unique2") == "value2"

    def test_keyed_yaml_namespaced(self, mm_target):
        result = mm_target(
            "name={{ mydata.name }}\ntop_name={{ name | default('not_set') }}",
            yaml_files={"mydata": {"name": "John", "age": 30}},
        )
        assert "name=John" in result.melded_output
        assert "top_name=not_set" in result.melded_output

    def test_unkeyed_yaml_at_top_level(self, mm_target, tmp_path):
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(yaml.dump({"name": "Jane", "role": "admin"}))
        result = mm_target(
            "name={{ name }}", data={"yaml_globs_unkeyed": [str(yaml_path)]}
        )
        assert "name=Jane" in result.melded_output

    def test_md_content_and_md_files_both_contribute_frontmatter(self, mm_target):
        result = mm_target(
            "file_var={{ file_var }}\ncontent_var={{ content_var }}",
            md_files={"file_doc": "---\nfile_var: from_file\n---\n# File Doc"},
            data={
                "md_content": {
                    "content_doc": "---\ncontent_var: from_content\n---\n# Content Doc"
                }
            },
        )
        assert "file_var=from_file" in result.melded_output
        assert "content_var=from_content" in result.melded_output


class TestContentSources:
    """md_content / yaml_content input formats."""

    def test_md_content_raw_string(self, mm_target):
        result = mm_target(
            "{{ doc1 }}",
            data={"md_content": {"doc1": "# Hello World\n\nThis is a test."}},
        )
        assert "# Hello World" in result.melded_output
        assert "This is a test." in result.melded_output

    def test_md_content_raw_string_with_frontmatter(self, mm_target):
        md_with_fm = "---\ntitle: From Content\nauthor: Memory Author\n---\n# Content\n"
        result = mm_target(
            "title={{ title }}", data={"md_content": {"doc": md_with_fm}}
        )
        assert "title=From Content" in result.melded_output
        gf = result.melded_input.get("_global_frontmatter", {}).get("dict", {})
        assert gf.get("title") == "From Content"
        assert gf.get("author") == "Memory Author"

    def test_md_content_dict_format(self, mm_target):
        result = mm_target(
            "Title: {{ _global_frontmatter.dict.title }}\n"
            "Author: {{ _global_frontmatter.dict.author }}\n{{ doc }}",
            data={
                "md_content": {
                    "doc": {
                        "content": "# Document\n\nContent here.",
                        "frontmatter": {"title": "Test Doc", "author": "Test Author"},
                    }
                }
            },
        )
        assert "Title: Test Doc" in result.melded_output
        assert "Author: Test Author" in result.melded_output
        assert "# Document" in result.melded_output
        gf = result.melded_input["_global_frontmatter"]["dict"]
        assert gf["title"] == "Test Doc"
        assert gf["author"] == "Test Author"

    def test_md_content_frontmatter_post_object(self, mm_target):
        post = frontmatter.Post("# Post Content\n\nThis is a post.")
        post.metadata = {"date": "2024-01-01", "category": "test"}
        result = mm_target(
            "Category: {{ _global_frontmatter.dict.category }}\n{{ doc3 }}",
            data={"md_content": {"doc3": post}},
        )
        assert "Category: test" in result.melded_output
        assert "# Post Content" in result.melded_output

    def test_yaml_content_dict(self, mm_target):
        result = mm_target(
            "Theme: {{ settings.theme }}, Lang: {{ settings.lang }}",
            data={"yaml_content": {"settings": {"theme": "dark", "lang": "en"}}},
        )
        assert "Theme: dark" in result.melded_output
        assert "Lang: en" in result.melded_output
        assert result.melded_input["settings"]["theme"] == "dark"
        assert result.melded_input["settings"]["lang"] == "en"

    def test_yaml_content_string(self, mm_target):
        result = mm_target(
            "DB: {{ config.database.host }}:{{ config.database.port }}",
            data={
                "yaml_content": {"config": "database:\n  host: localhost\n  port: 5432"}
            },
        )
        assert "DB: localhost:5432" in result.melded_output

    def test_combined_file_and_content(self, mm_target):
        result = mm_target(
            "{{ file_doc }}\n---\n{{ memory_doc }}",
            md_files={
                "file_doc": "---\ntitle: From File\n---\n# File Content\n\nFrom file."
            },
            data={"md_content": {"memory_doc": "# Memory Content\n\nFrom memory."}},
        )
        assert "# File Content" in result.melded_output
        assert "From file." in result.melded_output
        assert "# Memory Content" in result.melded_output
        assert "From memory." in result.melded_output


class TestSectionExtraction:
    """extract_sections lifts a body '# Abstract' heading into the `abstract` var."""

    TEMPLATE = "ABSTRACT:{{ abstract }}|BODY:{{ body }}"

    def test_extract_abstract_default_on(self, mm_target):
        body = "# Abstract\n\nThis is the abstract.\n\n# Introduction\n\nIntro body."
        result = mm_target(self.TEMPLATE, data={"md_content": {"body": body}})
        assert "ABSTRACT:This is the abstract." in result.melded_output
        assert "# Abstract" not in result.melded_output
        assert "This is the abstract." not in result.melded_output.split("BODY:")[1]
        assert "# Introduction" in result.melded_output
        assert "Intro body." in result.melded_output

    def test_extract_abstract_h2_section_span(self, mm_target):
        """An H2 '## Abstract' section ends at the next H2; later sections stay."""
        body = (
            "## Abstract\n\nAbstract prose here.\n\n## Methods\n\nMethods prose here."
        )
        result = mm_target(self.TEMPLATE, data={"md_content": {"body": body}})
        assert "ABSTRACT:Abstract prose here." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "Abstract prose here." not in body_out
        assert "## Methods" in body_out
        assert "Methods prose here." in body_out

    def test_extract_abstract_frontmatter_wins(self, mm_target):
        body = "# Abstract\n\nBody abstract text.\n\n# Intro\n\nIntro."
        result = mm_target(
            self.TEMPLATE,
            data={
                "md_content": {
                    "body": {
                        "content": body,
                        "frontmatter": {"abstract": "FM abstract"},
                    }
                }
            },
        )
        assert "ABSTRACT:FM abstract" in result.melded_output
        assert "# Abstract" in result.melded_output
        assert "Body abstract text." in result.melded_output

    def test_extract_abstract_opt_out(self, mm_target):
        body = "# Abstract\n\nBody abstract text."
        result = mm_target(
            self.TEMPLATE,
            extract_sections={"abstract": None},
            data={"md_content": {"body": body}},
        )
        assert "ABSTRACT:|BODY:" in result.melded_output
        assert "# Abstract" in result.melded_output
        assert "Body abstract text." in result.melded_output

    def test_extract_abstract_disable_all(self, mm_target):
        body = "# Abstract\n\nBody abstract text."
        result = mm_target(
            self.TEMPLATE, extract_sections=False, data={"md_content": {"body": body}}
        )
        assert "ABSTRACT:|BODY:" in result.melded_output
        assert "# Abstract" in result.melded_output
        assert "Body abstract text." in result.melded_output

    def test_extract_abstract_shallowest_wins(self, mm_target):
        """Abstract at both H1 and H2: the H1 section is captured."""
        body = (
            "# Abstract\n\nTop-level abstract.\n\n"
            "## Details\n\n### Abstract\n\nNested abstract.\n"
        )
        result = mm_target(self.TEMPLATE, data={"md_content": {"body": body}})
        assert "ABSTRACT:Top-level abstract." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "Top-level abstract." not in body_out

    def test_extract_abstract_override_heading_names(self, mm_target):
        body = "# Summary\n\nSummary prose.\n\n# Abstract\n\nAbstract prose."
        result = mm_target(
            self.TEMPLATE,
            extract_sections={"abstract": ["Summary"]},
            data={"md_content": {"body": body}},
        )
        assert "ABSTRACT:Summary prose." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "Summary prose." not in body_out
        assert "# Abstract" in body_out
        assert "Abstract prose." in body_out

    def test_extract_abstract_bold_heading(self, mm_target):
        body = (
            "# **Title**\n\n## **Abstract**\n\nBold-heading abstract.\n\n"
            "## **Introduction**\n\nIntro."
        )
        result = mm_target(self.TEMPLATE, data={"md_content": {"body": body}})
        assert "ABSTRACT:Bold-heading abstract." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "Bold-heading abstract." not in body_out
        assert "## **Introduction**" in body_out

    def test_extract_abstract_via_md_files(self, mm_target):
        """Extraction also applies to md_files sources (same code path)."""
        result = mm_target(
            self.TEMPLATE,
            md_files={
                "body": "# Abstract\n\nFile abstract text.\n\n# Body\n\nBody text."
            },
        )
        assert "ABSTRACT:File abstract text." in result.melded_output
        body_out = result.melded_output.split("BODY:")[1]
        assert "File abstract text." not in body_out
        assert "# Body" in body_out


class TestEdgeCases:
    @pytest.mark.parametrize(
        "kwargs, template, expected",
        [
            (
                dict(frontmatter={}, frontmatter_overrides={}),
                "output=test",
                "output=test",
            ),
            (
                dict(
                    frontmatter={
                        "author": {"name": "John Doe", "email": "john@example.com"}
                    }
                ),
                "name={{ author.name }}\nemail={{ author.email }}",
                "name=John Doe\nemail=john@example.com",
            ),
            (
                dict(frontmatter={"tags": ["python", "testing", "yaml"]}),
                "{% for tag in tags %}{{ tag }},{% endfor %}",
                "python,testing,yaml,",
            ),
            (
                dict(frontmatter={"value": None}),
                "value={{ value | default('default_value', true) }}",
                "value=default_value",
            ),
        ],
        ids=["empty_sections", "nested_dict", "list_values", "none_values"],
    )
    def test_frontmatter_value_types(self, mm_target, kwargs, template, expected):
        result = mm_target(template, **kwargs)
        assert expected in result.melded_output

    def test_frontmatter_overrides_nested_merge(self, mm_target):
        result = mm_target(
            "version={{ config.version }}",
            frontmatter={"config": {"version": "1.0", "debug": False}},
            frontmatter_overrides={"config": {"version": "2.0"}},
        )
        assert "version=2.0" in result.melded_output

    def test_missing_md_file_does_not_crash(self, mm_target, tmp_path):
        """A missing md_files source is skipped and its variable resolves to
        an empty string (not Jinja Undefined), so `| default(...)` -- which
        only kicks in for Undefined -- has no effect here."""
        result = mm_target(
            "doc={{ doc | default('missing') }}",
            data={"md_files": {"doc": str(tmp_path / "nonexistent.md")}},
        )
        assert result.melded_output == "doc="

    def test_frontmatter_works_without_data_block(self, mm_target):
        result = mm_target(
            "base={{ base }}\noverride={{ override }}",
            frontmatter={"base": "base_value"},
            frontmatter_overrides={"override": "override_value"},
        )
        assert "base=base_value" in result.melded_output
        assert "override=override_value" in result.melded_output


class TestInheritance:
    def test_frontmatter_inherits_from_parent(self, mm_target, tmp_path):
        template_path = tmp_path / "template.jinja"
        template_path.write_text("title={{ title }}\nauthor={{ author }}")
        result = mm_target(
            None,
            target_name="child",
            inherit_from="base",
            frontmatter={"title": "Child Title"},
            targets={
                "base": {
                    "jinja_template": str(template_path),
                    "command": None,
                    "frontmatter": {"title": "Base Title", "author": "Base Author"},
                }
            },
        )
        assert "title=Child Title" in result.melded_output
        assert "author=Base Author" in result.melded_output

    def test_frontmatter_overrides_inherits_and_extends(self, mm_target, tmp_path):
        template_path = tmp_path / "template.jinja"
        template_path.write_text("title={{ title }}\nversion={{ version }}")
        result = mm_target(
            None,
            target_name="child",
            inherit_from="base",
            frontmatter_overrides={"version": "2.0"},
            targets={
                "base": {
                    "jinja_template": str(template_path),
                    "command": None,
                    "frontmatter": {"title": "Base Title", "version": "1.0"},
                }
            },
        )
        assert "title=Base Title" in result.melded_output
        assert "version=2.0" in result.melded_output


class TestFrontmatterYamlMerge:
    """
    Regression: keyed yaml files named frontmatter_* must merge into
    _global_frontmatter. When _manuscript.yaml is loaded as
    yaml_files.frontmatter_manuscript, its keys (title, author, abstract,
    etc.) should appear in _global_frontmatter so pandoc templates can
    access them via $title$, $author$, etc. This broke on the cloud branch
    when process_data() was refactored and the
    `if k[:11] == "frontmatter": frontmatter_temp.update(yaml_dict)` line
    was accidentally dropped.
    """

    @pytest.fixture
    def mm(self):
        cfg = markmeld.load_config_wrapper(CFG_PATH)
        return markmeld.MarkdownMelder(cfg)

    def test_frontmatter_manuscript_yaml_merges_into_global_frontmatter(self, mm):
        result = mm.build_target("manuscript", print_only=True)
        output = result.melded_output

        assert output.strip().startswith("---")
        assert "title:" in output
        assert "Test Paper Title From YAML" in output
        assert "abstract" in output.lower()
        assert "abstract from _manuscript.yaml" in output.lower()
        assert "Jane Doe" in output
        assert "Introduction" in output
        assert "methods" in output.lower()

    def test_regular_yaml_key_stays_namespaced(self):
        """A yaml_files key not prefixed 'frontmatter' stays under its own
        key instead of merging into _global_frontmatter."""
        cfg = markmeld.load_config_wrapper(CFG_PATH)
        cfg["targets"]["manuscript"]["data"]["yaml_files"][
            "metadata_extra"
        ] = "_manuscript.yaml"
        mm_ = markmeld.MarkdownMelder(cfg)
        result = mm_.build_target("manuscript", print_only=True)
        assert (
            result.melded_input["metadata_extra"]["title"]
            == "Test Paper Title From YAML"
        )
        assert (
            "metadata_extra" not in result.melded_input["_global_frontmatter"]["dict"]
        )
