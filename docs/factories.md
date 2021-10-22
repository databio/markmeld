# Features

## Target output loops

Target output loops allow you to produce multiple outputs from a single target. They are not implemented yet

## Target factories

Target factories^1 are functions that generate lots of targets programatically. Without target factories, every target has to be specified individually in your `_markmeld.yaml` config file. Target factories provide a very powerful way to produce a lot of targets with very little effort. 

### Example use case

Say I have a folder with a bunch of `.md` files and I'd like to build a PDF for each of them. I want to build each one independently, not all at once, so a target output loop is not the right answer -- I need a separate target for each file. I could add each target to the `_markmeld.yaml` file and that would work, but wouldn't it be nice if I could somehow just say, "I want every markdown file in this folder to be its own target", and then leave it at that? This way, I could add a new target to the project by just adding a new `.md` file to the folder -- no change would be required in `_markmeld.yaml`.

### Built-in target factories

There are built-in target factories and custom target factories. You can use a built-in factory with no further requirement, and one example is the `glob` factory, which solves the above use case. You can add it to your 

```
imports:
  - $MMCFG
target_factories:
- glob:
    path: "*.md"
- glob:
    path: "*/*.md"
    name: "folder"
md_template: /home/nsheff/code/sciquill/markmeld_templates/generic.jinja
latex_template: /home/nsheff/code/sciquill/tex_templates/shefflab.tex
```


### Custom target factories

Custom target factories are Python packages. Once you've installed the package, you can use the target factory just like a built-in factory. To create one, you just have to follow 2 guidelines:

#### 1. Add entry_points to setup.py

The `setup.py` file uses `entry_points` to map target factory name to function.

    entry_points={
        'markmeld.factories': 'factory_name=packagename:my_function',
        }

The format is: 'markmeld.factories': 'FACTORY_NAME=FACTORY_PACKAGE_NAME:FUNCTION_NAME'.

- "FACTORY_NAME" can be any unique identifier for your factory
- "FACTORY_PACKAGE_NAME" must be the name of python package the holds your factory.
- "FUNCTION_NAME" must match the name of the function in your package


#### 2. Write functions to call

The factory function name must correspond to what you specify in `setup.py` in the entry points above. These functions must take a Python `dict` object as sole parameter, and must return a `targets` object. The `dict` object provided will be any additional variables given by the user in `_markmeld.yaml`, which is how users can parameterize the factory. For example:

```
target_factories:
- glob:
    path: "*/*.md"
    name: "folder"
```

Markmeld will pass this object to the registered function for the `glob` factory:

```
{ path: "*/*.md"
  name: "folder": }
```

The function is expected to return a `targets` object, that will be used to `update` the `targets` object specified in `_markmeld.yaml`.


[^1]: Name borrowed from the excellent [targets R package](https://books.ropensci.org/targets/).