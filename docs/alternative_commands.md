# Alternative commands

Usually, I want to run whatever my template is through pandoc, to produce the output. Markmeld first creates markdown using the jinja template, and then passes this to pandoc to convert to the final output.

## Commands without pandoc

But sometimes, the output I make from the jinja template is *not* markdown, and that's my end product. For example, I may want to produce a `csv` file representation of some data I had in yaml format. Markmeld can also do this. In this case, you would just change the `command`, and don't use pandoc.

```
command: |
  cat > {output_file}
```

Then, your jinja template would spit out a csv file. This command basically just writes that to an output file. You can use it to get the output from jinja directly.


## Raw commands

If in a command you use `type: raw`, then the command will run directly, and not pass the template render as stdin.