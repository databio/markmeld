# Advanced templates: variable variables

## The jinja md array

### How to access variable-named elements

In a typical markmeld application, you'll encode the structure of your document within the jinja file. That's great. But to make the template reusable, sometimes it's convenient to do things like specify a *list* of items that show up somewhere in the document. You can also do this by combining markmeld `data_variables` with a jinja loop through the `md` array.

Here's an example. I'm writing a book on finances. I have 3 chapters: *intro*, *credit*, and *savings*, each written in its own `.md` file. To start, I write a simple `_markmeld.yaml` config file that loads each chapter into an object:

```
targets:
  default:
    md_template: book.jinja
    output_file: "{today}_demo_output.pdf"
    data_md:
      intro: md/01-intro.md
      credit: md/02-credit.md
      savings: md/03-savings.md

```

Then, I could write a `jinja` template like this, that would simply put the chapters in order:

```
{{ intro.content }}
{{ credit.content }}
{{ savings.content }}
```

Great. That works. But the problem is that this jinja template is specific now to this particular set of chapters. Could I make that generic so that it will work with *any* book, regardless of what I name the chapter files and variables? Yes! You can do this using the magic of `data_variables`.

Instead of using those chapters directly, let's define an array of variable names, and then use a jinja loop to just loop through that array and use those values to index into the markmeld `md` object.

### The `md` array

Basically, markmeld makes available to jinja an array under the name `md` which has access to all of the markdown elements keyed by their names. So, while you can access the *intro* chapter directly with `{{ intro.content }}`, you can also access it through the `md` array using `{{ md["intro"].content }}`. Take it one step further, and this means if you have "intro" in a variable, say `myvar`, you could access the exact same content with `{{ my[myvar].content }}`.

So, let's set up an array with values as the chapter names by adding this to `_markmeld.yaml`:

```
    data_variables:
      chapters:
        - intro
        - credit
        - savings
```

This will give us access in the jinja template to a `chapters` array with those 3 values in it. So, we can switch the markmeld template to use this array like so...

```
{% for ch in chapters %}

{{ md[ch].content }}

{% endfor %}
```

And voila! We have the same output, but now we've encoded the chapter order logic in the markmeld config file, and this jinja template can be reused. It's beautiful.

