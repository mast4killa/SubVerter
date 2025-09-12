#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import site
import subprocess
import sys
import winreg
from pathlib import Path

from config_manager import create_default_config, load_config, validate_config
from lang_utils import filter_allowed_candidates, normalize_lang_code


# ============================================================
# CONFIG & CONSTANTS
# ============================================================

# No constants here yet — config is loaded from config_manager.py


# ============================================================
# SRT HELPERS
# ============================================================

def detect_language_from_srt(path: Path) -> str | None:
    """
    Detect the language of an SRT file.
    """
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
    except ImportError:
        print("❌ Missing dependency: langdetect. Please install it first.")
        return None

    try:
        text_lines = []
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
        return detect(sample)
    except Exception as e:
        print(f"❌ Language detection failed for {path.name}: {e}")
        return None
    

# ============================================================
# MKV HELPERS
# ============================================================

def probe_mkv_subtitles(mkvmerge_path: Path, mkv_path: Path) -> tuple[list[dict], list[int]]:
    """
    Use mkvmerge -J to read all tracks and split into:
    - tagged_subs: list of dicts {id, lang_raw, lang_norm, name, codec}
    - untagged_ids: list of subtitle track IDs with no usable language tag
    """
    try:
        # First attempt: keep stderr separate so JSON stays clean
        result_json = subprocess.run(
            [str(mkvmerge_path), "-J", str(mkv_path)],
            capture_output=True, text=True, check=True
        )
        try:
            info = json.loads(result_json.stdout)
        except json.JSONDecodeError:
            # Retry with merged stderr for diagnostics
            print("❌ mkvmerge output was not valid JSON. Retrying with merged stderr for diagnostics...")
            debug_run = subprocess.run(
                [str(mkvmerge_path), "-J", str(mkv_path)],
                capture_output=True, text=True, check=False,
                stderr=subprocess.STDOUT
            )
            print("---- mkvmerge combined output ----")
            print(debug_run.stdout)
            print("---- end output ----")
            return [], []
    except Exception as e:
        print(f"❌ Failed to run mkvmerge at '{mkvmerge_path}' on file '{mkv_path}': {e}")
        print("   💡 Check that MKVToolNix is installed and mkvmerge is available at this path.")
        return [], []

    tagged_subs: list[dict] = []
    untagged_ids: list[int] = []

    for track in info.get("tracks", []):
        if track.get("type") != "subtitles":
            continue
        tid = track.get("id")
        props = track.get("properties", {}) or {}
        lang_raw = props.get("language_ietf") or props.get("language")
        name = props.get("track_name")
        codec = props.get("codec_id") or props.get("codec")

        if lang_raw and lang_raw.lower() != "und":
            norm = normalize_lang_code(lang_raw)
            if norm:
                tagged_subs.append({
                    "id": tid,
                    "lang_raw": lang_raw.lower(),
                    "lang_norm": norm,
                    "name": name,
                    "codec": codec
                })
                continue

        # No usable tag
        untagged_ids.append(tid)

    return tagged_subs, untagged_ids


def extract_track_to_srt(mkvextract_path: Path, mkv_path: Path, tid: int, out_path: Path) -> bool:
    """
    Extract a single track to SRT; returns True if succeeded.
    """
    try:
        subprocess.run(
            [str(mkvextract_path), "tracks", str(mkv_path), f"{tid}:{out_path}"],
            check=True,
            text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to extract track {tid}: {e}")
        return False


def choose_mkv_subtitle_interactive(
    mkv_path: Path,
    mkvmerge_path: Path,
    mkvextract_path: Path,
    tagged_subs: list[dict],
    untagged_ids: list[int],
    allowed_src_langs_ordered: list[str],
) -> tuple[str | None, int | None, Path | None, list[Path]]:
    """
    Build a candidate list and let the user choose.
    - For untagged tracks: extract and detect language up front.
    - For tagged tracks: show tag only; extract/validate only if chosen.
    - Filters to allowed languages (already excludes target language).
    Returns: (lang_norm, track_id, srt_path, cleanup_paths)
    """
    cleanup_paths: list[Path] = []
    candidates: list[dict] = []

    # Detect untagged languages by extracting them
    if untagged_ids:
        print("🔎 Detecting languages for untagged subtitle tracks...")
    for tid in untagged_ids:
        temp_srt = mkv_path.with_name(f"{mkv_path.stem}_track{tid}.srt")
        if extract_track_to_srt(mkvextract_path, mkv_path, tid, temp_srt):
            cleanup_paths.append(temp_srt)
            lang = detect_language_from_srt(temp_srt)
            if lang:
                norm = normalize_lang_code(lang)
                print(f"   🔍 Track {tid}: Detected language {lang}")
                candidates.append({
                    "id": tid,
                    "lang_norm": norm,
                    "lang_raw": lang,
                    "source": "untagged+detected",
                    "name": None,
                    "codec": "SRT",
                    "srt_path": temp_srt
                })
            else:
                print(f"   ⚠️ Track {tid}: Could not detect language")
        else:
            print(f"   ⚠️ Skipping untagged track {tid}: extraction failed")

    # Add tagged tracks (not yet extracted)
    for t in tagged_subs:
        candidates.append({
            "id": t["id"],
            "lang_norm": t["lang_norm"],
            "lang_raw": t["lang_raw"],
            "source": "tagged",
            "name": t.get("name"),
            "codec": t.get("codec"),
            "srt_path": None
        })

    # Filter to allowed languages
    allowed = filter_allowed_candidates(candidates, allowed_src_langs_ordered)
    if not allowed:
        print("❌ No subtitle tracks match the allowed languages.")
        return None, None, None, cleanup_paths

    # Present menu
    print("\n📋 Available subtitle tracks:\n")
    print("   # | Track ID | Lang (raw→norm) | Source            | Name")
    print("  ---+----------+-----------------+-------------------+---------------------------")
    for idx, c in enumerate(allowed, start=1):
        name = c["name"] or "-"
        raw = c["lang_raw"] or "?"
        norm = c["lang_norm"] or "?"
        lang_display = f"{raw}→{norm}" if raw != norm else raw
        print(f"  {idx:>2} | {c['id']:^8} | {lang_display:^15} | {c['source']:<17} | {name}")

    # Ask user to choose
    while True:
        choice = input("\n➡️  Choose subtitle track by number (or press Enter to cancel): ").strip()
        if choice == "":
            print("⚠️ Selection cancelled by user.")
            return None, None, None, cleanup_paths
        if not choice.isdigit():
            print("   ⚠️ Please enter a valid number.")
            continue
        i = int(choice)
        if 1 <= i <= len(allowed):
            selected = allowed[i - 1]
            break
        print("   ⚠️ Choice out of range.")

    # If tagged, extract now and validate
    if selected["source"] == "tagged":
        out_srt = mkv_path.with_name(f"{mkv_path.stem}_track{selected['id']}.srt")
        if extract_track_to_srt(mkvextract_path, mkv_path, selected["id"], out_srt):
            cleanup_paths.append(out_srt)
            lang = detect_language_from_srt(out_srt)
            if lang:
                norm = normalize_lang_code(lang)
                print(f"   ✅ Extracted and validated track {selected['id']} (detected: {lang})")
                return norm, selected["id"], out_srt, cleanup_paths
            else:
                print(f"   ❌ Language detection failed for extracted track {selected['id']}")
                return None, None, None, cleanup_paths
        else:
            print(f"   ❌ Extraction failed for track {selected['id']}")
            return None, None, None, cleanup_paths

    # Already extracted/detected
    return selected["lang_norm"], selected["id"], selected["srt_path"], cleanup_paths
    

def select_mkv_subtitle(
    mkv_path: Path,
    mkvmerge_path: Path,
    mkvextract_path: Path,
    allowed_src_langs_ordered: list[str],
) -> tuple[str | None, int | None, Path | None, list[Path]]:
    """
    High-level selection strategy:
    - Probe tags.
    - Fast-path: if all tracks are tagged, pick the highest-priority allowed language:
        * If exactly one track → auto-select it (extract + validate).
        * If multiple tracks → interactive, restricted to those tracks.
    - If any untagged tracks exist → interactive with full candidate list.
    Returns: (src_lang_norm, track_id, srt_path, cleanup_paths)
    """
    cleanup_paths: list[Path] = []  # Always initialise at top

    tagged, untagged_ids = probe_mkv_subtitles(mkvmerge_path, mkv_path)

    # --- Fast-path: all tagged, no untagged ---
    if tagged and not untagged_ids:
        for pref_lang in allowed_src_langs_ordered:
            matches = filter_allowed_candidates(tagged, [pref_lang])
            if not matches:
                continue

            if len(matches) == 1:
                choice = matches[0]
                print(f"📦 MKV — auto-selected tagged subtitle track {choice['id']} "
                      f"({choice['lang_norm']}) based on priority.")
                out_srt = mkv_path.with_name(f"{mkv_path.stem}_track{choice['id']}.srt")
                if extract_track_to_srt(mkvextract_path, mkv_path, choice["id"], out_srt):
                    cleanup_paths.append(out_srt)
                    lang = detect_language_from_srt(out_srt)
                    if lang:
                        norm = normalize_lang_code(lang)
                        print(f"   ✅ Extracted and validated track {choice['id']} (detected: {lang})")
                        return norm, choice["id"], out_srt, cleanup_paths
                    else:
                        print(f"   ❌ Language detection failed for extracted track {choice['id']}")
                        return None, None, None, cleanup_paths
                else:
                    print(f"   ❌ Extraction failed for track {choice['id']}")
                    return None, None, None, cleanup_paths

            else:
                # Multiple tracks for the highest available priority language → interactive
                print("ℹ️ Multiple tracks found for highest available priority language — asking user.")
                lang_norm, track_id, srt_path, extra_cleanup = choose_mkv_subtitle_interactive(
                    mkv_path,
                    mkvmerge_path,
                    mkvextract_path,
                    tagged_subs=matches,      # restrict to ambiguous set
                    untagged_ids=[],          # none, all tagged here
                    allowed_src_langs_ordered=allowed_src_langs_ordered,
                )
                cleanup_paths.extend(extra_cleanup)
                return lang_norm, track_id, srt_path, cleanup_paths

        # No tagged tracks match any allowed language
        print("❌ No tagged tracks match the allowed languages.")
        return None, None, None, cleanup_paths

    # --- Interactive path: any untagged exist ---
    lang_norm, track_id, srt_path, extra_cleanup = choose_mkv_subtitle_interactive(
        mkv_path,
        mkvmerge_path,
        mkvextract_path,
        tagged_subs=tagged,
        untagged_ids=untagged_ids,
        allowed_src_langs_ordered=allowed_src_langs_ordered,
    )
    cleanup_paths.extend(extra_cleanup)
    return lang_norm, track_id, srt_path, cleanup_paths


# ============================================================
# REGISTRY HELPERS
# ============================================================

def install():
    """
    Install SubVerter: dependencies, config, registry entries.
    Writes context menu entries under HKCU for current user only.
    Uses 'py' launcher for future-proofing.
    """
    print("\n🛠️ SubVerter Installation Started")

    # --- Dependency installation ---
    def python_is_user_writable():
        try:
            test_path = site.getsitepackages()[0]
        except AttributeError:
            test_path = site.getusersitepackages()
        return os.access(test_path, os.W_OK)

    req_file = Path(__file__).parent / "requirements.txt"
    print("\n📦 Installing Python dependencies...")
    if not python_is_user_writable():
        print("   ⚠️ This Python environment may require Administrator rights for pip installs.")
        print("      If installation fails, re-run as admin or use: pip install --user -r requirements.txt")

    if req_file.exists():
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], check=True)
            print("   ✅ Dependencies installed from requirements.txt")
        except subprocess.CalledProcessError:
            print("   ❌ Failed to install dependencies. Please run manually:")
            print(f"      pip install -r {req_file}")
            return
    else:
        print("   ⚠️ requirements.txt not found. Skipping dependency installation.")

    # --- Registry setup ---
    print("\n🧠 Adding context menu entries to registry (current user only)...")

    create_default_config()
    cfg = load_config()

    extensions = [".srt", ".mkv"]
    for ext in extensions:
        key_path = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter"
        cmd_key_path = key_path + r"\\command"

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "Translate with SubVerter")
            print(f"   📝 Created key: HKCU\\{key_path}")
            print(f"      ↳ Set default value: 'SubVerter'")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key_path) as key:
            command = f'cmd /k py "{Path(__file__).resolve()}" "%1"'
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
            print(f"   📝 Created key: HKCU\\{cmd_key_path}")
            print(f"      ↳ Set default value: {command}")

    # --- Config validation ---
    print("\n⚙️ Config setup")
    validate_config(cfg)

    # --- Final summary ---
    print("\n🎉 SubVerter installation complete!")
    print("   ✔ Dependencies installed")
    print("   ✔ Config created/validated")
    print("   ✔ Registry entries added for .srt and .mkv (current user only)")
    print("ℹ️ If the new context menu entry doesn’t appear immediately, try logging off/on or restarting Explorer.")


def uninstall():
    """
    Remove right-click context menu entries for .srt and .mkv files.
    """
    print("\n🧹 SubVerter Uninstallation Started\n")

    # --- Registry cleanup ---
    extensions = [".srt", ".mkv"]
    print("🗑️ Removing registry keys...\n")
    for ext in extensions:
        cmd_key = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter\\command"
        main_key = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter"

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, cmd_key)
            print(f"   🗑️ Deleted key: HKCU\\{cmd_key}")
        except FileNotFoundError:
            print(f"   ⚠️ Key not found: HKCU\\{cmd_key}")

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, main_key)
            print(f"   🗑️ Deleted key: HKCU\\{main_key}")
        except FileNotFoundError:
            print(f"   ⚠️ Key not found: HKCU\\{main_key}")

    print("\n✅ Uninstallation complete — registry entries removed for .srt and .mkv\n")


# ============================================================
# PIPELINE
# ============================================================

def run_pipeline(files):
    """
    Main processing pipeline for SubVerter.
    - SRT: detect language, verify allowed, and proceed.
    - MKV: select a single subtitle track using tagged preference or interactive choice,
           extract to SRT, validate language, and proceed.
    """
    cfg = load_config()

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

        src_lang = None
        working_srt: Path | None = None
        cleanup_paths: list[Path] = []  # Always initialise

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
                    print(f"❌ mkvtoolnix not found (expected mkvmerge at {mkvmerge_path}, mkvextract at {mkvextract_path})")
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

            # --- Post-selection summary ---
            print(f"\n🎯 Target language: {cfg['target_language']}")
            print("➡️ Step 1: Parse and block build")
            print("➡️ Step 2: Send to model backend")
            print("➡️ Step 3: Validate and reformat")
            print("💾 Step 4: Write final SRT to output folder\n")

        finally:
            # Cleanup temps — keep the chosen working file if you plan to use it
            if cleanup_paths:
                for p in cleanup_paths:
                    if p != working_srt:
                        p.unlink(missing_ok=True)


# ============================================================
# CLI ENTRY POINT
# ============================================================

def main():
    """
    Parse command-line arguments and run the appropriate action.
    """
    parser = argparse.ArgumentParser(
        description="SubVerter — Context-aware subtitle translation using AI"
    )
    parser.add_argument(
        "files", nargs="*", type=Path,
        help="One or more .srt or .mkv files to process"
    )
    parser.add_argument(
        "--install", action="store_true",
        help="Install right-click context menu entry"
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Uninstall right-click context menu entry"
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

    run_pipeline(args.files)


if __name__ == "__main__":
    main()
    print("\n✅ Done. You can close this window.")