
# Markmeld config file

You produce a file called `_markmeld.yaml` to configure your project. In the file you specify any variables you want,  The `demo/_markmeld.yaml` looks like this:

```
targets:
  default:
    md_template: md_template.jinja
latex_template: pandoc_default.tex
output_file: "{today}_demo_output.pdf"
data_yaml:
  - some_data.yaml
data_md:
  some_text_data: some_text.md
```

The configurable attributes are:

- `targets`: a list of targets (outputs) to build. Each target can contain the other configurable attributes.
- `data_yaml` - a list of yaml files to make available to the templates
- `data_md` - a named list of markdown files, which will be made available to the templates
- `data_variables` - direct yaml data made available to the templates.
- `data_md_globs` - Globs, where each file will be read, and available at the key of the filename.
Any other attributes will be made available to the build system, but not to the jinja templates.

In the demo, the only target you can build is `default`. You can see the list of targets with `mm -l`. 


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

## Special variables

You'll automatically have access to:

- `{_today}` - Today's date in standard form (YYYY-MM-DD).
- `{_now}` - Current time in seconds since UNIX epoch.
- `{_frontmatter}` - A nicely priority-updated flat version of the yaml frontmatter across all provided `.md` files. The rationale here is that pandoc chokes if you provide multiple of the same key, but if you're importing files, then you could accidently include the same information multiple times. This way, these will get populated within markmeld, instead of making you handle that somehow in the jinja template.
- `_md`, `_yaml` -- these provide the keyed content you specified in your `_markmeld.yaml` config


