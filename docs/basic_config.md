
# Markmeld config file

## Definition of terms

- **target** - A specific recipe to run that produces an output to build.
- **configuration file** - A `yaml` file, by default named `_markmeld.yaml`, that configures markmeld. The configuration file contains the targets.
- **data** - Content, either in markdown or yaml format, used to produce a target.
- **template** - A template defined in [jinja2](https://palletsprojects.com/p/jinja/).

## A simple example

You produce a file called `_markmeld.yaml` to configure your project. Here's a simple example, `demo/_markmeld.yaml`:

```yaml
targets:
  target1:
    latex_template: pandoc_default.tex
    output_file: "{today}_demo_output.pdf"  
    md_template: md_template.jinja
    data:
      yaml_files:
        - some_data.yaml
      md_files:
        some_text_data: some_text.md
```

The configuration file must define a `targets` block. This block contains a series of named targets, in the example, `target1` is the only target defined in this configuration file.

The configurable attributes are:

- `targets`: a list of targets (outputs) to build. Each target can contain the other configurable attributes.
- `data_yaml` - a list of yaml files to make available to the templates
- `data_md` - a named list of markdown files, which will be made available to the templates
- `data_variables` - direct yaml data made available to the templates.
- `data_md_globs` - Globs, where each file will be read, and available at the key of the filename.
Any other attributes will be made available to the build system, but not to the jinja templates.

In the demo, the only target you can build is `target1`. You can see the list of targets with `mm -l`. 

## Version 2

The markmeld config file has three main sections: `targets`, `data`, `imports`, and `build_vars`.

### targets section

The `targets` section defines each target.

```
targets:
  target_name_1:
  	jinja_template: relative/path/to/tpl.jinja
    ...
  target_name_2:
    jinja_template: relative/path/to/tpl2.jinja
    ...
```

Each target may then define:

- `jinja_template`: path to the jinja template, relative to the config file where it is defined.
- `jinja_import_relative`: Set to `true` to make the jinja template relative to the importing file, rather than the working directory. Defaults to `false`.
