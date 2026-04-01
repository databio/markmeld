"""Markdown cleaning for Google Docs exports."""

import logging
import re

_LOGGER = logging.getLogger(__name__)


def clean_markdown(
    markdown_content: str,
    clean_escapes: bool = True,
    remove_images: bool = True,
    strip_heading_bold: bool = True,
    replace_svg_with_pdf: bool = False,
    fix_latex_chars: bool = True,
) -> str:
    """Apply cleaning operations to markdown content.

    Primarily used to clean Google Docs exports for LaTeX processing.

    Args:
        markdown_content: Raw markdown content to clean.
        clean_escapes: Remove escape characters from markdown elements.
        remove_images: Remove embedded images and data URIs.
        strip_heading_bold: Remove bold formatting from headings.
        replace_svg_with_pdf: Replace .svg extensions with .pdf in images.
        fix_latex_chars: Replace Unicode characters incompatible with LaTeX.

    Returns:
        Cleaned markdown content.
    """
    if clean_escapes:
        markdown_content = clean_escape_characters(markdown_content)

    if remove_images:
        markdown_content = remove_embedded_images(markdown_content)

    if strip_heading_bold:
        markdown_content = strip_bold_from_headings(markdown_content)

    if replace_svg_with_pdf:
        markdown_content = replace_svg_extensions(markdown_content)

    if fix_latex_chars:
        markdown_content = check_and_fix_latex_incompatible_chars(markdown_content)

    markdown_content = ensure_blank_lines_before_headings(markdown_content)

    return markdown_content


def clean_escape_characters(markdown_content: str) -> str:
    """Remove escape characters from markdown elements.

    Used to clean Google Docs exports which over-escape markdown syntax.
    Preserves LaTeX escape sequences.

    Args:
        markdown_content: Markdown content with escaped characters.

    Returns:
        Content with markdown escapes removed but LaTeX escapes preserved.
    """
    content = markdown_content

    # Remove escapes from various markdown characters (but NOT LaTeX ones)
    content = content.replace('\\[', '[')
    content = content.replace('\\]', ']')
    content = content.replace('\\_', '_')
    content = content.replace('\\!', '!')
    content = content.replace('\\(', '(')
    content = content.replace('\\)', ')')
    content = content.replace('\\`', '`')
    content = content.replace('\\-', '-')
    content = content.replace('\\*', '*')
    content = content.replace('\\=', '=')
    content = content.replace('\\+', '+')
    content = content.replace('\\<', '<')
    content = content.replace('\\>', '>')

    # Handle LaTeX-specific fixes: convert double backslashes before LaTeX commands to single
    # This fixes Google Docs converting \{ to \\{ while preserving the LaTeX command
    content = re.sub(r'\\\\([{}\\])', r'\\\1', content)

    # Handle other LaTeX commands: convert \\alpha to \alpha, etc.
    content = re.sub(r'\\\\([a-zA-Z]+)', r'\\\1', content)

    # Finally, clean up any remaining double backslashes that aren't LaTeX commands
    content = re.sub(r'\\\\(?![{}\\a-zA-Z])', r'\\', content)

    return content


def remove_embedded_images(markdown_content: str) -> str:
    """Remove embedded images and image references from markdown.

    Removes reference-style image definitions, inline data URI images,
    and markdown image references. Used to clean Google Docs exports.

    Args:
        markdown_content: Markdown content potentially containing images.

    Returns:
        Content with embedded images removed and blank lines cleaned up.
    """
    # Remove reference-style image definitions with data URIs (both with and without angle brackets)
    content = re.sub(r'^\[[^\]]+\]:\s*<?data:[^>\n]*>?\s*$', '', markdown_content, flags=re.MULTILINE)

    # Remove markdown image references (both ![][imageX] and ![alt][imageX])
    content = re.sub(r'!\[[^\]]*\]\[[^\]]+\]', '', content)

    # Remove inline data URI images
    content = re.sub(r'!\[[^\]]*\]\(data:[^)]+\)', '', content)

    # Clean up extra blank lines
    content = re.sub(r'\n\n+', '\n\n', content)

    return content.strip()


def strip_bold_from_headings(markdown_content: str) -> str:
    """Remove bold formatting from markdown headings.

    Used to clean Google Docs exports which often wrap heading text in bold.

    Args:
        markdown_content: Markdown content with potentially bold headings.

    Returns:
        Content with bold markers removed from heading lines.
    """
    # Pattern matches heading lines with bold markers
    content = re.sub(r'^(#+)\s+\*\*(.*?)\*\*\s*$', r'\1 \2', markdown_content, flags=re.MULTILINE)

    # Also handle cases where there might be bold within the heading
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('#'):
            line = line.replace('**', '')
        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def ensure_blank_lines_before_headings(markdown_content: str) -> str:
    """Ensure blank lines before markdown headings.

    Markdown requires a blank line before headings for proper parsing.
    Google Docs exports often omit these blank lines.

    Args:
        markdown_content: Markdown content with potentially missing blank lines.

    Returns:
        Content with blank lines inserted before heading lines.
    """
    lines = markdown_content.split('\n')
    result = []
    for i, line in enumerate(lines):
        if line.startswith('#') and i > 0 and result and result[-1].strip() != '':
            result.append('')
        result.append(line)
    return '\n'.join(result)


def replace_svg_extensions(markdown_content: str) -> str:
    """Replace .svg extensions with .pdf in markdown image syntax.

    Used when SVG images need to be converted to PDF for LaTeX processing.

    Args:
        markdown_content: Markdown content with image references.

    Returns:
        Content with .svg image extensions replaced by .pdf.
    """
    # Pattern to match markdown images with .svg extension
    pattern = r'!\[([^\]]*)\]\(([^)]+?)(\.svg)\)'

    # Replace .svg with .pdf
    content = re.sub(pattern, r'![\1](\2.pdf)', markdown_content)

    return content


def check_and_fix_latex_incompatible_chars(markdown_content: str) -> str:
    """Check for and fix Unicode characters incompatible with LaTeX.

    Detects characters that cause "inputenc Error: Unicode character not set up
    for use with LaTeX" errors and replaces them with LaTeX-compatible
    alternatives. Also warns about other non-ASCII characters.

    Args:
        markdown_content: Markdown content to check and fix.

    Returns:
        Content with problematic Unicode characters replaced.
    """
    # Dictionary of problematic Unicode characters and their LaTeX-safe replacements
    # Add more as we discover them
    char_replacements = {
        '\u223C': '~',           # U+223C TILDE OPERATOR -> regular tilde
        '\u2212': '-',           # U+2212 MINUS SIGN -> hyphen-minus
        '\u2019': "'",           # U+2019 RIGHT SINGLE QUOTATION MARK -> apostrophe
        '\u2018': "'",           # U+2018 LEFT SINGLE QUOTATION MARK -> apostrophe
        '\u201C': '"',           # U+201C LEFT DOUBLE QUOTATION MARK -> quotation mark
        '\u201D': '"',           # U+201D RIGHT DOUBLE QUOTATION MARK -> quotation mark
        '\u2026': '...',         # U+2026 HORIZONTAL ELLIPSIS -> three dots
        '\u2013': '--',          # U+2013 EN DASH -> double hyphen
        '\u2014': '---',         # U+2014 EM DASH -> triple hyphen
        '\u000B': '\n',          # U+000B VERTICAL TAB -> newline
        '\u00A0': ' ',           # U+00A0 NO-BREAK SPACE -> regular space
        '\u200B': '',            # U+200B ZERO WIDTH SPACE -> remove
        '\u2010': '-',           # U+2010 HYPHEN -> hyphen-minus
        '\u00D7': 'x',           # U+00D7 MULTIPLICATION SIGN -> letter x
        '\u00F7': '/',           # U+00F7 DIVISION SIGN -> forward slash
        '\u2248': '~',           # U+2248 ALMOST EQUAL TO -> tilde
        '\u2260': '!=',          # U+2260 NOT EQUAL TO -> !=
        '\u2264': '<=',          # U+2264 LESS-THAN OR EQUAL TO -> <=
        '\u2265': '>=',          # U+2265 GREATER-THAN OR EQUAL TO -> >=
        '\u00B1': '+/-',         # U+00B1 PLUS-MINUS SIGN -> +/-
        '\u00B0': '$^\\circ$',   # U+00B0 DEGREE SIGN -> LaTeX degree symbol
        '\u00B5': '$\\mu$',      # U+00B5 MICRO SIGN -> LaTeX mu
        '\u221E': '$\\infty$',   # U+221E INFINITY -> LaTeX infinity
        '\u221A': '$\\sqrt{}$',  # U+221A SQUARE ROOT -> LaTeX square root
        '\u2211': '$\\sum$',     # U+2211 N-ARY SUMMATION -> LaTeX sum
        '\u220F': '$\\prod$',    # U+220F N-ARY PRODUCT -> LaTeX product
        '\u222B': '$\\int$',     # U+222B INTEGRAL -> LaTeX integral
        '\u03B1': '$\\alpha$',   # U+03B1 GREEK SMALL LETTER ALPHA
        '\u03B2': '$\\beta$',    # U+03B2 GREEK SMALL LETTER BETA
        '\u03B3': '$\\gamma$',   # U+03B3 GREEK SMALL LETTER GAMMA
        '\u03B4': '$\\delta$',   # U+03B4 GREEK SMALL LETTER DELTA
        '\u03B5': '$\\epsilon$', # U+03B5 GREEK SMALL LETTER EPSILON
        '\u03B8': '$\\theta$',   # U+03B8 GREEK SMALL LETTER THETA
        '\u03BB': '$\\lambda$',  # U+03BB GREEK SMALL LETTER LAMBDA
        '\u03C0': '$\\pi$',      # U+03C0 GREEK SMALL LETTER PI
        '\u03C3': '$\\sigma$',   # U+03C3 GREEK SMALL LETTER SIGMA
        '\u03C6': '$\\phi$',     # U+03C6 GREEK SMALL LETTER PHI
        '\u03BC': '$\\mu$',      # U+03BC GREEK SMALL LETTER MU
        '\u2080': '$_0$',        # U+2080 SUBSCRIPT ZERO
        '\u2081': '$_1$',        # U+2081 SUBSCRIPT ONE
        '\u2082': '$_2$',        # U+2082 SUBSCRIPT TWO
        '\u2083': '$_3$',        # U+2083 SUBSCRIPT THREE
        '\u2084': '$_4$',        # U+2084 SUBSCRIPT FOUR
        '\u2085': '$_5$',        # U+2085 SUBSCRIPT FIVE
        '\u2086': '$_6$',        # U+2086 SUBSCRIPT SIX
        '\u2087': '$_7$',        # U+2087 SUBSCRIPT SEVEN
        '\u2088': '$_8$',        # U+2088 SUBSCRIPT EIGHT
        '\u2089': '$_9$',        # U+2089 SUBSCRIPT NINE
        '\u2192': '$\\rightarrow$',  # U+2192 RIGHTWARDS ARROW
        '\u2713': '$\\checkmark$',   # U+2713 CHECK MARK
        '\u2717': '$\\times$',       # U+2717 BALLOT X
        '\u00B2': '$^2$',        # U+00B2 SUPERSCRIPT TWO
        '\u00B3': '$^3$',        # U+00B3 SUPERSCRIPT THREE
    }

    # Track what we find and fix
    issues_found = []
    content = markdown_content

    for char, replacement in char_replacements.items():
        if char in content:
            # Find context around each occurrence
            pattern = re.compile(re.escape(char))
            matches = list(pattern.finditer(content))

            if matches:
                # Log each occurrence with context
                for match in matches:
                    start = max(0, match.start() - 20)
                    end = min(len(content), match.end() + 20)
                    context = content[start:end]
                    # Clean up context for display (remove newlines)
                    context = context.replace('\n', ' ')

                    char_code = f"U+{ord(char):04X}"
                    issues_found.append({
                        'char': char,
                        'char_code': char_code,
                        'replacement': replacement,
                        'context': f"...{context}...",
                        'position': match.start()
                    })

                # Replace all occurrences
                content = content.replace(char, replacement)

    # Log warnings if any problematic characters were found
    if issues_found:
        _LOGGER.warning("⚠️  LaTeX-incompatible characters detected and auto-replaced:")

        # Group by character for cleaner output
        char_groups = {}
        for issue in issues_found:
            char_key = (issue['char'], issue['char_code'], issue['replacement'])
            if char_key not in char_groups:
                char_groups[char_key] = []
            char_groups[char_key].append(issue['context'])

        for (char, char_code, replacement), contexts in char_groups.items():
            # Format as table: 'char' (code) -> 'replacement'   N occ: context
            count = len(contexts)
            plural = "s" if count > 1 else ""
            # Take first context, truncate if too long
            context = contexts[0]
            if len(context) > 60:
                context = context[:57] + "..."
            _LOGGER.warning(f"  '{char}' ({char_code}) -> '{replacement}'   {count} occurrence{plural}: {context}")

        _LOGGER.warning("Note: Review document to ensure replacements are appropriate.")

    # Also check for any other non-ASCII characters that might cause issues
    # but aren't in our replacement list
    remaining_non_ascii = []
    for i, char in enumerate(content):
        if ord(char) > 127 and char not in char_replacements:
            # Skip common accented characters that LaTeX handles well
            if ord(char) < 256:  # Latin-1 supplement, usually OK
                continue

            context_start = max(0, i - 20)
            context_end = min(len(content), i + 20)
            context = content[context_start:context_end].replace('\n', ' ')

            remaining_non_ascii.append({
                'char': char,
                'char_code': f"U+{ord(char):04X}",
                'context': f"...{context}...",
                'position': i
            })

    # Deduplicate remaining non-ASCII warnings
    if remaining_non_ascii:
        seen_chars = {}
        for item in remaining_non_ascii:
            char_key = (item['char'], item['char_code'])
            if char_key not in seen_chars:
                seen_chars[char_key] = []
            seen_chars[char_key].append(item['context'])

        if seen_chars:
            _LOGGER.warning("")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("⚠️  ADDITIONAL NON-ASCII CHARACTERS DETECTED")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("")
            _LOGGER.warning("The following non-ASCII characters were found that *might* cause")
            _LOGGER.warning("LaTeX issues (not automatically replaced):")
            _LOGGER.warning("")

            for (char, char_code), contexts in list(seen_chars.items())[:10]:  # Limit to 10
                _LOGGER.warning(f"  Character: '{char}' ({char_code})")
                _LOGGER.warning(f"  Example context: {contexts[0]}")
                if len(contexts) > 1:
                    _LOGGER.warning(f"  Found {len(contexts)} occurrence(s)")
                _LOGGER.warning("")

            if len(seen_chars) > 10:
                _LOGGER.warning(f"  ... and {len(seen_chars) - 10} more unique characters")
                _LOGGER.warning("")

            _LOGGER.warning("Consider reviewing these characters if you encounter LaTeX errors.")
            _LOGGER.warning("=" * 70)
            _LOGGER.warning("")

    return content
