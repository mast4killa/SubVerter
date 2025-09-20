#!/usr/bin/env python3
from __future__ import annotations

"""
Translation pipeline utilities for SubVerter.

Provides:
- Functions to split and validate translated subtitle blocks.
- Block-wise translation with context injection.
- Fallback to per-entry translation when block validation fails.
"""

import re
from typing import List, Optional

from subverter_lib.srt_utils import SRTEntry, build_blocks, context_slice
from subverter_lib.prompt_utils import build_translation_prompt, build_summary_prompt
from subverter_lib.llm_adapter import LLMAdapter
from subverter_lib.lang_utils import normalize_text

# Regex to detect ENTRY labels at the start of lines
ENTRY_LABEL_RE = re.compile(r"^ENTRY\s+\d+:\s*", re.IGNORECASE)


def split_on_entry_labels(text: str) -> list[str]:
    """
    Split translated text into parts based on ENTRY labels.
    """
    parts = re.split(r'(?=ENTRY \d+:)', text)
    return [p.strip() for p in parts if p.strip()]


def split_on_double_newline(text: str) -> List[str]:
    """
    Split text on double newlines into non-empty parts.

    Args:
        text: The input text.

    Returns:
        List of non-empty strings.
    """
    parts = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return [p for p in parts if p != ""]


def strip_entry_labels(text: str) -> str:
    """
    Remove 'ENTRY X:' labels from the start of each entry line.

    Args:
        text: The translated block text.

    Returns:
        Cleaned text without ENTRY labels.
    """
    lines = text.splitlines()
    cleaned_lines = [ENTRY_LABEL_RE.sub("", line).strip() for line in lines]
    return "\n".join(cleaned_lines).strip()


def validate_block_count(original: List[SRTEntry], translated_block_text: str) -> bool:
    """
    Validate that the number of translated entries matches the original block.

    Args:
        original: List of original SRTEntry objects for the block.
        translated_block_text: The translated block text.

    Returns:
        True if counts match, False otherwise.
    """
    orig_count = len(original)

    # Split on ENTRY labels instead of relying on blank lines
    parts = split_on_entry_labels(translated_block_text)
    return len(parts) == orig_count


def translate_block_fallback_per_entry(
    llm: LLMAdapter,
    src_lang: str,
    tgt_lang: str,
    entries: List[SRTEntry],
    summary_so_far: str,
    verbosity: int = 0
) -> Optional[str]:
    """
    Translate each entry individually as a fallback when block translation fails.

    Args:
        llm: LLMAdapter instance.
        src_lang: Source language code.
        tgt_lang: Target language code.
        entries: List of SRTEntry objects to translate.
        summary_so_far: Rolling summary of previous translations.
        verbosity: Verbosity level.

    Returns:
        The translated block text, or None if any entry fails.
    """
    out_parts: List[str] = []
    for idx, e in enumerate(entries, start=1):
        if verbosity >= 1:
            print(f"   🛈 Fallback: translating entry {idx}/{len(entries)} individually.")
        if verbosity >= 3:
            print(f"      ↳ Original text:\n{e.text}\n")

        prompt = build_translation_prompt(
            src_lang, tgt_lang, [e], summary_so_far,
            prev_context="", next_context="", verbosity=verbosity
        )

        try:
            resp = llm.generate(prompt)
        except Exception as e:
            print(f"❌ LLM generate call failed for entry {idx}/{len(entries)}: {e}")
            return None

        if not resp:
            print(f"❌ No output from LLM for entry {idx}/{len(entries)}")
            return None
        # Ensure single entry returned without extra splits
        lines = split_on_double_newline(resp)
        translated_line = lines[0] if lines else resp.strip()
        translated_line = strip_entry_labels(translated_line)
        if verbosity >= 3:
            print(f"      ↳ LLM output (cleaned):\n{translated_line}\n")
        out_parts.append(translated_line)
    return "\n\n".join(out_parts)


def translate_entries_with_context(
    entries: List[SRTEntry],
    src_lang: str,
    tgt_lang: str,
    llm: LLMAdapter,
    char_limit: int,
    verbosity: int = 0,
    keep_browser_alive: bool = False,
    summary_max_chars: int = 500
) -> Optional[List[str]]:
    """
    Translate a list of SRT entries in context-aware blocks.

    Args:
        entries: Parsed SRT entries.
        src_lang: Source language code.
        tgt_lang: Target language code.
        llm: LLMAdapter instance (used if keep_browser_alive=True).
        char_limit: Max characters per translation block.
        verbosity: Verbosity level.
        keep_browser_alive: If True, keep the same browser session alive for all blocks
                            (persistent mode), starting a new chat per block.
        summary_max_chars: Max characters to keep in rolling summary.
    """
    # Build translation blocks based on char_limit
    try:
        blocks = build_blocks(entries, char_limit)
    except Exception as e:
        print(f"❌ Failed to build translation blocks: {e}")
        return None

    translations: List[str] = []
    rolling_summary = ""

    if verbosity >= 1:
        print(f"   🛈 Built {len(blocks)} translation blocks (char_limit={char_limit}).")

    # If keeping browser alive, we use the provided llm for all blocks
    # If not, we'll create a fresh LLMAdapter per block
    for bi, (start, end) in enumerate(blocks, start=1):
        block_entries = entries[start: end + 1]
        try:
            prev_ctx, next_ctx = context_slice(entries, start, end, prev_n=5, next_n=5)
        except Exception as e:
            print(f"❌ Failed to extract context for block {bi}/{len(blocks)}: {e}")
            return None

        if verbosity >= 1:
            print(f"\n   🔹 Translating block {bi}/{len(blocks)} "
                  f"(entries {start+1}–{end+1}, {len(block_entries)} entries)")

        if verbosity >= 2:
            print("      ↳ First entry text:", repr(block_entries[0].text))
            print("      ↳ Last entry text:", repr(block_entries[-1].text))
        if verbosity >= 3:
            print("      ↳ Full block text to translate:")
            for e in block_entries:
                print(f"         [{e.idx}] {e.text}")
            print("\n      ↳ Previous context:\n", prev_ctx or "(none)")
            print("\n      ↳ Next context:\n", next_ctx or "(none)")

        # Always include rolling summary if available
        summary_for_prompt = rolling_summary
        if summary_for_prompt and verbosity >= 3:
            print(f"      🛈 Summary passed to prompt ({len(summary_for_prompt)} chars): {repr(summary_for_prompt)}")

        # Build the translation prompt for this block
        prompt = build_translation_prompt(
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            block_entries=block_entries,
            summary_so_far=summary_for_prompt,
            prev_context=prev_ctx,
            next_context=next_ctx,
            verbosity=verbosity
        )

        # Choose LLM instance
        if keep_browser_alive:
            llm_instance = llm
        else:
            # Fresh browser/session per block
            if not getattr(llm, "config", None):
                print(f"❌ LLMAdapter config is missing or invalid; cannot create new instance.")
                return None
            llm_instance = LLMAdapter(llm.config)

        # Generate translation for the block
        try:
            resp = llm_instance.generate(prompt, verbosity=verbosity)
        except Exception as e:
            print(f"❌ LLM generate call failed for block {bi}/{len(blocks)}: {e}")
            return None

        if not resp:
            print(f"❌ Model returned no output for block {bi}/{len(blocks)}")
            return None

        # Split LLM output into entries
        parts = split_on_entry_labels(resp)

        if verbosity >= 2:
            print(f"      ↳ LLM returned {len(parts)} entries.")
            if verbosity == 2:
                print("         First few lines of output:")
                for l in parts[:3]:
                    print("           ", l)
                if len(parts) > 3:
                    print("           ...")
            elif verbosity >= 3:
                print("      ↳ Full LLM output:\n", resp)

        # Validate entry count; fallback to per-entry translation if mismatch
        if not validate_block_count(block_entries, "\n\n".join(parts)):
            print(f"⚠️ Count mismatch in block {bi}/{len(blocks)}. Falling back to per-entry.")
            resp_fallback = translate_block_fallback_per_entry(
                llm_instance, src_lang, tgt_lang, block_entries,
                summary_for_prompt, verbosity=verbosity
            )
            if not resp_fallback:
                print(f"❌ Fallback failed for block {bi}/{len(blocks)}")
                return None
            resp = resp_fallback
        else:
            cleaned_parts = [strip_entry_labels(part) for part in parts]
            resp = "\n\n".join(cleaned_parts)

        # Store the translated block
        translations.append(resp.strip())

        # Update rolling summary for next block
        if bi < len(blocks):
            recent_text = " ".join(normalize_text(e.text) for e in block_entries)
            summary_prompt = build_summary_prompt(
                src_lang=src_lang,
                previous_summary=rolling_summary,
                recent_text=recent_text,
                max_chars=summary_max_chars
            )

            # Use the same llm_instance if keeping browser alive; otherwise, spin up a fresh one
            if keep_browser_alive:
                summary_llm = llm_instance
            else:
                if not getattr(llm, "config", None):
                    print(f"❌ LLMAdapter config is missing or invalid; cannot create new instance for summary.")
                    return None
                summary_llm = LLMAdapter(llm.config)

            try:
                new_summary = summary_llm.generate(summary_prompt, verbosity=verbosity)
            except Exception as e:
                print(f"❌ LLM generate call failed for rolling summary in block {bi}/{len(blocks)}: {e}")
                return None

            if new_summary:
                rolling_summary = new_summary.strip()
                if len(rolling_summary) > summary_max_chars:
                    rolling_summary = rolling_summary[:summary_max_chars]
                if verbosity >= 3:
                    print(f"      🛈 Rolling summary stored ({len(rolling_summary)} chars): {repr(rolling_summary)}")

            if verbosity >= 2:
                print(f"      ↳ Updated rolling summary length: {len(rolling_summary)} chars")

    return translations