print("Run test")

import markmeld

cfg = {"test": True}

def test_MarkdownMelder():
    cfg = markmeld.load_config_file("demo/_markmeld.yaml")
    cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)
    x.meld_output({"md": {}}, cmd_data, cfg, print_only=True)
    num = 25
    assert True


markmeld.populate_cmd_data


