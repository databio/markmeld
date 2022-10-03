print("Run test")

import markmeld
import os
import pytest

from datetime import date

cfg = {"test": True}
today = date.today().strftime("%Y-%m-%d")

# We want our logger to print verbosely during testing
N_LOGGING_FMT = "%(filename)12.12s:%(funcName)16.16s:%(lineno)4.4d |%(levelname)5.5s| %(message)s "
import logmuse
_LOGGER = logmuse.init_logger(name="markmeld", level="DEBUG", datefmt="%H:%M:%S", fmt=N_LOGGING_FMT)


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
        main(test_args={"config":"tests/test_data/demo.yaml"})

def test_MarkdownMelder_demo():
    cfg = markmeld.load_config_file("tests/test_data/demo.yaml")
    # cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)

    res = x.build_target("default", print_only=True)
    compare_to_file("demo/rendered.md", res.melded_output)

    res = x.build_target("default", print_only=False)
    outfile = f"tests/test_data/{today}_demo_output.pdf"
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
    assert os.path.isfile(f"demo_loop/{today}_demo_output_John Doe.pdf")
    assert os.path.isfile(f"demo_loop/{today}_demo_output_Jane Doe.pdf")
    os.remove(f"demo_loop/{today}_demo_output_John Doe.pdf")
    os.remove(f"demo_loop/{today}_demo_output_Jane Doe.pdf")

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


def test_v2():
    cfg = markmeld.load_config_file("tests/test_data/_markmeld2.yaml")
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



def test_null_jinja_template():
    cfg = markmeld.load_config_file("tests/test_data/null_jinja_template.yaml")
    mm = markmeld.MarkdownMelder(cfg)
    res = mm.build_target("target_name", print_only=True)

