# Template

This is a jinja template. You can write plain markdown text into the template like this.

## YAML data

You can also refer to variables in the yaml files, using syntax like this:


{{ number_of_things }} 
{{ name_of_person }}


Which renders like this:

15 
The sundance kid

## Markdown data

You can refer to *content* in the markdown data with the `.content` attribute, using the name you put in the config file {{ some_text_data }}, which renders like this:

```
# Text content

Here is some text
```


You can also refer to the yaml metadata in your markdown files, using {{ _local_frontmatter.some_text_data.text_property }}:

```

```