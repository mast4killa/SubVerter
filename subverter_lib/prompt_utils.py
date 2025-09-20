#!/usr/bin/env python3
from __future__ import annotations

"""
Prompt building utilities for SubVerter.

Provides:
- Functions to construct structured, context-aware prompts for LLM translation.
"""

from typing import List
from subverter_lib.srt_utils import SRTEntry


def build_translation_prompt(
    src_lang: str,
    tgt_lang: str,
    block_entries: List[SRTEntry],
    summary_so_far: str,
    prev_context: str,
    next_context: str,
    verbosity: int = 0
) -> str:
    """
    Build a context-rich translation prompt for a block of subtitle entries.

    Args:
        src_lang: Source language code (ISO 639-1/2).
        tgt_lang: Target language code (ISO 639-1/2).
        block_entries: List of SRTEntry objects representing the block to translate.
        summary_so_far: Optional rolling summary of previous blocks (≤500 chars).
                        Pass an empty string to omit.
        prev_context: Verbatim text of the previous 5 subtitles (may be empty).
        next_context: Verbatim text of the next 5 subtitles (may be empty).
        verbosity: Verbosity level for optional debug output.

    Returns:
        A formatted string prompt for the LLM.
    """
    expected_count = len(block_entries)

    # Label each entry so the model can’t merge/drop them.
    # We intentionally use ENTRY labels as the parsing anchor downstream.
    labelled_entries: List[str] = [
        f"ENTRY {i}: {e.text}" for i, e in enumerate(block_entries, start=1)
    ]

    # Blank lines between entries are optional for readability here; parsing relies on ENTRY labels.
    entries_text = "\n\n".join(labelled_entries)

    # Build optional context sections only if provided, to avoid noisy "(none)" blocks.
    summary_section = (
        f"- Summary so far (≤500 chars): {summary_so_far.strip()}"
        if summary_so_far.strip()
        else None
    )
    prev_section = (
        f"- Previous 5 subtitles (verbatim):\n{prev_context.strip()}"
        if prev_context.strip()
        else None
    )
    next_section = (
        f"- Next 5 subtitles (verbatim):\n{next_context.strip()}"
        if next_context.strip()
        else None
    )

    # Join whichever context blocks exist; keep this lean and factual.
    context_blocks = [b for b in (summary_section, prev_section, next_section) if b]
    context_text = "\n\n".join(context_blocks) if context_blocks else "(no additional context)"

    # Core instructions:
    # - Remove brittle "blank line" constraints; ENTRY labels are the single source of structure.
    # - Keep inline tags exactly; no timestamps; no commentary.
    # - One-to-one mapping with original entries; no merges/splits.
    instructions = f"""
You are a professional subtitle translator.

Task:
- Translate the content from {src_lang} to {tgt_lang}.
- There are EXACTLY {expected_count} subtitle entries in this block.
- You MUST return EXACTLY {expected_count} translated entries, in the same order.
- Each entry is prefixed with 'ENTRY X:' — keep these prefixes exactly as given.
- Do not merge or split entries; preserve one-to-one correspondence.
- Do not include numbers or timestamps other than the ENTRY labels.
- Preserve inline tags such as <i>...</i> and {{{{...}}}} exactly as they appear.
- Maintain tone, voice, and register; keep names and terminology consistent.

Context:
{context_text}

Output format:
- Only the translated subtitle texts, each prefixed with the same 'ENTRY X:' label.
- Entries may be separated by a newline or a single blank line.
- No extra commentary or formatting beyond the translated text.

Content to translate:
{entries_text}
""".strip()

    # Verbosity-controlled debug output
    if verbosity >= 3:
        print("\n      🛈 [Prompt Builder] Full prompt:\n" + instructions + "\n")
    elif verbosity == 2:
        lines = entries_text.splitlines()
        preview = "\n".join(lines[:3] + (["..."] if len(lines) > 6 else []) + lines[-3:])
        print("\n      🛈 [Prompt Builder] Content preview:\n" + preview + "\n")
    elif verbosity == 1:
        idxs = [str(e.idx) for e in block_entries]
        print(f"      🛈 [Prompt Builder] Entry indices in block: {', '.join(idxs)}")

    return instructions

def build_summary_prompt(
    src_lang: str,
    previous_summary: str,
    recent_text: str,
    max_chars: int
) -> str:
    """
    Build a prompt for updating a rolling summary of subtitle dialogue.

    Args:
        src_lang: Source language code (ISO 639-1/2).
        previous_summary: Existing summary text so far (may be empty).
        recent_text: New dialogue text to incorporate into the summary.
        max_chars: Maximum allowed characters for the updated summary.

    Returns:
        A formatted string prompt for the LLM.
    """
    return (
        f"You are assisting with translating subtitles from {src_lang} into another language. "
        f"The text is spoken dialogue from a video, without visual context. "
        f"We are maintaining a rolling summary in {src_lang} to help translate the next block. "
        f"Update the summary so it still fits within {max_chars} characters, "
        f"keeping the most important points from the existing summary and adding any new key details "
        f"from the latest dialogue. Focus on topics, relationships, tone or mood changes, "
        f"and relevant setting/time shifts. Ignore filler unless it changes meaning or tone.\n\n"
        f"Current summary:\n{previous_summary or '(none)'}\n\n"
        f"New dialogue:\n{recent_text.strip()}"
    )