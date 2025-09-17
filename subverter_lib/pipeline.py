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
    cfg = load_config()

    # Derive behaviour flags from context_mode
    mode = cfg.get("context_mode", "fresh_with_summary")
    reuse_chat = (mode == "reuse_chat")
    use_summary = (mode == "fresh_with_summary")
    summary_max_chars = cfg.get("summary_max_chars", 500)

    if verbosity >= 1:
        print(f"   🧠 Context mode: {mode} | reuse_chat={reuse_chat} | use_summary={use_summary}")

    # Build runtime allowlist without target language
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

                src_lang, track_id, srt_path, cleanup_paths = select_mkv_subtitle(
                    mkv_path=f,
                    mkvmerge_path=mkvmerge_path,
                    mkvextract_path=mkvextract_path,
                    allowed_src_langs_ordered=allowed_src_langs_ordered
                )

                if not src_lang or not srt_path:
                    print("❌ No usable subtitle track selected or extraction failed.\n")
                    continue

                working_srt = srt_path

            else:
                print(f"⚠️ Unsupported file type: {f.name} (.{f.suffix.lstrip('.')}) — skipping.\n")
                continue

            # --- Step 1: Parse and block build ---
            print(f"\n🎯 Target language: {cfg['target_language']}")
            print("➡️ Step 1: Parse and block build")
            if verbosity >= 1:
                print(f"   🛈 Parsing SRT file: {working_srt}")

            entries = parse_srt(working_srt)
            if not entries:
                print("❌ Failed to parse SRT or file is empty.")
                return

            if verbosity >= 1:
                print(f"   🛈 Parsed {len(entries)} subtitle entries.")

            # --- Step 2: Send to model backend ---
            print("➡️ Step 2: Send to model backend")
            if verbosity >= 1:
                print(f"   🛈 Backend: {cfg.get('backend', 'ollama')} | Model: {cfg.get('model', 'mistral')}")

            llm = LLMAdapter(LLMConfig(
                backend=cfg.get("backend", "ollama"),
                model=cfg.get("model", "mistral"),
                ollama_path=str(cfg.get("ollama_path")) if cfg.get("ollama_path") else None,
                timeout_sec=cfg.get("timeout_sec", 120),
            ))

            translations = translate_entries_with_context(
                entries=entries,
                src_lang=src_lang,
                tgt_lang=cfg["target_language"],
                llm=llm,
                char_limit=cfg.get("char_limit", 2500),
                verbosity=verbosity,
                reuse_chat=reuse_chat,
                use_summary=use_summary,
                summary_max_chars=summary_max_chars
            )

            if not translations:
                print("❌ Translation failed.")
                return

            # --- Step 3: Validate and reformat ---
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
                formatted = reformat_subtitle_text(t, max_width=42, max_lines=2)
                final_entries.append((e.idx, e.start, e.end, formatted))

            # --- Step 4: Write final SRT ---
            print("💾 Step 4: Write final SRT to output folder")
            if verbosity >= 1:
                print(f"   🛈 Output directory: {Path('output').resolve()}")

            out_dir = Path("output")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{working_srt.stem}.{cfg['target_language']}.srt"
            with open(out_path, "w", encoding="utf-8", newline="\n") as w:
                for i, (idx, start, end, text) in enumerate(final_entries, start=1):
                    w.write(f"{idx}\n")
                    w.write(f"{start} --> {end}\n")
                    w.write(text.strip() + "\n\n")

            print(f"✅ Wrote: {out_path}")

        finally:
            # Cleanup temporary files (except the chosen working file)
            for p in cleanup_paths:
                if p != working_srt:
                    p.unlink(missing_ok=True)