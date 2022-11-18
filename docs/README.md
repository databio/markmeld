# <img src="img/markmeld_logo_long.svg" alt="markmeld logo" height="70">

## Introduction

Markmeld is a *markdown* *melder*. It merges `yaml` and `markdown` content using `jinja2` templates. You configure markmeld with your content in computer-readable `.md` and `.yaml` files, and markmeld helps produce polished, publication-ready versions of your content, such as a PDF or HTML format. Markmeld is useful for many types of output document, including resumes, biosketches, manuscripts, proposals, books, and more. 

## How it works

1. Store your content in computer-readable formats: `.md` for unstructured text, `.yaml` format for structured content like lists or objects. 
2. Write or find a jinja template that produces the output document you are trying to create. We have a variety of common examples in a [public repository](https://databio.org/mm_templates/).
3. Configure markmeld with a `yaml` configuration file to point to 1) your content files; and 2) your jinja template. Markmeld integrates across multiple files of either type using a jinja template.

Markmeld is useful independently, but is particularly powerful when combined with [pandoc](https://pandoc.org) -- you pipe the markmeld output in markdown format to pandoc, making it easy to format the output in a variety of downstream output types, such as HTML or PDF via LaTeX. This lets you design design powerful multi-file documents, restructured into different output formats.

![demo](img/markmeld_abstract.svg)

## Why is this better than just stringing inputs together with pandoc?

For simple use cases, you can provide pandoc a list of markdown files, which it simply concatenates. The markmeld approach provides two key benefits:

1. First, the power of a jinja template is nice. Just tell markmeld about all the content, and then using jinja I can restructure the output in whatever format I want -- not just concatenating `md` inputs in a list.

2. Second, markmeld allows you to intersperse yaml data in there. Without markmeld, you can't integrate prose content (in markdown format) with structured content (in yaml format) into one output. This is useful for something like a CV/Biosketch, where I have some prose components, and then some lists, which I'd rather draw from a structured YAML file.

For simple documents like a manuscript that don't really use much structured content and are purely gluing together prose, you can get by with just straight-up pandoc. You'd just pass multiple markdown files directly to pandoc on the command line. But even in these situations, you gain something from going the route of the jinja template with markmeld: it formalizes the linking of documents into a separate file, instead of relying the on order and content of CLI arguments to pandoc. So you can more easily write a little recipe saying, "provide these pieces of content under these names, and then use this jinja template to produce the output". So, markmeld makes that recipe reproducible.
