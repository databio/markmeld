# Multi-refs Filter Test Data

This directory contains test files for the multi-refs pandoc filter, which enables multiple reference sections in a single document.

## Test Files

- `sample.md` - Sample markdown with multiple sections and citations, each with a `<div class="multi-refs"></div>` marker
- `bibliography.bib` - BibTeX bibliography with 7 test references
- `multi-refs.lua` - The actual filter being tested

## What These Tests Verify

The tests ensure that the multi-refs filter works correctly **regardless of --citeproc flag placement**:

1. **--citeproc BEFORE --lua-filter** (traditional order)
2. **--citeproc AFTER --lua-filter** (previously broken, now fixed)
3. **NO --citeproc** (filter handles it internally)

All three scenarios should produce **identical output** with section-specific references.

## The Fix

The filter was updated to clear bibliography metadata after processing citations, which prevents external `--citeproc` from re-processing and corrupting the output. This makes the filter order-independent and error-proof.

## Configuration Options

The sample.md includes:
- `multiref_no_duplicates: true` - Repeated citations only appear in the first section where they occur
- (Optional) `multiref_keep_bibliography: true` - Preserves bibliography metadata (not set in sample, would disable the fix)
