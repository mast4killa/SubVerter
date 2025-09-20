# CLI entry point — minimal logic:
# - Parses command-line args
# - Dispatches to installers or main pipeline

#!/usr/bin/env python3
from __future__ import annotations

"""
SubVerter — Context-aware subtitle translation using AI.

CLI entry point — minimal logic here:
- Parses command-line arguments.
- Dispatches to:
    • subverter_lib/installers.py → install() / uninstall()
    • subverter_lib/pipeline.py   → run_pipeline()

# ============================================================
# 📂 Project Structure
# ============================================================
subverter/
├── subverter.py                 # CLI entry point — just parses args & dispatches
│
├── subverter_lib/               # All reusable logic lives here
│   ├── __init__.py              # Empty for now (marks this as a package)
│   ├── config_manager.py        # Load/save/validate config.json
│   ├── installers.py            # install() / uninstall() registry helpers
│   ├── lang_utils.py            # Language code normalization & filtering
│   ├── llm_adapter.py           # Model-agnostic LLM interface (Ollama + stubs)
│   ├── mkv_utils.py             # MKV probing, extraction, track selection
│   ├── pipeline.py              # run_pipeline() — orchestrates the workflow
│   ├── prompt_utils.py          # Builds context-aware translation prompts
│   ├── reformat.py              # Soft-wrap & reformat subtitles
│   ├── srt_utils.py             # Parse SRT, detect language, build blocks
│   └── translator.py            # Block-wise translation & fallback logic
│
├── cfg/
│   └── config.json              # User-editable configuration
│   └── copilot_storage.json     # Internal cache for AI-related state and progress
│
├── requirements.txt             # Python dependencies
├── README.md                    # Project documentation

# ============================================================
# 🔗 Import Map
# ============================================================
subverter.py
 ├─ subverter_lib.installers.install / uninstall
 └─ subverter_lib.pipeline.run_pipeline
      ├─ subverter_lib.config_manager.load_config
      ├─ subverter_lib.lang_utils.normalize_lang_code
      ├─ subverter_lib.srt_utils.detect_language_from_srt / parse_srt
      ├─ subverter_lib.mkv_utils.select_mkv_subtitle
      ├─ subverter_lib.llm_adapter.LLMAdapter / LLMConfig
      ├─ subverter_lib.translator.translate_entries_with_context
      └─ subverter_lib.reformat.reformat_subtitle_text
"""

import argparse
from pathlib import Path

from subverter_lib.installers import install, uninstall
from subverter_lib.pipeline import run_pipeline


def main() -> None:
    """
    Entry point for SubVerter CLI.

    Parses command-line arguments and dispatches to appropriate actions:
    - Installs or uninstalls context menu entries.
    - Runs subtitle translation pipeline on provided files.

    Arguments:
        None (arguments are parsed from sys.argv)

    Returns:
        None (exits with status code 0 on success, non-zero on failure)
    """
    parser = argparse.ArgumentParser(
        prog="SubVerter",
        description="SubVerter — Context-aware subtitle translation using AI",
        epilog="Example: SubVerter movie.srt -vv"
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="One or more .srt or .mkv files to process"
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--install",
        action="store_true",
        help="Install dependencies, create/validate config, and add right‑click menu entries"
    )
    group.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall right-click context menu entry"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase output verbosity (can be used multiple times: -v, -vv, -vvv)"
    )

    args = parser.parse_args()

    # Clamp verbosity to max 3
    args.verbose = min(args.verbose, 3)

    try:
        if args.install:
            install()
            return
        if args.uninstall:
            uninstall()
            return
        if not args.files:
            parser.print_help()
            print("\n❌ No input files provided. Please specify one or more .srt or .mkv files.")
            raise SystemExit(1)

        run_pipeline(args.files, verbosity=args.verbose)
        print("\n✅ Done. You can close this window.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()