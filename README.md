# markmeld

A simple tool for integrating structured data from `yaml` or `markdown` files into `markdown` output using `jinja2` templates. Markmeld is a *markup* *melder*. It makes it easy to restructure your structured data into different output formats.

Install:
```
pip install markmeld
```

Run:
```
cd demo
mm -c demo_meld.yaml > rendered.md
```

You can pipe the output of `mm` to pandoc, like this:

```
mm -c demo_meld.yaml | pandoc ...
```

Or you can configure a pandoc template directly in the config file:

```
latex_template: path/to/blah.tex
```

Then it will automatically run pandoc.


## Limitations and TODO

- Currently, paths are relative to the working directory. Instead, paths should be relative to the directory of the yaml file.
- Might need better error handling in case some sections aren't present in the config file. All sections are optional.
- It would be nice if the config files could import one another so I can have nested ones, so I don't have to repeat common data. Can I use PEP for that?
- some kind of list functionality to show available recipes to build? `mm list` ? Or just `mm` ?
- I want the config file to be a position argument?
- the latex template is configurable, but nothing else with pandoc. Really, should pandoc just be something you pipe `mm` output to? An alternative would be to switch to a `pandoc` section like:

```
pandoc:
  template: /path/to/template
  ...
```

And all these elements would just be considered pandoc parameters. So you can configure your whole pandoc command right there inside the config file. All `mm` is doing then is providing a convenient way to parameterize pandoc, I guess. Can you already do this with yaml frontmatter? Possibly, but maybe not for everything.
