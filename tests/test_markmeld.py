import markmeld
import os
import pytest

from datetime import date

today = date.today().strftime("%Y-%m-%d")

# We want our logger to print verbosely during testing
N_LOGGING_FMT = (
    "%(filename)12.12s:%(funcName)16.16s:%(lineno)4.4d |%(levelname)5.5s| %(message)s "
)
import logmuse

_LOGGER = logmuse.init_logger(
    name="markmeld", level="DEBUG", datefmt="%H:%M:%S", fmt=N_LOGGING_FMT
)


def compare_to_file(file, string_to_compare):
    with open(file) as f:
        file_contents = f.read()
        assert file_contents == string_to_compare


def test_output():
    cfg = markmeld.load_config_file("demo/null.yaml")
    x = markmeld.MarkdownMelder(cfg)
    res = x.build_target("default", print_only=True)
    assert res is not None
    assert res.melded_output is not None
    assert len(res.melded_output) > 0
    assert res.returncode == 0


def test_cli():
    from markmeld.cli import main

    with pytest.raises(SystemExit):
        main(
            test_args={
                "config": "tests/test_data/_markmeld_basic.yaml",
                "target": None,
                "list": True,
            }
        )


def test_MarkdownMelder_demo():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_basic.yaml")
    x = markmeld.MarkdownMelder(cfg)

    res = x.build_target("default", print_only=True)
    compare_to_file("demo/rendered.md", res.melded_output)

    outfile = f"tests/test_data/{today}_demo_output.txt"
    try:
        x.build_target("default", print_only=False)
        assert os.path.isfile(outfile)
    finally:
        if os.path.isfile(outfile):
            os.remove(outfile)


def test_loop():
    cfg = markmeld.load_config_file("demo_loop/_markmeld.yaml")
    x = markmeld.MarkdownMelder(cfg)
    res = x.build_target("default", print_only=True)
    assert "John Doe" in str(res[0].melded_output)
    assert "Jane Doe" in str(res[1].melded_output)

    # Check actual build (requires pandoc)
    john_out = f"demo_loop/{today}_demo_output_John Doe.txt"
    jane_out = f"demo_loop/{today}_demo_output_Jane Doe.txt"
    try:
        x.build_target("default")
        assert os.path.isfile(john_out)
        assert os.path.isfile(jane_out)
    finally:
        if os.path.isfile(john_out):
            os.remove(john_out)
        if os.path.isfile(jane_out):
            os.remove(jane_out)

    res2 = x.build_target("complex_loop", print_only=True)
    assert "John Doe" in str(res2[0].melded_output)
    assert "Jane Doe" in str(res2[1].melded_output)


def test_factory():
    cfg = markmeld.load_config_file("demo_factory/_markmeld.yaml")
    x = markmeld.MarkdownMelder(cfg)
    res = x.build_target("target1", print_only=True)
    assert "Target1" in str(res.melded_output)


def test_v2_basic_function():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_inherit.yaml")
    mm = markmeld.MarkdownMelder(cfg)

    res = mm.build_target("test_process_md", print_only=True)
    assert "GGnmmicHsG" in str(res.melded_output)

    res = mm.build_target("test_process_yaml", print_only=True)
    assert "rVEeqUQ1t5" in str(res.melded_output)

    res = mm.build_target("test_data_variables", print_only=True)
    assert "6s0BoZEiiN" in str(res.melded_output)

    res = mm.build_target("test_merged_frontmatter", print_only=True)
    assert "text_property_value" in str(res.melded_output)

    res = mm.build_target("test_unkeyed_yaml", print_only=True)
    assert "22" in str(res.melded_output)


def test_inherited_data_propogates_to_target():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_inherit.yaml")
    mm = markmeld.MarkdownMelder(cfg)

    res = mm.build_target("test_inherited_data_propogates_to_target", print_only=True)
    assert "xs8Nd0D98" in str(res.melded_output)

    res = mm.build_target("test_inherited_data_merges_into_target", print_only=True)
    assert "xs8Nd0D98" in str(res.melded_output)  # From root data definition
    assert "k9XFJOId0" in str(res.melded_output)  # From local target data definition

    res = mm.build_target("test_recursive_inheritance", print_only=True)
    assert "xs8Nd0D98" in str(res.melded_output)  # From deep inheritance
    assert "k9XFJOId0" in str(res.melded_output)  # From immediate inheritance
    assert "c9nmw827" in str(res.melded_output)  # Make sure order is correct

    res = mm.build_target("test_multiple_inheritance", print_only=True)
    assert "8x8x9c" in str(res.melded_output)

    res = mm.build_target("test_multiple_inheritance_plus_local", print_only=True)
    assert "0sjk8wj82" in str(res.melded_output)


def test_import():
    cfg = markmeld.load_config_wrapper("tests/test_data/_markmeld_import.yaml")
    mm = markmeld.MarkdownMelder(cfg)

    res = mm.build_target("imported_target", print_only=True)
    assert "rVEeqUQ1t5" in str(res.melded_output)

    cfg2 = markmeld.load_config_wrapper(
        "tests/test_data/_markmeld_import_relative.yaml"
    )
    mm2 = markmeld.MarkdownMelder(cfg2)

    res = mm2.build_target("imported_target", print_only=True)
    assert "qk32LK6Nv0" in str(res.melded_output)


def test_null_jinja_template():
    cfg = markmeld.load_config_wrapper(
        "tests/test_data/_markmeld_null_jinja_template.yaml"
    )
    mm = markmeld.MarkdownMelder(cfg)
    res = mm.build_target("target_name", print_only=True)
    assert res is not None
    assert res.melded_output is not None
    assert res.returncode == 0


def test_variable_variables():
    cfg = markmeld.load_config_wrapper("demo_book/book_basic/_markmeld.yaml")
    mm = markmeld.MarkdownMelder(cfg)
    res = mm.build_target("default", print_only=True)

    cfg2 = markmeld.load_config_wrapper("demo_book/book_var1/_markmeld.yaml")
    mm2 = markmeld.MarkdownMelder(cfg2)
    res2 = mm2.build_target("default", print_only=True)

    cfg3 = markmeld.load_config_wrapper("demo_book/book_var2/_markmeld.yaml")
    mm3 = markmeld.MarkdownMelder(cfg3)
    res3 = mm3.build_target("default", print_only=True)

    cfg4 = markmeld.load_config_wrapper("demo_book/variable_variables/_markmeld.yaml")
    mm4 = markmeld.MarkdownMelder(cfg4)
    res4 = mm4.build_target("default", print_only=True)

    assert res.melded_output == res2.melded_output
    assert res.melded_output == res3.melded_output
    assert "l0xn37lks8" in str(res4.melded_output)


def test_meta_target():
    cfg = markmeld.load_config_wrapper("tests/test_data/prebuild_test/_markmeld.yaml")
    mm = markmeld.MarkdownMelder(cfg)
    test_path = "tests/test_data/prebuild_test/prebuild_test_file"
    try:
        mm.build_target("my_meta_target", print_only=True)
        assert os.path.isfile(test_path)
    finally:
        if os.path.isfile(test_path):
            os.remove(test_path)


def test_postprocess():
    """Test that postprocess runs shell commands in _workpath after build"""
    cfg = markmeld.load_config_wrapper(
        "tests/test_data/postprocess_test/_markmeld.yaml"
    )
    mm = markmeld.MarkdownMelder(cfg)

    test_dir = "tests/test_data/postprocess_test"
    marker_path = f"{test_dir}/postprocess_marker.txt"
    output_path = f"{test_dir}/out/output.txt"

    # Clean up any previous test artifacts
    if os.path.isfile(marker_path):
        os.remove(marker_path)
    if os.path.isfile(output_path):
        os.remove(output_path)

    try:
        mm.build_target("test_postprocess", print_only=False)

        # Postprocess should have created the marker file in _workpath
        assert os.path.isfile(marker_path), "postprocess should create marker file"
        # Postprocess should have appended to output file
        assert os.path.isfile(output_path), "output file should exist"
        with open(output_path) as f:
            content = f.read()
        assert "postprocessed" in content, "postprocess should append to output"
    finally:
        if os.path.isfile(marker_path):
            os.remove(marker_path)
        if os.path.isfile(output_path):
            os.remove(output_path)


# Tests for assess_variable_matches function
from markmeld.melder import assess_variable_matches


def test_assess_variable_matches_all_match():
    """Test when all template variables are provided"""
    template = "Hello {{ name }}! You are {{ age }} years old."
    provided = {"name": "Alice", "age": 30, "extra": "unused"}

    result = assess_variable_matches(template, provided)

    assert result["missing"] == set()
    assert "name" in result["template_vars"]
    assert "age" in result["template_vars"]


def test_assess_variable_matches_missing_vars():
    """Test when template references variables not provided"""
    template = "Hello {{ name }}! Your email is {{ email }}."
    provided = {"name": "Alice"}

    result = assess_variable_matches(template, provided)

    assert result["missing"] == {"email"}
    assert "name" in result["template_vars"]
    assert "email" in result["template_vars"]


def test_assess_variable_matches_unused_vars():
    """Test when variables are provided but not used"""
    template = "Hello {{ name }}!"
    provided = {"name": "Alice", "age": 30, "email": "alice@example.com"}

    result = assess_variable_matches(template, provided)

    assert result["missing"] == set()
    assert result["unused"] == {"age", "email"}


def test_assess_variable_matches_underscore_filter():
    """Test that underscore-prefixed variables are filtered out"""
    template = "Hello {{ name }}! Config: {{ _internal }}."
    provided = {"name": "Alice", "_private": "secret"}

    result = assess_variable_matches(template, provided)

    # _internal is missing but should be filtered out (internal variable)
    assert "_internal" not in result["missing"]
    # _private is unused but should be filtered out (internal variable)
    assert "_private" not in result["unused"]


def test_assess_variable_matches_with_filters():
    """Test that templates using Jinja2 filters parse correctly"""
    template = "Date: {{ date | default('today') }}. Name: {{ name | upper }}."
    provided = {"date": "2025-01-01", "name": "alice"}

    result = assess_variable_matches(template, provided)

    assert result["missing"] == set()
    assert "date" in result["template_vars"]
    assert "name" in result["template_vars"]


def test_assess_variable_matches_with_loops():
    """Test that templates with for loops parse correctly"""
    template = """
    {% for item in items %}
    - {{ item.name }}: {{ item.value }}
    {% endfor %}
    """
    provided = {"items": [{"name": "a", "value": 1}]}

    result = assess_variable_matches(template, provided)

    assert result["missing"] == set()
    assert "items" in result["template_vars"]
