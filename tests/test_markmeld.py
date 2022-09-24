print("Run test")

import markmeld
import os

from datetime import date

cfg = {"test": True}
today = date.today().strftime("%Y-%m-%d")

def compare_to_file(file, string_to_compare):
    with open(file) as f:
        file_contents = f.read()
        assert file_contents == string_to_compare


def test_MarkdownMelder_demo():
    cfg = markmeld.load_config_file("demo/_markmeld.yaml")
    cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)
    
    res = x.build_target("default", print_only=True)
    compare_to_file('demo/rendered.md', res.melded_output)

    res = x.build_target("default", print_only=False)
    print(f"res:", res)

    # os.remove()


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
