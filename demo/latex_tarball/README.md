# LaTeX Tarball Export Example

This example demonstrates how to create a portable LaTeX package (tarball) containing the generated `.tex` file and all required figures for compilation on any system.

## Quick Start

```bash
# Build the PDF (generates .tex file)
mm manuscript-pdf

# Create the LaTeX package tarball
mm latex-package
```

The generated tarball `out/manuscript-latex.tar.gz` contains everything needed to compile the LaTeX document locally.

## Extracting and Compiling

```bash
# Extract the tarball
tar xzf out/manuscript-latex.tar.gz

# Compile the LaTeX
cd manuscript
pdflatex manuscript.tex
```

## How It Works

### 1. Relative Paths in Generated LaTeX

The generated `.tex` file contains relative figure paths like:
```latex
\includegraphics{fig/overview.pdf}
```

This makes the LaTeX portable - no absolute paths that only work on the build server.

### 2. Symlinks in Build Directory

During the build, the system automatically creates symlinks:
```
build_dir/
├── out/
│   └── manuscript.tex
├── fig/ -> ../../.cache/doc-id/converted/fig/
└── sheets/ -> ../../.cache/doc-id/converted/sheets/
```

These symlinks make the relative paths resolve correctly during PDF builds.

### 3. Tar Dereferences Symlinks

The `tar` command uses `--dereference` to follow symlinks and embed the actual figure files:

```bash
tar czf manuscript-latex.tar.gz \
  --dereference \
  --transform 's,^,manuscript/,' \
  manuscript.tex ../fig/ ../sheets/
```

### 4. Clean Tarball Structure

The `--transform` option creates a top-level directory in the tarball:

```
manuscript/
├── manuscript.tex
├── fig/
│   ├── figure1.pdf
│   └── figure2.pdf
└── sheets/
    └── sheet1.pdf
```

### 5. Graceful Fallbacks

The command uses cascading fallbacks to handle missing directories:

1. Try with `../fig/` and `../sheets/` (if both exist)
2. Fall back to just `../fig/` (if only figures exist)
3. Fall back to just `manuscript.tex` (if no figures)

This prevents errors when a project has no figures or spreadsheets.

## Target Configuration

There are two ways to configure a LaTeX tarball target:

### Option 1: Self-Contained Target (Recommended)

The target builds the PDF and creates the tarball in a single command:

```yaml
latex-package:
  output_file: "out/manuscript-latex.tar.gz"
  tex_output: true  # Generate .tex file
  jinja_template: "template.jinja"
  data:
    md_files:
      body: "manuscript.md"
    variables:
      title: "Example Manuscript"
  command: |
    pandoc {input_file} -o out/manuscript.pdf --pdf-engine=pdflatex && \
    cd out && \
    tar czf manuscript-latex.tar.gz \
      --dereference \
      --transform 's,^,manuscript/,' \
      manuscript.tex ../fig/ ../sheets/ 2>/dev/null || \
    tar czf manuscript-latex.tar.gz \
      --dereference \
      --transform 's,^,manuscript/,' \
      manuscript.tex ../fig/ 2>/dev/null || \
    tar czf manuscript-latex.tar.gz \
      --dereference \
      --transform 's,^,manuscript/,' \
      manuscript.tex
```

**Pros:**
- Single target does everything
- No need for separate PDF target
- Simpler project configuration

**Cons:**
- If you also want the PDF separately, it runs pandoc twice

### Option 2: Separate Targets with Prebuild

Use a separate PDF target and prebuild hook:

```yaml
targets:
  manuscript-pdf:
    tex_output: true  # CRITICAL: Must generate .tex file
    # ... normal PDF build configuration ...

  latex-package:
    output_file: "out/manuscript-latex.tar.gz"
    command: |
      cd out && \
      tar czf manuscript-latex.tar.gz \
        --dereference \
        --transform 's,^,manuscript/,' \
        manuscript.tex ../fig/ ../sheets/ 2>/dev/null || \
      tar czf manuscript-latex.tar.gz \
        --dereference \
        --transform 's,^,manuscript/,' \
        manuscript.tex ../fig/ 2>/dev/null || \
      tar czf manuscript-latex.tar.gz \
        --dereference \
        --transform 's,^,manuscript/,' \
        manuscript.tex
    prebuild:
      - manuscript-pdf  # Build PDF first to generate .tex
```

**Pros:**
- Reuses existing PDF target
- Can build PDF independently
- Both targets share the same .tex file

**Cons:**
- Requires two targets instead of one
- More configuration to maintain

## Customization Options

### Change Output Name

```yaml
command: |
  cd out && \
  tar czf myproject-latex.tar.gz \
    --dereference \
    --transform 's,^,myproject/,' \
    manuscript.tex ../fig/ ../sheets/
```

### Include Additional Files

```yaml
command: |
  cd out && \
  tar czf manuscript-latex.tar.gz \
    --dereference \
    --transform 's,^,manuscript/,' \
    manuscript.tex ../fig/ ../sheets/ *.sty *.cls 2>/dev/null
```

### Create ZIP Instead of Tarball

```yaml
output_file: "out/manuscript-latex.zip"
command: |
  cd out && \
  zip -r manuscript-latex.zip manuscript.tex && \
  cd .. && \
  zip -r out/manuscript-latex.zip fig/ sheets/ 2>/dev/null || true
```

### Add README to Tarball

```yaml
command: |
  cd out && \
  echo "Compile with: pdflatex manuscript.tex" > README.txt && \
  tar czf manuscript-latex.tar.gz \
    --dereference \
    --transform 's,^,manuscript/,' \
    manuscript.tex README.txt ../fig/ ../sheets/
```

## Why No .bib File?

The generated `.tex` file already has the bibliography embedded as `\bibitem` entries (pandoc processes the `.bib` during PDF generation). Users only need to run `pdflatex` once or twice - no `bibtex` step required.

## Use Cases

- **Journal submission**: Many journals require LaTeX source files
- **Collaboration**: Share with collaborators who prefer local LaTeX compilation
- **Archiving**: Create self-contained packages for long-term storage
- **Offline compilation**: Compile the document without network access
- **Custom formatting**: Let users tweak LaTeX directly before final compilation

## Troubleshooting

### Tarball is empty
- Ensure `tex_output: true` is set in the PDF build target
- Verify the PDF target actually generates a `.tex` file
- Check that the output filename matches the tar command

### Figures missing from tarball
- Verify figures are in the cache (check `.cache/*/converted/fig/`)
- Ensure symlinks were created correctly in build directory
- Check that `--dereference` flag is present in tar command

### Compilation fails after extraction
- Ensure all LaTeX dependencies are installed on target system
- Check that figure paths in `.tex` are relative (not absolute)
- Verify the tarball structure has `fig/` as a subdirectory

### Build fails with permission errors
- Check write permissions on build directory
- Ensure tar is installed and in PATH
- Verify `prebuild` target completed successfully

## Requirements

- **Build system**: Markmeld with relative path support (v2.0+)
- **System tools**: `tar` and `gzip` (standard on Linux/macOS)
- **Target system**: LaTeX distribution (TeX Live, MiKTeX, etc.)

## Further Reading

- See `_markmeld.yaml` for complete configuration
- Check main Sciquill documentation for markmeld usage
- Review LaTeX tarball export plan for implementation details
