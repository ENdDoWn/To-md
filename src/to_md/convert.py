"""Runs a Source through markitdown.

Only the streaming entry point (`convert_stream`) is used, never the
variant that accepts a URI or path — the Source never touches disk and the
tool never fetches remote resources.
"""

from __future__ import annotations

import io
import re

from markitdown import MarkItDown, StreamInfo

# C0 controls except \t and \n, plus DEL and the C1 range. Some PDFs — Thai
# ones with a broken ToUnicode CMap in particular — map glyphs to U+0000, and
# those bytes would otherwise leak into the Markdown.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def sanitize_markdown(markdown: str) -> str:
    return _CONTROL_CHARS.sub("", markdown)


def convert_to_markdown(source: bytes, extension: str) -> str:
    # A fresh instance per call sidesteps any question of whether MarkItDown
    # is safe to share across the worker pool's threads.
    stream = io.BytesIO(source)
    result = MarkItDown().convert_stream(
        stream,
        stream_info=StreamInfo(extension=extension),
    )
    return sanitize_markdown(result.markdown)
