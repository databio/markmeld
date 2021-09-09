# markmeld

`markmeld` is a simple tool for integrating structured data from `yaml` or `markdown` files into `markdown` output using `jinja2` templates. The name `markmeld` refers to it as a *markup* *melder*. It makes it easy to restructure your structured data into different output formats. It's a companion to pandoc that allows you to merge and shape various data, from yaml or markdown documents, and output them into markdown format that can then (optionally) be piped to pandoc.

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
- [ ] Might need better error handling in case some sections aren't present in the config file. All sections are optional. This has not been thoroughly tested.
- [ ] It would be nice if the config files could import one another so I can have nested ones, so I don't have to repeat common data. Can I use PEP for that?
- [x] some kind of list functionality to show available recipes to build? `mm list` ? Or just `mm` ? -> `mm -l`
- [x] I want the config file to be a position argument?
- [x] the latex template is configurable, but nothing else with pandoc. Really, should pandoc just be something you pipe `mm` output to?
- [x] CLI: `mm meldsource.yaml target`
- [x] use `_markmeld.yaml` by default, so you configure by putting a `_markmeld.yaml` file in root.
- [ ] `mm` without a target lists the targets.
- [x] tab completion would be awesome (but `-l` suffices for the time being)

All `mm` is doing then is providing a convenient way to parameterize pandoc, I guess. Can you already do this with yaml frontmatter? Possibly, but maybe not for everything.

- [ ] Right now, if you want to provide markmeld with `md` data, you can either specify them explicitly, in which case you can define an identifier by which you can refer to that file, like `my_identifier: path/some_file.md`, which can then be referenced in a template with `{{ my_identifer.content }}`. But if you use `data_md_globs`, then you just give it file globs, and the identifier is the filename. I could build an alternative metadata key, like `mm_id: my_identifier`, and if you use the glob approach, it could become available under that label. Why might this be useful? 1) For a mix/match where I want swap out one possible version of `my_identifier` with another, this way I can do that with different file names; 2) if using hedgedoc, I may not control the filename. So if it's a remote file... I guess I'd just have to make it explicit?

## Hooks

I also recently developed hooks. You can use them by adding:

``
    prebuild: 
      - manuscript_supplement
      - manuscript
    postbuild:
      - split
```

in `_markmeld.yaml`. This allows you to build another recipe before the current one. These recipes can be built-in recipes (which are in `mm_targets`), or can be recipes from your cfg file. I'm using built-in recipes to provide alternative commands, like building figures or splitting stuff. I guess I could make these command templates instead.

## Rationale

Why is this better than just stringing stuff together using pandoc? Well, for one, the power of a jinja template is pretty nice... so I can just provide markmeld with the documents, and then output them in whatever format I want using jinja. Furthermore, it allows me to intersperse yaml data in there more easily. Without markmeld, I couldn't really find an easy way to integrate prose content (in markdown format) with structured content (in yaml format) into one output. This is useful for something like a CV/Biosketch, where I have some prose components, and then some lists, which I'd rather draw from a structured YAML file.

For simple documents like a manuscript that don't really use much structured content and are purely gluing together prose, you can get by with just straight-up pandoc. But even in these situations, you gain something from going the route of the jinja template: it formalizes the linking of documents somehow into a separate file (as opposed to relying on order of feeding things to pandoc, for example). So you can more easily write a little recipe saying, "provide these pieces of content under these names, and then use this jinja template to produce the output". 

I also like the symmetry -- that is, becoming familiar with one system that can handle the simple documents, but is also powerful enough to add in structured content into those same documents, should it become necessary.

