#!/usr/bin/env python3
from __future__ import annotations

"""
Subtitle reformatting utilities for SubVerter.

Provides:
- Soft word-wrapping for subtitle text.
- Reformatting subtitles to meet width and line count constraints.
"""

from typing import List


def soft_wrap(text: str, width: int) -> List[str]:
    """
    Wrap text into lines without breaking words, respecting a maximum width.

    Args:
        text: The input text to wrap.
        width: Maximum number of characters per line.

    Returns:
        A list of wrapped lines.
    """
    words = text.split()
    lines: List[str] = []
    curr = ""
    for w in words:
        if not curr:
            curr = w
        elif len(curr) + 1 + len(w) <= width:
            curr += " " + w
        else:
            lines.append(curr)
            curr = w
    if curr:
        lines.append(curr)
    return lines


def reformat_subtitle_text(text: str, max_width: int = 42, max_lines: int = 2) -> str:
    """
    Reformat subtitle text to meet width and line count constraints.

    - Preserves existing line breaks as hints.
    - Wraps each segment to the specified max_width.
    - If the result exceeds max_lines, merges lines intelligently.

    Args:
        text: The subtitle text to reformat.
        max_width: Maximum number of characters per line.
        max_lines: Maximum number of lines allowed.

    Returns:
        The reformatted subtitle text.
    """
    text = text.replace("\r\n", "\n").strip()
    lines: List[str] = []

    # Preserve existing line breaks as hints; wrap each segment
    for seg in text.split("\n"):
        wrapped = soft_wrap(seg, max_width)
        lines.extend(wrapped)

    if len(lines) <= max_lines:
        return "\n".join(lines)

    # Squeeze to max_lines by merging last parts intelligently
    merged: List[str] = []
    for l in lines:
        if not merged:
            merged.append(l)
        else:
            if len(merged[-1]) + 1 + len(l) <= max_width:
                merged[-1] = merged[-1] + " " + l
            else:
                merged.append(l)
    return "\n".join(merged[:max_lines])