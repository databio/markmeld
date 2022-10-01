
# How to use a remote template repository

## Remotely

Point your `_markmeld.yaml` config to a remote template provider using `mm_templates`:


```yaml
mm_templates: http://databio.org/mm_templates/
```

Then you can refer to a template with a local path like this:

```yaml
targets:
  letter:
    md_template: generic.jinja
```

## Locally

Clone the repository and then point to it with a local path:

```yaml
mm_templates: local/path/to/mm_templates/
```

Then use in the same way as above.
