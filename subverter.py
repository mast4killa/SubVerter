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
├── subverter.py                # CLI entry point — just parses args & dispatches
│
├── subverter_lib/                         # All reusable logic lives here
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
│   └── copilot_storage.json     # TODO: I still have to describe this one!! HELP ME
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
    Parse command-line arguments and run the appropriate action.
    """
    parser = argparse.ArgumentParser(
        description="SubVerter — Context-aware subtitle translation using AI"
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="One or more .srt or .mkv files to process"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install right-click context menu entry"
    )
    parser.add_argument(
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

    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
        return
    if not args.files:
        parser.print_help()
        return

    # Pass verbosity level into the pipeline
    run_pipeline(args.files, verbosity=args.verbose)


if __name__ == "__main__":
    main()
    print("\n✅ Done. You can close this window.")