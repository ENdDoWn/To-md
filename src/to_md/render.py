"""Renders Markdown to sanitized HTML, entirely server-side.

A Source can smuggle raw HTML through the extraction, and Markdown renderers
pass raw HTML through untouched, so the rendered HTML is sanitized before it
ever reaches the browser.
"""

from __future__ import annotations

import markdown
import nh3


def render_to_html(markdown_text: str) -> str:
    html = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    return nh3.clean(html)
