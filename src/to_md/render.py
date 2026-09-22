"""Renders Markdown to sanitized HTML, entirely server-side.

A Source can smuggle raw HTML through the extraction, and Markdown renderers
pass raw HTML through untouched, so the rendered HTML is sanitized before it
ever reaches the browser.
"""

from __future__ import annotations

import re

import markdown
import nh3

_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_ROW = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")


def _isolate_tables(markdown_text: str) -> str:
    """Surround pipe-table blocks with blank lines and stop them at their last row.

    Sources like markitdown often emit table rows immediately adjacent to
    prose, with no blank line in between. Python-Markdown's tables extension
    then either merges the table into the surrounding paragraph (failing to
    render it as a table at all) or swallows the next unrelated line as a
    fake data row. Isolating each block on its own paragraph fixes both.
    """
    lines = markdown_text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if _PIPE_ROW.match(line) and i + 1 < n and _SEPARATOR_ROW.match(lines[i + 1]):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            while i < n and _PIPE_ROW.match(lines[i]):
                out.append(lines[i])
                i += 1
            if i < n and lines[i].strip() != "":
                out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def render_to_html(markdown_text: str) -> str:
    isolated = _isolate_tables(markdown_text)
    html = markdown.markdown(isolated, extensions=["tables", "fenced_code"])
    return nh3.clean(html)
