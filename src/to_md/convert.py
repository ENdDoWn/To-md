"""Runs a Source through markitdown.

Only the streaming entry point (`convert_stream`) is used, never the
variant that accepts a URI or path — the Source never touches disk and the
tool never fetches remote resources.
"""

from __future__ import annotations

import io

from markitdown import MarkItDown, StreamInfo


def convert_to_markdown(source: bytes, extension: str) -> str:
    # A fresh instance per call sidesteps any question of whether MarkItDown
    # is safe to share across the worker pool's threads.
    stream = io.BytesIO(source)
    result = MarkItDown().convert_stream(
        stream,
        stream_info=StreamInfo(extension=extension),
    )
    return result.markdown
