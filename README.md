# markmeld

A simple tool for integrating structured data from `yaml` or `markdown` files into `markdown` output using `jinja2` templates. Markmeld is a *markup* *melder*. It makes it easy to restructure your structured data into different output formats. It's a companion to pandoc that allows you to merge and shape various data, from yaml or markdown documents, and output them into markdown format that can then (optionally) be piped to pandoc.

Install:
```
pip install markmeld
```

Run:
```
cd demo
mm  > rendered.md
```

You can pipe the output of `mm` to pandoc using `-p`, like this:

```
mm demo_meld.yaml -p | pandoc ...
```

Or you can configure a pandoc template directly in the config file:

```
latex_template: path/to/blah.tex
```

Then it will automatically run pandoc.


## Limitations and TODO

- [ ] Currently, paths are relative to the working directory. Instead, paths should be relative to the directory of the yaml file. (this will only matter when I start trying to build stuff using external `_markmeld.yaml` files in other folders.)
- [ ] Might need better error handling in case some sections aren't present in the config file. All sections are optional.
- [ ] It would be nice if the config files could import one another so I can have nested ones, so I don't have to repeat common data. Can I use PEP for that?
- [x] some kind of list functionality to show available recipes to build? `mm list` ? Or just `mm` ?
- [x] I want the config file to be a position argument?
- [x] the latex template is configurable, but nothing else with pandoc. Really, should pandoc just be something you pipe `mm` output to?
- [x] CLI: `mm meldsource.yaml target`
- [x] use `_markmeld.yaml` by default, so you configure by putting a `_markmeld.yaml` file in root.
- [x] `mm` without a target lists the targets.
- [ ] tab completion would be awesome (but `-l` suffices for the time being)

All `mm` is doing then is providing a convenient way to parameterize pandoc, I guess. Can you already do this with yaml frontmatter? Possibly, but maybe not for everything.

- [ ] Right now, if you want to provide markmeld with `md` data, you can either specify them explicitly, in which case you can define an identifier by which you can refer to that file, like `my_identifier: path/some_file.md`, which can then be referenced in a template with `{{ my_identifer.content }}`. But if you use `data_md_globs`, then you just give it file globs, and the identifier is the filename. I could build an alternative metadata key, like `mm_id: my_identifier`, and if you use the glob approach, it could become available under that idea. Why might this be useful? 1) For a mix/match where I want swap out one possible version of `my_identifier` with another, this way I can do that with different file names; 2) if using hedgedoc, I may not control the filename. So if it's a remote file... I guess I'd just have to make it explicit?