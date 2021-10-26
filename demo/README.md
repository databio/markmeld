# Markmeld demo

This folder contains a basic "hello world" demo.

## Quick start
Clone this repository navigate to this folder, and run the demo like this: 

```
cd markmeld/demo
mm default
```

This will use the configuration found in [_markmeld.yaml](_markmeld.yaml), which looks like this:

```
targets:
  default:
    md_template: md_template.jinja
    recursive_render: false
output_file: "{today}_demo_output.pdf"
data_yaml:
  - some_data.yaml
data_md:
  some_text_data: some_text.md
```

This integrates the structured YAML data from [some_data.yaml](some_data.yaml) with the markdown prose in [some_text.md](some_text.md), using the [md_template.jinja](md_template.jinja) template, to render the output as [*_demo_output.pdf)](2021-10-25_demo_output.pdf).