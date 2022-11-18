# Imports

It's super useful to define global config options, and then re-use them across projects. You can do this with `imports`.So I have a global config file, say `/_markmeld_config.yaml`:

```yaml
sciquill: /home/nsheff/code/sciquill/
figczar: /home/nsheff/code/sciquill/pandoc_filters/figczar/figczar.lua
highlighter: /home/nsheff/code/sciquill/pandoc_filters/change_marker/change_marker.lua
multirefs: /home/nsheff/code/sciquill/pandoc_filters/multi-refs/multi-refs.lua
csl: /home/nsheff/code/sciquill/csl/biomed-central.csl
bibdb: /home/nsheff/code/papers/sheffield.bib
```

Now you use:
```yaml
imports:
- /_markmeld_config.yaml
```

And now I can use `{figczar}` and `{bibdb}` in `command` section of a `_markmeld.yaml` file. If you want to be really cool, maybe point to this config file with `$MARKMELD` and then use:

```yaml
imports:
- $MARKMELD
```

It works! Imports are in priority order, and lower priority than whatever you have in the local file, like `css`.  You can also define targets and import them.

