# Prebuild hooks

You can add a 'prebuild' hook, which runs a separate target them by adding:

```
prebuild: 
  - manuscript_supplement
  - manuscript
postbuild:
  - split
```

in `_markmeld.yaml`. This allows you to build another recipe before the current one. These recipes can be built-in recipes (which are in `mm_targets`), or can be recipes from your cfg file. I'm using built-in recipes to provide alternative commands, like building figures or splitting stuff. I guess I could make these command templates instead.