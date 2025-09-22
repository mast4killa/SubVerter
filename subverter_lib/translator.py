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
import builtins
from typing import List, Optional, Tuple
from pathlib import Path

from subverter_lib.srt_utils import SRTEntry, build_blocks, context_slice
from subverter_lib.prompt_utils import build_translation_prompt, build_summary_prompt
from subverter_lib.llm_adapter import LLMAdapter
from subverter_lib.lang_utils import normalize_text

# Regex to detect ENTRY labels at the start of lines
ENTRY_LABEL_RE = re.compile(r"^ENTRY\s+\d+:\s*", re.IGNORECASE)


# === Progress bar helpers ===
current_bar = ""
bar_visible = False  # whether a bar is currently occupying the line

def draw_bar(completed: int, total: int):
    """Draw or update the progress bar."""
    global current_bar, bar_visible
    current_bar = f"[{'#'*completed}{'_'*(total-completed)}]"
    builtins.print(f"\rTranslation progress: {current_bar}", end="", flush=True)
    bar_visible = True

def print_msg(*args, **kwargs):
    """Print a message without corrupting the progress bar display."""
    global bar_visible, current_bar
    if bar_visible:
        clear_len = len("Translation progress: ") + len(current_bar)
        builtins.print("\r" + " " * clear_len + "\r", end="")
        bar_visible = False
    builtins.print(*args, **kwargs)
    if current_bar:
        builtins.print(f"\rTranslation progress: {current_bar}", end="", flush=True)
        bar_visible = True

def finish_bar_line():
    """Clear the progress bar and print a completion message."""
    global bar_visible
    if bar_visible:
        builtins.print("\rTranslation completed." + " " * max(0, len(current_bar) - len("completed")))
        bar_visible = False
# === End progress bar helpers ===


def indent_block(text: str, prefix: str = "      ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


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
    print(f"   🛈 Fallback: translating {len(entries)} entries individually.")
    for idx, e in enumerate(entries, start=1):
        print(f"      ↳ Entry {idx}/{len(entries)}")
        if verbosity >= 3:
            print(f"         Original text:\n{e.text}\n")

        prompt = build_translation_prompt(
            src_lang, tgt_lang, [e], summary_so_far,
            prev_context="", next_context="", verbosity=verbosity
        )

        try:
            resp = llm.generate(prompt)
        except Exception as ex:
            print(f"❌ LLM generate call failed for entry {idx}/{len(entries)}: {ex}")
            return None

        if not resp:
            print(f"❌ No output from LLM for entry {idx}/{len(entries)}")
            return None

        non_empty_lines = [l for l in resp.splitlines() if l.strip()]
        if (
            len(non_empty_lines) == 1
            and not non_empty_lines[0].lstrip().upper().startswith("ENTRY")
        ):
            print(f"❌ Model response refusal output for entry {idx}/{len(entries)}:")
            print(indent_block(resp.strip()))
            print(f"   🛈 Source subtitle text:")
            print(indent_block(e.text))
            return None

        lines = split_on_double_newline(resp)
        translated_line = lines[0] if lines else resp.strip()
        translated_line = strip_entry_labels(translated_line)

        if verbosity >= 3:
            print(f"         LLM output (cleaned):\n{translated_line}\n")

        out_parts.append(translated_line)

    return "\n\n".join(out_parts)


def format_segment_range(entries: List[SRTEntry]) -> str:
    """Return a human-readable range string for a segment."""
    if not entries:
        return "(empty)"
    if len(entries) == 1:
        return f"entry {entries[0].idx}"
    return f"entries {entries[0].idx}–{entries[-1].idx}"

def attempt_block_translation(
    entries_subset: List[SRTEntry],
    llm_instance: LLMAdapter,
    src_lang: str,
    tgt_lang: str,
    summary_for_prompt: str,
    prev_ctx: str,
    next_ctx: str,
    verbosity: int,
    movie_folder: Path | None,
    block_label: str
) -> Tuple[bool, Optional[str]]:
    """
    Attempt to translate a given list of entries as one block.
    Returns (success, cleaned_translation or None).
    """
    prompt = build_translation_prompt(
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        block_entries=entries_subset,
        summary_so_far=summary_for_prompt,
        prev_context=prev_ctx,
        next_context=next_ctx,
        verbosity=verbosity
    )

    try:
        resp = llm_instance.generate(prompt, verbosity=verbosity)
    except Exception as e:
        print(f"❌ LLM generate call failed for {block_label}: {e}")
        return False, None

    if not resp:
        print(f"❌ Model returned no output for {block_label}")
        return False, None

    parts = split_on_entry_labels(resp)
    if verbosity >= 2:
        print(f"      ↳ LLM returned {len(parts)} entries for {block_label}.")
        if verbosity == 2:
            print("         First few lines of output:")
            for l in parts[:3]:
                print("           ", l)
            if len(parts) > 3:
                print("           ...")
        elif verbosity >= 3:
            print("      ↳ Full LLM output:\n", resp)

    if validate_block_count(entries_subset, "\n\n".join(parts)):
        cleaned_parts = [strip_entry_labels(part) for part in parts]
        return True, "\n\n".join(cleaned_parts)

    # Refusal detection
    non_empty_lines = [l for l in resp.splitlines() if l.strip()]
    if (
        len(non_empty_lines) == 1
        and not non_empty_lines[0].lstrip().upper().startswith("ENTRY")
    ):
        print(f"❌ Model response refusal output for {block_label}:")
        print(indent_block(resp.strip()))
        return False, None

    # Mismatch: log + debug files
    print(f"⚠️ Count mismatch in {block_label}.")
    if not movie_folder:
        movie_folder = Path.cwd()
    in_file = movie_folder / f"{block_label.replace(' ', '_')}_input_en.txt"
    out_file = movie_folder / f"{block_label.replace(' ', '_')}_output_nl.txt"
    with open(in_file, "w", encoding="utf-8") as f_in:
        for e in entries_subset:
            f_in.write(f"[{e.idx}] {e.text}\n")
    with open(out_file, "w", encoding="utf-8") as f_out:
        for i, line in enumerate(parts, start=entries_subset[0].idx):
            f_out.write(f"[{i}] {line}\n")
    print(f"   🛈 Saved mismatch debug to:\n      {in_file.name}\n      {out_file.name}")
    return False, None

def progressive_refine(
    segments: List[List[SRTEntry]],
    llm_instance: LLMAdapter,
    src_lang: str,
    tgt_lang: str,
    summary_for_prompt: str,
    prev_ctx: str,
    next_ctx: str,
    verbosity: int,
    movie_folder: Path | None,
    min_char_limit: int
) -> List[str]:
    """
    Recursively refine only failed segments until all succeed.
    Returns list of translated segment strings in original order.
    """
    results: List[Optional[str]] = [None] * len(segments)
    failed_segments: List[Tuple[int, List[SRTEntry]]] = []

    # First pass: try each segment
    for idx, seg_entries in enumerate(segments):
        seg_label = f"segment {format_segment_range(seg_entries)}"
        print(f"   🔹 Translating {seg_label}...")
        success, translated = attempt_block_translation(
            seg_entries, llm_instance, src_lang, tgt_lang,
            summary_for_prompt, prev_ctx, next_ctx,
            verbosity, movie_folder, seg_label
        )
        if success and translated is not None:
            results[idx] = translated
        else:
            failed_segments.append((idx, seg_entries))

    # If no failures, return all results
    if not failed_segments:
        return [r for r in results if r is not None]

    # Refine each failed segment
    for idx, seg_entries in failed_segments:
        # Stop splitting if segment is already at or below min_char_limit
        seg_text_len = sum(len(e.text) for e in seg_entries)
        if seg_text_len <= min_char_limit:
            # Fallback to per-entry
            print(f"   ↩️ Falling back to per-entry translation for {format_segment_range(seg_entries)}...")
            translated = translate_block_fallback_per_entry(
                llm_instance, src_lang, tgt_lang, seg_entries,
                summary_for_prompt, verbosity=verbosity
            )
            if translated is None:
                raise RuntimeError(f"Fallback failed for {format_segment_range(seg_entries)}")
            results[idx] = translated
            continue

        # Split into two halves and recurse
        mid = len(seg_entries) // 2
        sub_segments = [seg_entries[:mid], seg_entries[mid:]]
        sub_results = progressive_refine(
            sub_segments, llm_instance, src_lang, tgt_lang,
            summary_for_prompt, prev_ctx, next_ctx,
            verbosity, movie_folder, min_char_limit
        )
        results[idx] = "\n\n".join(sub_results)

    return [r for r in results if r is not None]


# translate_entries_with_context() — main translation loop with fallback and rolling summary
def translate_entries_with_context(
    entries: List[SRTEntry],
    src_lang: str,
    tgt_lang: str,
    llm: LLMAdapter,
    char_limit: int,
    verbosity: int = 0,
    keep_browser_alive: bool = False,
    summary_max_chars: int = 500,
    movie_folder: Path | None = None,
    min_char_limit: int = 400
) -> Optional[List[str]]:
    """
    Translate a list of SRT entries in context-aware blocks using progressive refinement.

    Args:
        entries: Parsed SRT entries.
        src_lang: Source language code.
        tgt_lang: Target language code.
        llm: LLMAdapter instance (used if keep_browser_alive=True).
        char_limit: Max characters per translation block (from config: max_char_limit).
        verbosity: Verbosity level.
        keep_browser_alive: If True, keep the same browser session alive for all blocks
                            (persistent mode), starting a new chat per block.
        summary_max_chars: Max characters to keep in rolling summary.
        movie_folder: Folder where mismatch debug files will be written.
        min_char_limit: Minimum block size before falling back to per-entry translation.
    """
    global print
    print = print_msg  # bar-safe print

    try:
        effective_char_limit = min(char_limit, 7500) - summary_max_chars
        if effective_char_limit < min_char_limit:
            effective_char_limit = min_char_limit

        try:
            blocks = build_blocks(entries, effective_char_limit)
        except Exception as e:
            print(f"❌ Failed to build translation blocks: {e}")
            return None

        translations: List[str] = []
        rolling_summary = ""

        if verbosity >= 1:
            print(f"   🛈 Built {len(blocks)} translation blocks (char_limit={effective_char_limit}).")

        draw_bar(0, len(blocks))

        for bi, (start, end) in enumerate(blocks, start=1):
            block_entries = entries[start:end + 1]
            try:
                prev_ctx, next_ctx = context_slice(entries, start, end, prev_n=5, next_n=5)
            except Exception as e:
                print(f"❌ Failed to extract context for block {bi}/{len(blocks)}: {e}")
                return None

            if verbosity >= 1:
                print(f"\n   🔹 Translating block {bi}/{len(blocks)} "
                      f"({format_segment_range(block_entries)}, {len(block_entries)} entries)")

            if verbosity >= 2:
                print("      ↳ First entry text:", repr(block_entries[0].text))
                print("      ↳ Last entry text:", repr(block_entries[-1].text))
            if verbosity >= 3:
                print("      ↳ Full block text to translate:")
                for e in block_entries:
                    print(f"         [{e.idx}] {e.text}")
                print("\n      ↳ Previous context:\n", prev_ctx or "(none)")
                print("\n      ↳ Next context:\n", next_ctx or "(none)")

            summary_for_prompt = rolling_summary
            if summary_for_prompt and verbosity >= 3:
                print(f"      🛈 Summary passed to prompt ({len(summary_for_prompt)} chars): "
                      f"{repr(summary_for_prompt)}")

            # Choose LLM instance
            if keep_browser_alive:
                llm_instance = llm
            else:
                if not getattr(llm, "config", None):
                    print(f"❌ LLMAdapter config is missing or invalid; cannot create new instance.")
                    return None
                llm_instance = LLMAdapter(llm.config)

            # === Progressive refinement ===
            success, translated_block = attempt_block_translation(
                block_entries, llm_instance, src_lang, tgt_lang,
                summary_for_prompt, prev_ctx, next_ctx,
                verbosity, movie_folder, f"block_{bi:02d}"
            )

            if not success:
                # Split into halves and refine only failed parts
                mid = len(block_entries) // 2
                segments = [block_entries[:mid], block_entries[mid:]]
                segment_results = progressive_refine(
                    segments, llm_instance, src_lang, tgt_lang,
                    summary_for_prompt, prev_ctx, next_ctx,
                    verbosity, movie_folder, min_char_limit
                )
                translated_block = "\n\n".join(segment_results)

            translations.append(translated_block.strip())

            # Update progress bar
            draw_bar(bi, len(blocks))

            # === Rolling summary update ===
            if bi < len(blocks):
                recent_text = " ".join(normalize_text(e.text) for e in block_entries)
                summary_prompt = build_summary_prompt(
                    src_lang=src_lang,
                    previous_summary=rolling_summary,
                    recent_text=recent_text,
                    max_chars=summary_max_chars
                )

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
                        print(f"      🛈 Rolling summary stored ({len(rolling_summary)} chars): "
                              f"{repr(rolling_summary)}")
                if verbosity >= 2:
                    print(f"      ↳ Updated rolling summary length: {len(rolling_summary)} chars")

        return translations

    finally:
        # Ensure the progress bar line ends cleanly
        finish_bar_line()  # replaces bare print() so the bar is cleared properly

        # Restore the built‑in print so outside code is unaffected
        print = builtins.print