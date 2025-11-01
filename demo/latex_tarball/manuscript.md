# Example Manuscript

This is a simple example manuscript to demonstrate LaTeX tarball export.

## Introduction

This document shows how to create a portable LaTeX package that includes all figures and can be compiled anywhere.

## Methods

When you include figures in your markdown, they will be converted and included in the tarball.

<!-- Example figure reference (would work if fig/example.pdf existed):
![Example figure](fig/example.pdf)
-->

## Results

The generated tarball contains:

- The `.tex` file with embedded bibliography
- All figures from the `fig/` directory
- All spreadsheet figures from the `sheets/` directory (if present)

## Conclusion

This portable package can be:

- Extracted and compiled on any LaTeX system
- Submitted to journals that require LaTeX source
- Shared with collaborators for local compilation
- Archived for reproducibility
