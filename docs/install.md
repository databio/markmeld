# Install

```
pip install https://github.com/databio/markmeld/archive/refs/heads/master.zip
```

Markmeld provides the `mm` executable:

```
cd demo
mm default
```

This will produce the output, automatically piping to pandoc. You can also get the raw output with `-p`, like this:

```
mm default -p > rendered.md
```
