# Markmeld demo

This folder contains a demo that uses a remote note in Hedgedoc.

## Quick start

This will use the configuration found in [_markmeld.yaml](_markmeld.yaml), which looks like this:

```
targets:
  default:
    output_file: "demo_output.pdf"
    data_md:
      data: https://demo.hedgedoc.org/lZSqGjRfQ_aP2ONA-77Npg/download
```

This is using the default LaTeX template and default Jinja template to produce the [demo_output.pdf](demo_output.pdf).

You can use a different one by adding `latex_template: ...` or `jinja_template: ...` attributes to this target. The point of this demo is just to show how you could collaborate on a Markdown file, and then use markmeld to build it locally.
