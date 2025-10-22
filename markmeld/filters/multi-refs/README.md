# multi-refs pandoc filter

## Introduction and rationale

This filter lets you have multiple references sections. It's similar to the earlier `section-refs.lua` filter, but provides a bit more control: instead of automatically generating a bibliography for every section, it lets the user select where the bibliographies will go by including `multi-refs` divs. Each div will display the references that have accumulated to that point in the document.

I use this to divide my references section into one for the primary manuscript, and a separate references section for supplemental text.

## Configuration

### Specifying bibliographies

Place this in your markdown file to specify where you want your bibliography placed:

```
<div class="multi-refs"></div>
```

You can put that in multiple places and it will just show the citations that have accumulated to that point in the document.

### Duplicate references

What do you want to do if you have a reference that repeats across sections? Do you want it to be listed in both bibliographies, or only the first one?

I think it looks nicest if you include it in both for alphabetical citation styles, but only include it in the first one for numerically ordered citation styles. By default it will list the entity in both bibliographies, but you can turn it off by adding this to the metadata:

```
---
multiref_no_duplicates: true
---
```

### Citeproc order handling

The filter automatically handles citation processing internally and works correctly regardless of whether `--citeproc` is specified before the filter, after the filter, or not at all. By default, after processing citations, the filter clears the bibliography metadata to prevent external `--citeproc` from re-processing citations.

If for some reason you need to preserve the bibliography metadata for further processing, you can disable this behavior:

```
---
multiref_keep_bibliography: true
---
```

Note: Setting this to `true` may cause issues if `--citeproc` is specified after `--lua-filter multi-refs.lua` in the command line.

## Test it

Numeric references:

```
pandoc --citeproc --lua-filter multi-refs.lua \
	sample.md -o sample.pdf --bibliography bibliography.bib --csl /home/nsheff/code/sciquill/csl/biomed-central.csl
```

Alphabetical references: 

```
pandoc --citeproc --lua-filter multi-refs.lua \
	sample.md -o sample.pdf --bibliography bibliography.bib
```


## Limitations

By the way, it ALSO works to divide sections, so you can put more than 1 bibliography into a top-level section.

## Technical Details: Order-Independence

### The Problem

Historically, this filter required `--citeproc` to be placed before `--lua-filter` in the pandoc command. When `--citeproc` came after the filter, it would re-process citations and corrupt the output, producing files 2.65x larger with all references duplicated in every section.

### The Solution

The filter now "consumes" citations by clearing bibliography metadata after processing. This prevents external `--citeproc` from having anything to re-process, making it a harmless no-op.

**All three command patterns now produce identical, correct output:**

```bash
# Pattern 1: --citeproc before filter (traditional)
pandoc --bibliography bib.bib --citeproc --lua-filter multi-refs.lua sample.md -o out.pdf

# Pattern 2: --citeproc after filter (now works!)
pandoc --bibliography bib.bib --lua-filter multi-refs.lua --citeproc sample.md -o out.pdf

# Pattern 3: No --citeproc (filter handles internally)
pandoc --bibliography bib.bib --lua-filter multi-refs.lua sample.md -o out.pdf
```

### How It Works

1. Filter runs and calls citeproc internally to process citations
2. Filter splits references by section and populates multi-refs divs
3. Filter clears `doc.meta.bibliography` and `doc.meta.references` (unless `multiref_keep_bibliography: true`)
4. If external `--citeproc` runs after, it has no metadata to process
5. External `--citeproc` becomes a no-op → no corruption

### Testing

Comprehensive tests verify the filter works correctly in all configurations:

```bash
# Run the test suite
cd /path/to/markmeld
pytest tests/test_multi_refs_filter.py -v
```

The tests verify:
- ✓ All three command patterns produce identical output
- ✓ References are split correctly by section
- ✓ The `multiref_no_duplicates` option works correctly
- ✓ Output size is correct (~2,300 chars for test case, not 6,000+ chars)

Test results demonstrate that all three patterns now produce identical output with section-specific references, proving the filter is order-independent and error-proof.