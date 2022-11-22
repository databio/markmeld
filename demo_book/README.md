# Variable variables for book demo

This folder contains an example of how to write a generic jinja template, and encode the contents within data variables in the config file.

There are three examples that produce the same output, which can be produced using these commands:

```
mm -c book_basic/_markmeld.yaml default -p 

mm -c book_var1/_markmeld.yaml default -p 

mm -c book_var2/_markmeld.yaml default -p 

```


## Book basic

This encodes the chapters directly in the `jinja` template. It's simple, but it's not re-usable.

## Book var1

This method uses the `_md` array, and indexes into it with `data.variables` specified in the `_markmeld.yaml` file. This uses a jinja template that is reusable.

## Book var2 (recommended)

This way extracts the chapters out of the `_markmeld.yaml` config file into a standalone yaml file. This is the most flexible way, since both the `jinja` template can be reused, and the `target` could also be imported and re-used with a different `chapters.yaml` file.


