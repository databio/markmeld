# Multi-output targets

This folder contains a demo that shows how to use *multi-output targets*. Typical targets produce only a single output, but if you specify a *loop* variable and provide an array, you can have a target that produces multiple outputs.

## Motivation

This is useful for something like a mail merge, where you'd write a single letter, but want to produce it with slight differences such as the name of the recipient.


## Quick start

You do this by adding a loop variable to a target in `_markmeld.yaml`:

```
targets:
  target_name:
    loop:
      loop_data: recipients
      assign_to: recipient
```
The *loop* attribute has two sub-attributes:
- **loop_data**: Specify the name of the object that contains the data you want to loop over. This target will create one output per element in this array. The array can be either of primitive types (like strings), or can be an array of objects.
- **assign_to**: This is the name of the variable that each element in loop_data will be assigned to. This is how you will access the individual element, both in the command templates and in the jinja templates.

## Loop data: array of strings

In the simple example, the array data (found in `some_data.yaml`) looks like this:

```
recipients:
  - "John Doe"
  - "Jane Doe"
```

This target will create 1 outputs, one for each recipient.

### Loop data: array of objects

If you have a more complicated needs, like more than one element per loop iteration, then you can use a array of objects like this:

```
recipients:
  - name: "John Doe"
    institution: "University of Virginia"
  - name: "Jane Doe"
    institution: "Brigham Young University"
```

See how the `_markmeld.yaml` file uses this information:

```
targets:
  default:
    output_file: "{today}_demo_output_{recipient}.pdf"
    loop:
      loop_data: recipients
      assign_to: recipient
    md_template: md_template.jinja
    recursive_render: false
    data_yaml:
    - some_data.yaml
  complex_loop:
    output_file: "{today}_demo_output_complex_{recipient[name]}.pdf"
    loop:
      loop_data: recipients
      assign_to: recipient
    md_template: md_template_complex.jinja
    recursive_render: false
    data_yaml:
    - complex_loop.yaml
data_md:
  some_text_data: some_text.md
```

We just have to make sure the `output_file` variable uses the array data in some way (in this case, it's `{recipient}`, because that's what we put under `assign_to`). This will create a separate output, with a separate output file name, for each iteration of the loop.

You thus produce multiple outputs with a single `mm` build call.