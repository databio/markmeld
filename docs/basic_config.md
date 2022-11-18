
# Markmeld config file

## Definition of terms

- **target** - A specific recipe to run that usually produces an output to build.
- **configuration file** - A `yaml` file that configures markmeld and specifies targets (Default:  `_markmeld.yaml`).
- **data** - Content, either in markdown or yaml format, used to produce a target.
- **template** - A [jinja2](https://palletsprojects.com/p/jinja/) file defining how the input will be integrated to produce the output.

## A simple example

You write `_markmeld.yaml` to configure your project. Here's a simple example, `demo/_markmeld.yaml`:

```yaml
targets:
  target1:
    latex_template: pandoc_default.tex
    output_file: "{today}_demo_output.pdf"  
    jinja_template: jinja_template.jinja
    data:
      yaml_files:
        - some_data.yaml
      md_files:
        some_text_data: some_text.md
```

## Root config file variables

The configuration file must define a `targets` block. This block contains a series of named targets, in the example, `target1` is the only target defined in this configuration file.

The configurable attributes are:

- `version`: Should be "1" for the version 1 of the markmeld configuration specification.
- `targets`: a list of targets (outputs) to build. Each target can contain the other configurable attributes.
- `target_factories`: a list of target factories
- `imports`: A list of markmeld configuration files imported by the current file.
- `imports_relative`: Exactly like `imports`, but the imported targets will be built relative to the importing file.

## The targets section

- `data`: the main section that points to the content. Data sub-attributes:
    - `md_files`: a named list of markdown files, which will be made available to the templates
    - `md_globs`: Globs, where each file will be read, and available at the key of the filename.
    - `yaml_files`: a list of yaml files to make available to the templates
    - `yaml_globs`: a list of globs (regexes) to yaml files, which will be keyed by filename
    - `yaml_globs_unkeyed`: a list of globs (regexes) to yaml files, which will be directly available
    - `variables`: direct yaml data made available to the templates.
- `inherit_from`: Defines a base target; any base attributes will be available to the current target, with the local target taking priority in case of conflict.
- `jinja_template`: path to the jinja template, relative to the config file where it is defined.
- `loop`: used to specify a `multi-output` target.
- `prebuild`: A list of other targets to build before the current target is built
- `command`: Shell command to execute to build the target. 

Any other attributes will be made available to the build system, but not to the jinja templates.


## Target inheritance

Sometimes you want to define multiple targets that all share some content, or template, or other properties. Markmeld handles this with the `inherit_from` directive.

Example:

```yaml
targets:
  base_target:
    ...
  target2:
    inherits_from: base_target
    data:
      ...
```

If a target has an `inherit_from` attribute, then one or more targets will first be pre-loaded and processed. The targets are loaded in the order listed, with the specified target the last one, so attributes with the same name will have the highest priority.


