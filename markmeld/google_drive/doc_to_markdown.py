"""Convert Google Docs API JSON to markdown with change markers.

Walks the structured JSON from documents.get(suggestionsViewMode='SUGGESTIONS_INLINE')
and produces markdown where:
- Text runs with suggestedDeletionIds are skipped (old text being replaced)
- Text runs with suggestedInsertionIds are wrapped in [text]{.changed}
- Normal text runs are output as-is
"""

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Heading level mapping
_HEADING_MAP = {
    "HEADING_1": "# ",
    "HEADING_2": "## ",
    "HEADING_3": "### ",
    "HEADING_4": "#### ",
    "HEADING_5": "##### ",
    "HEADING_6": "###### ",
}


def doc_to_markdown(doc: dict[str, Any]) -> str:
    """Convert a Google Docs API document to markdown with change markers.

    Args:
        doc: The full document dict from documents().get() with
             suggestionsViewMode='SUGGESTIONS_INLINE'.

    Returns:
        Markdown string with suggestions marked as [text]{.changed}.
    """
    body = doc.get("body", {})
    content = body.get("content", [])

    parts: list[str] = []
    in_frontmatter = False
    for element in content:
        if "paragraph" in element:
            text = _convert_paragraph(element["paragraph"])
            if not text.strip():
                continue

            stripped = text.rstrip("\n")

            # Track YAML frontmatter blocks (--- delimited) to avoid
            # inserting blank lines between frontmatter fields
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                parts.append(stripped)
                continue

            if in_frontmatter:
                # Frontmatter lines: no blank line separation
                parts.append(stripped)
            else:
                # Body paragraphs: need blank line separation for markdown
                if parts and not parts[-1] == "":
                    parts.append("")
                parts.append(stripped)
        elif "table" in element:
            if parts and not parts[-1] == "":
                parts.append("")
            parts.append(_convert_table(element["table"]).rstrip("\n"))
        elif "sectionBreak" in element:
            continue
        elif "tableOfContents" in element:
            continue

    return "\n".join(parts)


def _convert_paragraph(paragraph: dict[str, Any]) -> str:
    """Convert a paragraph element to markdown.

    Args:
        paragraph: A paragraph dict from the Docs API.

    Returns:
        A markdown string for this paragraph.
    """
    style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
    elements = paragraph.get("elements", [])

    # Check if this paragraph is entirely a suggested insertion
    all_insertion = elements and all(
        bool(
            elem.get("suggestedInsertionIds")
            or (elem.get("textRun", {}).get("suggestedInsertionIds"))
        )
        or (elem.get("textRun", {}).get("content", "").strip() == "")
        for elem in elements
    )

    # Build the text content from all runs
    text = ""
    for elem in elements:
        text += _convert_element(elem)

    # Apply heading prefix — but not if the entire paragraph is a suggested
    # insertion, which means it's replacement text that shouldn't be a heading
    prefix = _HEADING_MAP.get(style, "")
    if prefix and not all_insertion:
        text = text.rstrip("\n")
        return f"{prefix}{text}\n"

    return text


def _convert_element(element: dict[str, Any]) -> str:
    """Convert a single paragraph element (text run, inline object, etc.).

    Args:
        element: An element dict from paragraph['elements'].

    Returns:
        Markdown text for this element.
    """
    if "textRun" in element:
        return _convert_text_run(element)
    elif "inlineObjectElement" in element:
        # Skip inline objects (images) — manuscripts handle figures separately
        return ""
    elif "footnoteReference" in element:
        # Skip footnote references for now
        return ""
    return ""


def _convert_text_run(element: dict[str, Any]) -> str:
    """Convert a text run element, handling suggestions and formatting.

    Args:
        element: An element dict containing a 'textRun' key.

    Returns:
        Markdown text, possibly wrapped in []{.changed} for suggestions.
    """
    text_run = element["textRun"]
    content = text_run.get("content", "")

    # Check for suggestion markers at the element level or textRun level
    is_deletion = bool(element.get("suggestedDeletionIds") or text_run.get("suggestedDeletionIds"))
    is_insertion = bool(
        element.get("suggestedInsertionIds") or text_run.get("suggestedInsertionIds")
    )

    # Deletions: skip entirely (this is the old text being replaced)
    if is_deletion and not is_insertion:
        return ""

    # Apply text formatting
    text_style = text_run.get("textStyle", {})
    formatted = _apply_formatting(content, text_style)

    # Insertions: wrap in change marker
    if is_insertion:
        # Don't wrap pure whitespace/newlines in change markers
        stripped = formatted.strip()
        if stripped:
            # Preserve leading/trailing whitespace outside the marker
            leading = formatted[: len(formatted) - len(formatted.lstrip())]
            trailing = formatted[len(formatted.rstrip()) :]
            formatted = f"{leading}[{stripped}]{{.changed}}{trailing}"

    return formatted


def _apply_formatting(text: str, text_style: dict[str, Any]) -> str:
    """Apply bold/italic markdown formatting to text.

    Args:
        text: The raw text content.
        text_style: The textStyle dict from the Docs API.

    Returns:
        Text with markdown bold/italic applied.
    """
    # Don't format whitespace-only or newline-only content
    if not text.strip():
        return text

    is_bold = text_style.get("bold", False)
    is_italic = text_style.get("italic", False)

    if not is_bold and not is_italic:
        return text

    # Preserve leading/trailing whitespace outside formatting markers
    stripped = text.strip()
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]

    if is_bold and is_italic:
        return f"{leading}***{stripped}***{trailing}"
    elif is_bold:
        return f"{leading}**{stripped}**{trailing}"
    elif is_italic:
        return f"{leading}*{stripped}*{trailing}"

    return text


def _convert_table(table: dict[str, Any]) -> str:
    """Convert a table element to markdown.

    Args:
        table: A table dict from the Docs API.

    Returns:
        Markdown table string.
    """
    rows = table.get("tableRows", [])
    if not rows:
        return ""

    md_rows: list[str] = []
    for i, row in enumerate(rows):
        cells = row.get("tableCells", [])
        cell_texts: list[str] = []
        for cell in cells:
            # Each cell has content (paragraphs)
            cell_content = cell.get("content", [])
            cell_text = ""
            for content_elem in cell_content:
                if "paragraph" in content_elem:
                    cell_text += _convert_paragraph(content_elem["paragraph"]).strip()
            cell_texts.append(cell_text)

        md_rows.append("| " + " | ".join(cell_texts) + " |")

        # Add header separator after first row
        if i == 0:
            md_rows.append("| " + " | ".join(["---"] * len(cell_texts)) + " |")

    return "\n".join(md_rows) + "\n"
