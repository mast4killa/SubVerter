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
    builtins.print(f"   🛈 Fallback: translating {len(entries)} entries individually.")
    for idx, e in enumerate(entries, start=1):
        builtins.print(f"      ↳ Entry {idx}/{len(entries)}")
        if verbosity >= 3:
            builtins.print(f"         Original text:\n{e.text}\n")

        prompt = build_translation_prompt(
            src_lang, tgt_lang, [e], summary_so_far,
            prev_context="", next_context="", verbosity=verbosity
        )

        try:
            resp = llm.generate(prompt)
        except Exception as ex:
            builtins.print(f"❌ LLM generate call failed for entry {idx}/{len(entries)}: {ex}")
            return None

        if not resp:
            builtins.print(f"❌ No output from LLM for entry {idx}/{len(entries)}")
            return None

        non_empty_lines = [l for l in resp.splitlines() if l.strip()]
        if (
            len(non_empty_lines) == 1
            and not non_empty_lines[0].lstrip().upper().startswith("ENTRY")
        ):
            builtins.print(f"❌ Model response refusal output for entry {idx}/{len(entries)}:")
            builtins.print(indent_block(resp.strip()))
            builtins.print(f"   🛈 Source subtitle text:")
            builtins.print(indent_block(e.text))
            return None

        lines = split_on_double_newline(resp)
        translated_line = lines[0] if lines else resp.strip()
        translated_line = strip_entry_labels(translated_line)

        if verbosity >= 3:
            builtins.print(f"         LLM output (cleaned):\n{translated_line}\n")

        out_parts.append(translated_line)

    return "\n\n".join(out_parts)


# === Status printing utilities ===

class StatusPrinter:
    """
    In-place status line printer with dynamic colon alignment:
    - Calculates absolute colon column from runtime parameters so ':' aligns across all depths.
    - Leaves ⚠️ LLM Response lines compact (no colon alignment).
    """
    def __init__(self,
                status_col_width: int = 24,
                total_subs: int = None,
                base_indent: int = 2,
                indent_step: int = 2,
                max_char_limit: int = 4000,
                min_char_limit: int = 200,
                icon_display_width: int = 2):
        self.status_w = status_col_width
        self.total_subs = total_subs
        self._active = None

        # store limits for later use
        self.max_char_limit = max_char_limit
        self.min_char_limit = min_char_limit

        # 1) Deepest possible depth (halvings + per-subtitle fallback)
        deepest_depth = 0
        limit = max_char_limit
        while limit > min_char_limit:
            limit //= 2
            deepest_depth += 1
        deepest_depth += 1  # per-subtitle fallback

        self.base_indent = base_indent
        self.indent_step = indent_step
        self.max_indent = base_indent + indent_step * deepest_depth

        # 2) Longest possible range string width
        max_digits = len(str(total_subs))
        longest_range = f"Subtitles {'9'*max_digits}-{'9'*max_digits} of {total_subs}"
        self.range_text_width = len(longest_range)

        # 3) Icon display width (emoji = 2 in most monospace fonts)
        self.icon_display_width_default = icon_display_width

        # 4) Absolute colon column (constant for all lines)
        self.colon_abs_col = self.max_indent + self.icon_display_width_default + 1 + self.range_text_width

    def _fmt_range(self, start_idx: int, end_idx: int) -> str:
        return f"Subtitles {start_idx}-{end_idx} of {self.total_subs}"

    def _fmt_status(self, status: str) -> str:
        return status.ljust(self.status_w)

    def _icon_display_width(self, icon: str) -> int:
        # Adjust if mixing ASCII and emoji icons
        return self.icon_display_width_default

    def print_step_header(self, text: str):
        builtins.print(f"➡️ {text}")

    def start_line(self, indent: int, icon: str, start_idx: int, end_idx: int,
                   status: str, extra: str = ""):
        self._active = (indent, icon, start_idx, end_idx)
        self.update_line(status, extra)

    def update_line(self, status: str, extra: str = "", icon_override: str = None):
        if not self._active:
            builtins.print(f"   {status} {extra}".rstrip())
            return
        indent, icon, start_idx, end_idx = self._active
        if icon_override:
            icon = icon_override
            self._active = (indent, icon, start_idx, end_idx)

        range_col = self._fmt_range(start_idx, end_idx)
        icon_w = self._icon_display_width(icon)

        pad_w = self.colon_abs_col - (indent + icon_w + 1)
        if pad_w < len(range_col):
            pad_w = len(range_col)

        msg = (
            "\r" + " " * indent +
            f"{icon} {range_col:<{pad_w}} : {status:<{self.status_w}}{extra}"
        ).rstrip()
        builtins.print(msg, end="", flush=True)

    def finalize_active(self):
        if self._active:
            builtins.print()
        self._active = None

    def print_line(self, indent: int, icon: str, start_idx: int, end_idx: int,
                   status: str, extra: str = ""):
        range_col = self._fmt_range(start_idx, end_idx)
        icon_w = self._icon_display_width(icon)

        pad_w = self.colon_abs_col - (indent + icon_w + 1)
        if pad_w < len(range_col):
            pad_w = len(range_col)

        msg = (
            " " * indent +
            f"{icon} {range_col:<{pad_w}} : {status:<{self.status_w}}{extra}"
        ).rstrip()
        builtins.print(msg)

    def print_detail_line(self, indent: int, icon: str, message: str):
        icon_w = self._icon_display_width(icon)

        if ":" in message:
            # Split into label and message part
            label, _, rest = message.partition(":")
            label = label.rstrip()
            rest = rest.lstrip()

            # Pad label so colon aligns with subtitle lines
            pad_w = self.colon_abs_col - (indent + icon_w + 1)
            if pad_w < len(label):
                pad_w = len(label)

            # === NEW: determine max width for message part ===
            # Build the longest possible subtitle line for per-subtitle char limit
            longest_status = "Translation in progress."  # longer than "complete."
            char_limit_str = f"(Char Limit = {self.min_char_limit} chars)"
            max_msg_width = len(longest_status) + 1 + len(char_limit_str)
            # This is the width from colon to end of the longest per-subtitle line

            # Word-wrap the message part using this width
            words = rest.split()
            lines = []
            current_line = ""
            for word in words:
                if not current_line:
                    current_line = word
                elif len(current_line) + 1 + len(word) <= max_msg_width:
                    current_line += " " + word
                else:
                    lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

            # Print first line with icon, label, colon, and first chunk of message
            builtins.print(" " * indent + f"{icon} {label:<{pad_w}} : {lines[0]}")

            # Print subsequent lines starting exactly under the message text
            msg_start_col = indent + icon_w + 1 + pad_w + 3  # space + colon + space
            for line in lines[1:]:
                builtins.print(" " * msg_start_col + line)

        else:
            # No colon → compact detail line
            builtins.print(" " * indent + f"{icon} {message}")


# === Logging helpers ===

def log_step_header(sp: StatusPrinter, text: str):
    sp.print_step_header(text)

def log_block_start(sp: StatusPrinter, start_idx: int, end_idx: int, char_limit_desc: str, depth: int):
    indent = 2 + depth * 2
    sp.start_line(indent, "🔹", start_idx, end_idx, "Translation in progress.", f" ({char_limit_desc})")

def log_block_done(sp: StatusPrinter, start_idx: int, end_idx: int, char_limit_desc: str, depth: int):
    sp.update_line("Translation complete.", f" ({char_limit_desc})", icon_override="✅")
    sp.finalize_active()

def log_block_failed(sp: StatusPrinter, start_idx: int, end_idx: int, char_limit_desc: str, depth: int):
    sp.update_line("Translation failed.", f" ({char_limit_desc})", icon_override="❌")
    sp.finalize_active()

def log_failure_detail(sp: StatusPrinter, message: str, debug_files: Optional[Tuple[str, str]], depth: int):
    indent = (2 + depth * 2) + 2
    sp.print_detail_line(indent, "⚠️", message)

    if debug_files:
        in_name, out_name = debug_files
        builtins.print(" " * indent + f"   See debug files: {in_name} / {out_name}")


# === Attempt block translation ===

class AttemptResult:
    def __init__(
        self,
        success: bool,
        text: Optional[str] = None,
        refusal_text: Optional[str] = None,
        mismatch_debug: Optional[Tuple[str, str]] = None
    ):
        self.success = success
        self.text = text
        self.refusal_text = refusal_text
        self.mismatch_debug = mismatch_debug


def attempt_block_translation(
    entries_subset: List[SRTEntry],
    llm_instance: LLMAdapter,
    src_lang: str,
    tgt_lang: str,
    summary_for_prompt: str,
    prev_ctx: str,
    next_ctx: str,
    verbosity: int,
    movie_folder: Path | None
) -> AttemptResult:
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
        return AttemptResult(False, refusal_text=f"LLM generate failed: {e}")

    if not resp:
        return AttemptResult(False, refusal_text="Model returned no output.")

    parts = split_on_entry_labels(resp)

    if validate_block_count(entries_subset, "\n\n".join(parts)):
        cleaned_parts = [strip_entry_labels(part) for part in parts]
        return AttemptResult(True, text="\n\n".join(cleaned_parts))

    non_empty_lines = [l for l in resp.splitlines() if l.strip()]
    if len(non_empty_lines) == 1 and not non_empty_lines[0].lstrip().upper().startswith("ENTRY"):
        return AttemptResult(False, refusal_text=non_empty_lines[0].strip())

    # Mismatch → write debug files
    if not movie_folder:
        movie_folder = Path.cwd()
    start_idx, end_idx = entries_subset[0].idx, entries_subset[-1].idx
    base = f"subtitles_{start_idx}-{end_idx}"
    in_file = movie_folder / f"{base}_input_en.txt"
    out_file = movie_folder / f"{base}_output_nl.txt"
    with open(in_file, "w", encoding="utf-8") as f_in:
        for e in entries_subset:
            f_in.write(f"[{e.idx}] {e.text}\n")
    with open(out_file, "w", encoding="utf-8") as f_out:
        for i, line in enumerate(parts, start=start_idx):
            f_out.write(f"[{i}] {line}\n")

    return AttemptResult(False, mismatch_debug=(in_file.name, out_file.name))


# === Progressive refinement with narrative logging ===

def progressive_refine(
    seg_entries: List[SRTEntry],
    llm_instance: LLMAdapter,
    src_lang: str,
    tgt_lang: str,
    summary_for_prompt: str,
    prev_ctx: str,
    next_ctx: str,
    verbosity: int,
    movie_folder: Path | None,
    min_char_limit: int,
    sp: StatusPrinter,
    current_limit: int,
    depth: int = 0
) -> tuple[str, int]:
    start_idx, end_idx = seg_entries[0].idx, seg_entries[-1].idx
    desc = f"Char Limit = {current_limit} chars"

    # Announce work start (in-place line)
    log_block_start(sp, start_idx, end_idx, desc, depth)

    # Attempt as a block
    result = attempt_block_translation(
        seg_entries, llm_instance, src_lang, tgt_lang,
        summary_for_prompt, prev_ctx, next_ctx,
        verbosity, movie_folder
    )

    if result.success and result.text is not None:
        log_block_done(sp, start_idx, end_idx, desc, depth)
        return result.text, current_limit

    # Failed → replace line and print short detail
    log_block_failed(sp, start_idx, end_idx, desc, depth)
    if result.refusal_text:
        log_failure_detail(sp, f"LLM Response: {result.refusal_text}", None, depth)
    elif result.mismatch_debug:
        log_failure_detail(
            sp,
            "Mismatch between number of original and translated subtitles.",
            result.mismatch_debug,
            depth
        )

    # Decide fallback or split
    seg_text_len = sum(len(e.text) for e in seg_entries)
    if seg_text_len <= min_char_limit or len(seg_entries) <= 1:
        translated = translate_block_fallback_per_entry(
            llm_instance, src_lang, tgt_lang, seg_entries,
            summary_for_prompt, verbosity=verbosity
        )
        if translated is None:
            raise RuntimeError(f"Fallback failed for {start_idx}-{end_idx}")
        sp.print_line(
            2 + depth * 2, "✅", start_idx, end_idx,
            "Translation complete.", " (Char Limit = per-subtitle)"
        )
        return translated, min_char_limit

    # Split into two halves and refine children
    mid = len(seg_entries) // 2
    left, right = seg_entries[:mid], seg_entries[mid:]
    child_limit = max(min_char_limit, current_limit // 2)

    left_text, left_limit = progressive_refine(
        left, llm_instance, src_lang, tgt_lang,
        summary_for_prompt, prev_ctx, next_ctx,
        verbosity, movie_folder, min_char_limit,
        sp, current_limit=child_limit, depth=depth + 1
    )
    right_text, right_limit = progressive_refine(
        right, llm_instance, src_lang, tgt_lang,
        summary_for_prompt, prev_ctx, next_ctx,
        verbosity, movie_folder, min_char_limit,
        sp, current_limit=child_limit, depth=depth + 1
    )

    # Parent closure label
    if left_limit != right_limit:
        parent_desc = "Char Limit = mixed"
    else:
        parent_desc = f"Char Limit = {left_limit} chars"

    sp.print_line(
        2 + depth * 2, "✅", start_idx, end_idx,
        "Translation complete.", f" ({parent_desc})"
    )
    return "\n\n".join([left_text, right_text]), left_limit


# === Main translation loop ===

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
    try:
        effective_char_limit = min(char_limit, 7500) - summary_max_chars
        if effective_char_limit < min_char_limit:
            effective_char_limit = min_char_limit

        blocks = build_blocks(entries, effective_char_limit)
        translations: List[str] = []
        rolling_summary = ""

        sp = StatusPrinter(
            status_col_width=24,
            total_subs=len(entries),
            max_char_limit=char_limit,
            min_char_limit=min_char_limit,
            icon_display_width=2  # for emojis in Notepad++
        )

        if verbosity >= 1:
            builtins.print(f"   🛈 Built {len(blocks)} blocks (Char Limit = {effective_char_limit} chars)")

        for bi, (start, end) in enumerate(blocks, start=1):
            block_entries = entries[start:end + 1]
            prev_ctx, next_ctx = context_slice(entries, start, end, prev_n=5, next_n=5)
            summary_for_prompt = rolling_summary

            if verbosity >= 1:
                builtins.print(f"\n   🔹 Translating block {bi}/{len(blocks)} "
                               f"({block_entries[0].idx}–{block_entries[-1].idx}, {len(block_entries)} subtitles)")
            if verbosity >= 2:
                builtins.print("      ↳ First subtitle text:", repr(block_entries[0].text))
                builtins.print("      ↳ Last subtitle text:", repr(block_entries[-1].text))
            if verbosity >= 3:
                builtins.print("      ↳ Full block text to translate:")
                for e in block_entries:
                    builtins.print(f"         [{e.idx}] {e.text}")
                builtins.print("\n      ↳ Previous context:\n", prev_ctx or "(none)")
                builtins.print("\n      ↳ Next context:\n", next_ctx or "(none)")
                if summary_for_prompt:
                    builtins.print(f"      🛈 Summary passed to prompt ({len(summary_for_prompt)} chars): "
                                   f"{repr(summary_for_prompt)}")

            llm_instance = llm if keep_browser_alive else LLMAdapter(llm.config)

            # Progressive refinement now returns (text, limit_used)
            text, _ = progressive_refine(
                block_entries, llm_instance, src_lang, tgt_lang,
                summary_for_prompt, prev_ctx, next_ctx,
                verbosity, movie_folder, min_char_limit,
                sp, current_limit=effective_char_limit, depth=0
            )
            translations.append(text.strip())

            if bi < len(blocks):
                recent_text = " ".join(normalize_text(e.text) for e in block_entries)
                summary_prompt = build_summary_prompt(
                    src_lang=src_lang,
                    previous_summary=rolling_summary,
                    recent_text=recent_text,
                    max_chars=summary_max_chars
                )
                summary_llm = llm_instance if keep_browser_alive else LLMAdapter(llm.config)
                try:
                    new_summary = summary_llm.generate(summary_prompt, verbosity=verbosity)
                except Exception as e:
                    builtins.print(f"❌ LLM generate call failed for rolling summary in block {bi}/{len(blocks)}: {e}")
                    return None
                if new_summary:
                    rolling_summary = new_summary.strip()[:summary_max_chars]

        return translations

    finally:
        if 'sp' in locals():
            sp.finalize_active()