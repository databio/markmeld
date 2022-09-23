print("Run test")

import markmeld

cfg = {"test": True}

def compare_to_file(file, string_to_compare):
    with open(file) as f:
        file_contents = f.read()
        assert file_contents == string_to_compare


def test_MarkdownMelder_demo():
    cfg = markmeld.load_config_file("demo/_markmeld.yaml")
    cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)
    
    res = x.build_target("default", print_only=True)
    compare_to_file('demo/rendered.md', res)

    res = x.build_target("default", print_only=False)
    print(f"res:", res)

    # os.remove()


def test_loop():
    cfg = markmeld.load_config_file("demo_loop/_markmeld.yaml")
    cmd_data = markmeld.populate_cmd_data(cfg, "default", {})
    x = markmeld.MarkdownMelder(cfg)
    
    res = x.build_target("default", print_only=True)