# <img src="https://raw.githubusercontent.com/databio/markmeld/master/docs/img/markmeld_logo_long.svg?sanitize=true" alt="markmeld logo" height="70">

Markmeld is a markdown melder. It merges yaml and markdown content using jinja2 templates. You configure markmeld with your content in computer-readable .md and .yaml files, and markmeld helps produce polished, publication-ready versions of your content, such as a PDF or HTML format. Markmeld is useful for many types of output document, including resumes, biosketches, manuscripts, proposals, books, and more. 

Read the complete documentation at [markmeld.databio.org](https://markmeld.databio.org).

## Automatic abstract extraction

A markdown paper written as plain prose with an `# Abstract` heading has that
section lifted into the `abstract` variable automatically (and stripped from the
body), so it renders in a template's abstract slot just like a frontmatter
`abstract:` would. A frontmatter `abstract:` still takes precedence. Opt a target
out with `extract_sections: {abstract: null}`, disable all extraction with
`extract_sections: false`, or override the heading names with
`extract_sections: {abstract: [Abstract, Summary]}`.

## Testing

Test with

```
pytest
```

You can also just build the demos.

```
cd demo
mm default
```
