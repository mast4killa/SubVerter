#!/usr/bin/env python3
from __future__ import annotations

"""
SRT subtitle utilities for SubVerter.

Provides:
- Data structure for SRT entries.
- Parsing SRT files into structured entries.
- Language detection from SRT text.
- Utility functions for building translation blocks and extracting context.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# SRT_TIME_RE — matches "HH:MM:SS,mmm --> HH:MM:SS,mmm" timestamp lines
SRT_TIME_RE = re.compile(
    r"^\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*$"
)


@dataclass
class SRTEntry:
    """
    Represents a single subtitle entry in an SRT file.
    """
    idx: int
    start: str
    end: str
    text: str  # single string with internal newlines preserved


def detect_language_from_srt(path: Path, verbosity: int = 0) -> str | None:
    """
    Detect the language of an SRT file's subtitle text.

    Args:
        path: Path to the SRT file.
        verbosity: Verbosity level for optional debug output.

    Returns:
        Detected language code (ISO 639-1/2) or None if detection fails.
    """
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
    except ImportError:
        print("❌ Missing dependency: langdetect. Please install it first.")
        return None

    try:
        text_lines: list[str] = []
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "-->" in line or line.strip().isdigit():
                    continue
                line = re.sub(r"<[^>]+>", "", line)  # strip HTML-like tags
                line = re.sub(r"\{[^}]+\}", "", line)  # strip {tags}
                line = line.strip()
                if line:
                    text_lines.append(line)
                if len(text_lines) >= 80:
                    break
        sample = " ".join(text_lines)
        if not sample.strip():
            print(f"⚠️ No text found in {path.name} for language detection.")
            return None
        lang = detect(sample)
        if verbosity >= 1:
            print(f"   🛈 Language detection sample length: {len(sample)} chars")
            if verbosity >= 2:
                print(f"      ↳ Sample text: {sample[:200]}{'...' if len(sample) > 200 else ''}")
            print(f"   🛈 Detected language: {lang}")
        return lang
    except FileNotFoundError:
        print(f"❌ SRT file not found: {path}")
        return None
    except UnicodeDecodeError as e:
        print(f"❌ Cannot decode {path.name} as UTF-8: {e}")
        return None
    except Exception as e:
        # Catch langdetect-specific or other unexpected errors
        print(f"❌ Language detection failed for {path.name}: {e}")
        return None


def parse_srt(path: Path, verbosity: int = 0) -> List[SRTEntry]:
    """
    Parse an SRT file into a list of SRTEntry objects.

    Args:
        path: Path to the SRT file.
        verbosity: Verbosity level for optional debug output.

    Returns:
        List of SRTEntry objects.
    """
    entries: List[SRTEntry] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"❌ SRT file not found: {path}")
        return []
    except UnicodeDecodeError as e:
        print(f"❌ Cannot decode {path.name} as UTF-8: {e}")
        return []
    except OSError as e:
        print(f"❌ Failed to read SRT file {path}: {e}")
        return []

    # Normalize line endings
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b for b in raw.split("\n\n") if b.strip()]

    if verbosity >= 1:
        print(f"   🛈 Found {len(blocks)} subtitle blocks in {path.name}")

    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip() != "" or l == ""]
        if not lines:
            continue

        # First line can be index; if not numeric, try to continue
        i = 0
        idx = None
        if lines[i].strip().isdigit():
            idx = int(lines[i].strip())
            i += 1

        if i >= len(lines):
            continue
        if not SRT_TIME_RE.match(lines[i]):
            # malformed block
            if verbosity >= 2:
                print(f"      ⚠️ Skipping malformed block: {lines}")
            continue
        start, end = SRT_TIME_RE.match(lines[i]).groups()
        i += 1

        text_lines = lines[i:]
        text = "\n".join(text_lines).strip("\n")
        entries.append(
            SRTEntry(
                idx=idx if idx is not None else len(entries) + 1,
                start=start,
                end=end,
                text=text
            )
        )

    if verbosity >= 1:
        print(f"   🛈 Parsed {len(entries)} valid subtitle entries from {path.name}")
        if verbosity >= 3:
            for e in entries[:5]:
                print(f"      ↳ [{e.idx}] {e.start} --> {e.end} | {repr(e.text)}")
            if len(entries) > 5:
                print("      ...")

    return entries


def join_entries_text(entries: List[SRTEntry]) -> str:
    """
    Join SRT entries' text with blank lines preserved between entries.

    Args:
        entries: List of SRTEntry objects.

    Returns:
        Combined subtitle text.
    """
    return "\n\n".join(e.text for e in entries)


def build_blocks(entries: List[SRTEntry], char_limit: int, verbosity: int = 0) -> List[Tuple[int, int]]:
    """
    Build blocks of entries staying under a character limit.

    Args:
        entries: List of SRTEntry objects.
        char_limit: Maximum number of characters per block.
        verbosity: Verbosity level for optional debug output.

    Returns:
        List of (start_index, end_index) tuples for each block.
    """
    blocks: List[Tuple[int, int]] = []
    start = 0
    curr_len = 0
    for i, e in enumerate(entries):
        entry_len = len(e.text) + 2  # include blank line separator
        if curr_len == 0:
            # start new block
            start = i
            curr_len = entry_len
        elif curr_len + entry_len <= char_limit:
            curr_len += entry_len
        else:
            blocks.append((start, i - 1))
            start = i
            curr_len = entry_len
    if curr_len > 0:
        blocks.append((start, len(entries) - 1))

    if verbosity >= 1:
        print(f"   🛈 Built {len(blocks)} blocks from {len(entries)} entries (char_limit={char_limit})")
        if verbosity >= 3:
            for bi, (s, e) in enumerate(blocks, start=1):
                print(f"      ↳ Block {bi}: entries {s+1}–{e+1}")

    return blocks


def context_slice(
    entries: List[SRTEntry],
    start: int,
    end: int,
    prev_n: int = 5,
    next_n: int = 5,
    verbosity: int = 0
) -> Tuple[str, str]:
    """
    Extract surrounding context from a list of SRT entries.

    Args:
        entries: List of SRTEntry objects.
        start: Start index of the current block.
        end: End index of the current block.
        prev_n: Number of previous entries to include.
        next_n: Number of next entries to include.
        verbosity: Verbosity level for optional debug output.

    Returns:
        Tuple of (previous_context, next_context) as strings.
    """
    prev_lines = [entries[i].text for i in range(max(0, start - prev_n), start)]
    next_lines = [entries[i].text for i in range(end + 1, min(len(entries), end + 1 + next_n))]

    if verbosity >= 2:
        print(f"      🛈 Context slice for entries {start+1}–{end+1}: "
              f"{len(prev_lines)} prev / {len(next_lines)} next")
        if verbosity >= 3:
            print("         ↳ Previous context:", repr("\n".join(prev_lines)))
            print("         ↳ Next context:", repr("\n".join(next_lines)))

    return ("\n".join(prev_lines).strip(), "\n".join(next_lines).strip())