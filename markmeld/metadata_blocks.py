"""Find pandoc YAML metadata blocks anywhere in a markdown document.

python-frontmatter only reads a block at the very top of the file. Pandoc
reads one anywhere, as long as the opening ``---`` starts the document or
follows a blank line, and the line after it is not blank. When two blocks set
the same field, pandoc keeps the later one. Code that decides what pandoc
will cite from must follow pandoc's rules, not python-frontmatter's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass
class _Block:
    start: int  # line index of the opening ---
    end: int  # line index of the closing --- or ...
    data: dict[str, Any]


def _blocks(lines: list[str]) -> list[_Block]:
    blocks = []
    i = 0
    while i < len(lines):
        opens = (
            lines[i].rstrip() == "---"
            and (i == 0 or not lines[i - 1].strip())
            and i + 1 < len(lines)
            and lines[i + 1].strip()
        )
        if opens:
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip() in ("---", "..."):
                    try:
                        data = yaml.safe_load("\n".join(lines[i + 1 : j]))
                    except yaml.YAMLError:
                        data = None
                    if isinstance(data, dict):
                        blocks.append(_Block(i, j, data))
                        i = j
                    break
        i += 1
    return blocks


def find_bibliography(content: str) -> str | list[str] | None:
    """The `bibliography` pandoc would use from the document's own metadata."""
    found = None
    for block in _blocks(content.split("\n")):
        if "bibliography" in block.data:
            found = block.data["bibliography"]
    return found
