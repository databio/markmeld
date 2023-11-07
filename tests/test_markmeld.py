print("Run test")

import markmeld
import os
import pytest

from datetime import date

cfg = {"test": True}
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
    # cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)
    res = x.build_target("default", print_only=True)
    print(res.melded_output)


def test_cli():
    from markmeld.cli import main

    with pytest.raises(SystemExit):
        main(test_args={"config": "tests/test_data/_markmeld_basic.yaml"})


def test_MarkdownMelder_demo():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_basic.yaml")
    # cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)

    res = x.build_target("default", print_only=True)
    compare_to_file("demo/rendered.md", res.melded_output)

    res = x.build_target("default", print_only=False)
    outfile = f"tests/test_data/{today}_demo_output.txt"
    assert os.path.isfile(outfile)
    print(f"res:", res)
    os.remove(outfile)


def test_loop():
    cfg = markmeld.load_config_file("demo_loop/_markmeld.yaml")
    x = markmeld.MarkdownMelder(cfg)
    res = x.build_target("default", print_only=True)
    print(f"res:", res)
    assert "John Doe" in str(res[0].melded_output)
    assert "Jane Doe" in str(res[1].melded_output)

    # Check actual build (requires pandoc)
    res = x.build_target("default")
    assert os.path.isfile(f"demo_loop/{today}_demo_output_John Doe.txt")
    assert os.path.isfile(f"demo_loop/{today}_demo_output_Jane Doe.txt")
    os.remove(f"demo_loop/{today}_demo_output_John Doe.txt")
    os.remove(f"demo_loop/{today}_demo_output_Jane Doe.txt")

    res2 = x.build_target("complex_loop", print_only=True)
    assert "John Doe" in str(res2[0].melded_output)
    assert "Jane Doe" in str(res2[1].melded_output)
    # print(f"res:", res)


def test_factory():
    cfg = markmeld.load_config_file("demo_factory/_markmeld.yaml")
    x = markmeld.MarkdownMelder(cfg)
    # print(x.cfg)
    res = x.build_target("target1", print_only=True)
    # print(f"res:", res)
    assert "Target1" in str(res.melded_output)


def test_v2_basic_function():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_inherit.yaml")
    mm = markmeld.MarkdownMelder(cfg)
    # print(x.cfg)
    res = mm.build_target("test_process_md", print_only=True)
    # print(res.melded_output)
    assert "GGnmmicHsG" in str(res.melded_output)

    res = mm.build_target("test_process_yaml", print_only=True)
    print(res.melded_output)
    assert "rVEeqUQ1t5" in str(res.melded_output)

    res = mm.build_target("test_data_variables", print_only=True)
    print(res.melded_output)
    assert "6s0BoZEiiN" in str(res.melded_output)

    res = mm.build_target("test_merged_frontmatter", print_only=True)
    print(res.melded_output)
    assert "text_property_value" in str(res.melded_output)

    res = mm.build_target("test_unkeyed_yaml", print_only=True)
    print(res.melded_output)
    assert "22" in str(res.melded_output)


def test_inherited_data_propogates_to_target():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld_inherit.yaml")
    mm = markmeld.MarkdownMelder(cfg)

    res = mm.build_target("test_inherited_data_propogates_to_target", print_only=True)
    print(res.melded_output)
    assert "xs8Nd0D98" in str(res.melded_output)

    res = mm.build_target("test_inherited_data_merges_into_target", print_only=True)
    print(res.melded_output)
    assert "xs8Nd0D98" in str(res.melded_output)  # From root data definition
    assert "k9XFJOId0" in str(res.melded_output)  # From local target data definition

    res = mm.build_target("test_recursive_inheritance", print_only=True)
    print(res.melded_output)
    assert "xs8Nd0D98" in str(res.melded_output)  # From deep inheritance
    assert "k9XFJOId0" in str(res.melded_output)  # From immediate inheritance
    assert "c9nmw827" in str(res.melded_output)  # Make sure order is correct

    res = mm.build_target("test_multiple_inheritance", print_only=True)
    print(res.melded_output)
    assert "8x8x9c" in str(res.melded_output)

    res = mm.build_target("test_multiple_inheritance_plus_local", print_only=True)
    print(res.melded_output)
    assert "0sjk8wj82" in str(res.melded_output)


def test_import():
    cfg = markmeld.load_config_wrapper("tests/test_data/_markmeld_import.yaml")
    mm = markmeld.MarkdownMelder(cfg)

    res = mm.build_target("imported_target", print_only=True)
    print(res.melded_output)
    assert "rVEeqUQ1t5" in str(res.melded_output)

    cfg2 = markmeld.load_config_wrapper(
        "tests/test_data/_markmeld_import_relative.yaml"
    )
    mm2 = markmeld.MarkdownMelder(cfg2)

    res = mm2.build_target("imported_target", print_only=True)
    print(res.melded_output)
    assert "qk32LK6Nv0" in str(res.melded_output)


def test_null_jinja_template():
    cfg = markmeld.load_config_wrapper(
        "tests/test_data/_markmeld_null_jinja_template.yaml"
    )
    mm = markmeld.MarkdownMelder(cfg)
    res = mm.build_target("target_name", print_only=True)


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

    # print("/////" + res.melded_output + "/////")
    # print("/////" + res2.melded_output + "/////")
    # print("/////" + res3.melded_output + "/////")

    cfg4 = markmeld.load_config_wrapper("demo_book/variable_variables/_markmeld.yaml")
    mm4 = markmeld.MarkdownMelder(cfg4)
    res4 = mm4.build_target("default", print_only=True)

    assert res.melded_output == res2.melded_output
    assert res.melded_output == res3.melded_output
    assert "l0xn37lks8" in str(res4.melded_output)


def test_meta_target():
    cfg = markmeld.load_config_wrapper("tests/test_data/prebuild_test/_markmeld.yaml")
    mm = markmeld.MarkdownMelder(cfg)
    res = mm.build_target("my_meta_target", print_only=True)
    test_path = "tests/test_data/prebuild_test/prebuild_test_file"
    assert os.path.isfile(test_path)
    os.remove(test_path)
