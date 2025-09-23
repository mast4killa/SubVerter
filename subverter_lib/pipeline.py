#!/usr/bin/env python3
from __future__ import annotations

"""
Main processing pipeline for SubVerter.

Handles:
- SRT: detect language, verify allowed, and proceed.
- MKV: select a single subtitle track using tagged preference or interactive choice,
       extract to SRT, validate language, and proceed.
- Translation via configured LLM backend.
- Validation, reformatting, and output of final SRT.
"""

import os

from pathlib import Path
from typing import Sequence

from subverter_lib.config_manager import load_config
from subverter_lib.lang_utils import normalize_lang_code
from subverter_lib.srt_utils import detect_language_from_srt, parse_srt
from subverter_lib.mkv_utils import select_mkv_subtitle
from subverter_lib.llm_adapter import LLMAdapter, LLMConfig
from subverter_lib.translator import translate_entries_with_context
from subverter_lib.reformat import reformat_subtitle_text


def run_pipeline(files: Sequence[Path], verbosity: int = 0) -> None:
    """
    Main processing pipeline for SubVerter.

    Args:
        files: Sequence of Path objects pointing to .srt or .mkv files.
        verbosity: Verbosity level (0 = normal output, higher = more debug info).
    """
    try:
        cfg = load_config()
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return

    # Derive behaviour flags from config
    keep_browser_alive = bool(cfg.get("keep_browser_alive", False))
    summary_max_chars = cfg.get("summary_max_chars", 500)

    if verbosity >= 1:
        print(f"   🧠 keep_browser_alive={keep_browser_alive} | summary_max_chars={summary_max_chars}")

    # Build allowed source language list, excluding the target language
    tgt_lang = cfg["target_language"].lower()
    allowed_src_langs_ordered = [
        lang.lower()
        for lang in cfg.get("allowed_src_langs_ordered", [])
        if lang.lower() != tgt_lang
    ]
    if not allowed_src_langs_ordered:
        print("❌ No allowed source languages remain after removing the target language.\n")
        print(f"   📜 Allowed source languages : {', '.join(allowed_src_langs_ordered) or 'None'}")
        print(f"   🎯 Target language          : {tgt_lang}")
        print("   ⚠️  Please update your configuration to include at least one valid source language.\n")
        return

    mkvextract_path = Path(cfg["mkvextract_path"])
    mkvmerge_path = Path(cfg["mkvmerge_path"])

    for f in files:
        print("\n" + "=" * 60)
        print(f"📂 Processing file: {f.name}")
        print("=" * 60 + "\n")

        if not f.exists():
            print(f"⚠️ Skipping missing file: {f}\n")
            continue

        llm: LLMAdapter | None = None
        src_lang: str | None = None
        working_srt: Path | None = None
        cleanup_paths: list[Path] = []

        try:
            # --- SRT handling ---
            if f.suffix.lower() == ".srt":
                lang = detect_language_from_srt(f)
                if not lang:
                    print(f"❌ Could not detect language for {f.name}.")
                    continue
                src_lang = normalize_lang_code(lang)
                print(f"🌐 Detected source language: {src_lang}")

                if src_lang not in allowed_src_langs_ordered:
                    print(f"❌ Source language '{src_lang}' is not in allowed list.")
                    continue

                working_srt = f

            # --- MKV handling ---
            elif f.suffix.lower() == ".mkv":
                if not mkvmerge_path.exists() or not mkvextract_path.exists():
                    print(
                        f"❌ mkvtoolnix not found (expected mkvmerge at {mkvmerge_path}, "
                        f"mkvextract at {mkvextract_path})"
                    )
                    print("   Update mkvextract_path in config or install MKVToolNix.\n")
                    continue

                try:
                    src_lang, track_id, srt_path, cleanup_paths = select_mkv_subtitle(
                        mkv_path=f,
                        mkvmerge_path=mkvmerge_path,
                        mkvextract_path=mkvextract_path,
                        allowed_src_langs_ordered=allowed_src_langs_ordered
                    )
                except Exception as e:
                    print(f"❌ Failed to select MKV subtitle: {e}")
                    continue

                if not src_lang or not srt_path:
                    print("❌ No usable subtitle track selected or extraction failed.\n")
                    continue

                working_srt = srt_path

            else:
                print(f"⚠️ Unsupported file type: {f.name} (.{f.suffix.lstrip('.')}) — skipping.\n")
                continue

            # Step 1: Parse SRT into structured entries
            print(f"\n🎯 Target language: {cfg['target_language']}")
            print("➡️ Step 1: Parse and block build")
            if verbosity >= 1:
                print(f"   🛈 Parsing SRT file: {working_srt}")

            try:
                entries = parse_srt(working_srt)
            except Exception as e:
                print(f"❌ Failed to parse SRT file {working_srt}: {e}")
                return
            if not entries:
                print("❌ Failed to parse SRT or file is empty.")
                return

            if verbosity >= 1:
                print(f"   🛈 Parsed {len(entries)} subtitle entries.")

            # Step 2: Translate entries in context-aware blocks
            print("➡️ Step 2: Send to model backend")
            if verbosity >= 1:
                print(f"   🛈 Backend: {cfg.get('backend', 'ollama')} | Model: {cfg.get('model', 'mistral')}")

            llm = LLMAdapter(LLMConfig(
                backend=cfg.get("backend", "ollama"),
                model=cfg.get("model", "mistral"),
                ollama_path=str(cfg.get("ollama_path")) if cfg.get("ollama_path") else None,
                timeout_sec=cfg.get("timeout_sec", 120),
                keep_browser_alive=keep_browser_alive
            ))

            try:
                translations = translate_entries_with_context(
                    entries=entries,
                    src_lang=src_lang,
                    tgt_lang=cfg["target_language"],
                    llm=llm,
                    char_limit=cfg.get("max_char_limit", 4500),       # use new max
                    verbosity=verbosity,
                    keep_browser_alive=keep_browser_alive,
                    summary_max_chars=summary_max_chars,
                    movie_folder=f.parent,
                    min_char_limit=cfg.get("min_char_limit", 400)     # pass through min
                )
            except Exception as e:
                print(f"❌ Translation step failed: {e}")
                return

            if not translations:
                print("❌ Translation failed.")
                return

            # Step 3: Reformat translated text to fit subtitle constraints
            print("➡️ Step 3: Validate and reformat")

            translated_text = "\n\n".join(translations)
            translated_chunks = [c.strip() for c in translated_text.split("\n\n")]
            if len(translated_chunks) != len(entries):
                print("⚠️ Mismatch after merging; attempting recovery.")
                if len(translated_chunks) < len(entries):
                    translated_chunks += [""] * (len(entries) - len(translated_chunks))
                else:
                    translated_chunks = translated_chunks[:len(entries)]

            final_entries = []
            for e, t in zip(entries, translated_chunks):
                try:
                    formatted = reformat_subtitle_text(t, max_width=42, max_lines=2)
                except Exception as e:
                    print(f"❌ Failed to reformat subtitle text: {e}")
                    formatted = t
                final_entries.append((e.idx, e.start, e.end, formatted))

            # Step 4: Write final SRT next to input file
            print("💾 Step 4: Write final SRT next to input file")

            # Decide base name:
            if f.suffix.lower() == ".srt":
                # If filename ends with ".<src_lang>.srt", strip the src_lang part
                src_suffix = f".{src_lang.lower()}"
                if f.stem.lower().endswith(src_suffix):
                    base_name = f.stem[: -len(src_suffix)]
                else:
                    base_name = f.stem
            else:
                # MKV case: use MKV's stem (no _track# from extracted temp SRT)
                base_name = f.stem

            # Build output path in the same directory as the input file
            out_path = f.parent / f"{base_name}.{cfg['target_language']}.srt"

            if verbosity >= 1:
                print(f"   🛈 Target path: {out_path}")

            # If the target file already exists, rename it to .old (with counter if needed)
            if out_path.exists():
                backup_path = out_path.with_suffix(out_path.suffix + ".old")
                counter = 1
                while backup_path.exists():
                    backup_path = out_path.with_suffix(out_path.suffix + f".old.{counter}")
                    counter += 1
                try:
                    out_path.rename(backup_path)
                    if verbosity >= 1:
                        print(f"⚠️ Existing file renamed to: {backup_path}")
                except OSError as e:
                    print(f"❌ Failed to rename existing file {out_path} to {backup_path}: {e}")
                    return

            # Write the final SRT
            try:
                with open(out_path, "w", encoding="utf-8", newline="\n") as w:
                    for i, (idx, start, end, text) in enumerate(final_entries, start=1):
                        w.write(f"{idx}\n")
                        w.write(f"{start} --> {end}\n")
                        w.write(text.strip() + "\n\n")
                print(f"✅ Wrote: {out_path}")

                # ✅ Remove extracted MKV track SRT if translation succeeded
                try:
                    if f.suffix.lower() == ".mkv" and working_srt != f and working_srt.exists():
                        working_srt.unlink()
                        if verbosity >= 1:
                            print(f"🗑️ Deleted temporary source-language SRT: {working_srt}")
                except Exception as e:
                    if verbosity >= 1:
                        print(f"⚠️ Failed to delete temporary source-language SRT {working_srt}: {e}")

            except OSError as e:
                print(f"❌ Failed to write output file {out_path}: {e}")
                if out_path.exists():
                    try:
                        out_path.unlink()
                        print(f"⚠️ Deleted incomplete file: {out_path}")
                    except OSError as del_err:
                        print(f"⚠️ Could not delete incomplete file {out_path}: {del_err}")

        finally:
            # Close persistent Copilot session if it was used
            try:
                if (
                    llm
                    and getattr(llm.config, "keep_browser_alive", False)
                    and getattr(llm, "config", None)
                ):
                    if llm.config.backend.lower() == "copilot_web":
                        if hasattr(llm, "_copilot_client") and llm._copilot_client:
                            llm._copilot_client.close()
                            llm._copilot_client = None
            except Exception as e:
                if verbosity >= 1:
                    print(f"⚠️ Failed to close persistent Copilot session: {e}")

            # Cleanup temporary files (except the chosen working file)
            for p in cleanup_paths:
                if p != working_srt:
                    p.unlink(missing_ok=True)