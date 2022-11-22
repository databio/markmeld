{'yaml_globs_unkeyed': ['some_data.yaml'], 'md_files': {'some_text_data': 'some_text.md'}}
# Template

This is a jinja template. You can write plain markdown text into the template like this.

## YAML data

You can also refer to variables in the yaml files, using syntax like this:


15 
The sundance kid


Which renders like this:

15 
The sundance kid

## Markdown data

You can refer to *content* in the markdown data with the `.content` attribute, using the name you put in the config file # Text content

Here is some text, which renders like this:

```
# Text content

Here is some text
```


You can also refer to the yaml metadata in your markdown files, using :

```

```
