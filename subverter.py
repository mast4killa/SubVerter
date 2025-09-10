#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import argparse
import winreg
import subprocess
import re
from config_manager import load_config, validate_config, create_default_config


# ============================================================
# CONFIG & CONSTANTS
# ============================================================

# No constants here yet — config is loaded from config_manager.py


# ============================================================
# GENERIC HELPERS
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
                if "-->" not in line and not line.strip().isdigit():
                    text_lines.append(line.strip())
                if len(text_lines) > 50:
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

def get_mkv_sub_lang(mkv_path, mkvmerge_path, target_lang, priority_list):
    """
    Return (language_code, track_id) for the best subtitle track.
    Checks both 'language' and 'language_ietf' from mkvmerge JSON.
    Falls back to None if no usable tag is found.
    """
    import json, subprocess

    try:
        result = subprocess.run(
            [str(mkvmerge_path), "-J", str(mkv_path)],
            capture_output=True, text=True, check=True
        )
        mkv_info = json.loads(result.stdout)
    except Exception as e:
        print(f"❌ Failed to run mkvmerge: {e}")
        return None, None

    best_track = None
    best_lang = None

    for track in mkv_info.get("tracks", []):
        if track.get("type") != "subtitles":
            continue

        props = track.get("properties", {})
        lang = props.get("language")
        lang_ietf = props.get("language_ietf")

        # Prefer language_ietf if present and not 'und'
        if lang_ietf and lang_ietf.lower() != "und":
            detected_lang = lang_ietf.lower()
        elif lang and lang.lower() != "und":
            detected_lang = lang.lower()
        else:
            detected_lang = None

        if detected_lang:
            # If we have a priority list, pick the first match
            if priority_list and detected_lang in priority_list:
                return detected_lang, track["id"]
            # Otherwise, pick the first valid tag we find
            if best_track is None:
                best_track = track["id"]
                best_lang = detected_lang

    if best_track is not None:
        return best_lang, best_track

    # No usable tag found — signal to caller to fall back to langdetect
    return None, None


def extract_and_select_best_subtitle(
    mkv_path: Path,
    mkvmerge_path: Path,
    mkvextract_path: Path,
    target_lang: str,
    priority_list: list[str]
) -> tuple[str | None, int | None, Path | None]:
    """
    Select the best subtitle track from an MKV.
    1. Prefer MKV tags (language / language_ietf).
    2. Fallback to langdetect if tags missing/und.
    Returns (language_code, track_id, temp_srt_path or None).
    """
    import json, subprocess, re

    try:
        # --- Step 1: Read MKV tags ---
        result_json = subprocess.run(
            [str(mkvmerge_path), "-J", str(mkv_path)],
            capture_output=True, text=True, check=True
        )
        mkv_info = json.loads(result_json.stdout)

        tagged_tracks = []
        for track in mkv_info.get("tracks", []):
            if track.get("type") != "subtitles":
                continue
            props = track.get("properties", {})
            lang = props.get("language")
            lang_ietf = props.get("language_ietf")
            if lang_ietf and lang_ietf.lower() != "und":
                tagged_tracks.append((lang_ietf.lower(), track["id"]))
            elif lang and lang.lower() != "und":
                tagged_tracks.append((lang.lower(), track["id"]))

        # --- Step 2: If tags exist, pick best without extraction ---
        if tagged_tracks:
            # Priority match
            for pref_lang in priority_list:
                for lang, tid in tagged_tracks:
                    if lang == pref_lang:
                        return lang, tid, None
            # Fallback: first non-target
            for lang, tid in tagged_tracks:
                if lang != target_lang:
                    return lang, tid, None
            # All are target_lang → skip translation
            for lang, tid in tagged_tracks:
                if lang == target_lang:
                    print(f"⚠️ Subtitle track {tid} already in target language ({target_lang}). Skipping translation.")
                    return None, tid, None

        # --- Step 3: No usable tags → extract & detect ---
        result = subprocess.run(
            [str(mkvmerge_path), "-i", str(mkv_path)],
            capture_output=True, text=True, check=True
        )
        subtitle_tracks = []
        for line in result.stdout.splitlines():
            if "subtitles" in line.lower():
                m = re.search(r"Track ID\s+(\d+):", line)
                if m:
                    subtitle_tracks.append(int(m.group(1)))

        if not subtitle_tracks:
            print("❌ No subtitle tracks found in MKV.")
            return None, None, None

        detected = []
        for tid in subtitle_tracks:
            temp_srt = mkv_path.with_name(f"{mkv_path.stem}_track{tid}.srt")
            try:
                subprocess.run(
                    [str(mkvextract_path), "tracks", str(mkv_path), f"{tid}:{temp_srt}"],
                    check=True
                )
                lang = detect_language_from_srt(temp_srt)
                if lang:
                    print(f"🔍 Track {tid}: Detected language {lang}")
                    detected.append((lang.lower(), tid, temp_srt))
                else:
                    print(f"⚠️ Track {tid}: Could not detect language")
                    temp_srt.unlink(missing_ok=True)
            except Exception as e:
                print(f"Error extracting track {tid}: {e}")

        if not detected:
            print("❌ No detectable subtitle tracks found.")
            return None, None, None

        # Priority match
        for pref_lang in priority_list:
            for lang, tid, path in detected:
                if lang == pref_lang:
                    for _, other_tid, other_path in detected:
                        if other_tid != tid:
                            other_path.unlink(missing_ok=True)
                    return lang, tid, path

        # Fallback: first non-target
        for lang, tid, path in detected:
            if lang != target_lang:
                for _, other_tid, other_path in detected:
                    if other_tid != tid:
                        other_path.unlink(missing_ok=True)
                return lang, tid, path

        # All are target_lang → skip translation
        print(f"⚠️ All detected subtitle tracks are already in target language ({target_lang}). Skipping translation.")
        for _, _, path in detected:
            path.unlink(missing_ok=True)
        return None, None, None

    except Exception as e:
        print(f"Error during subtitle selection: {e}")
        return None, None, None


# ============================================================
# REGISTRY HELPERS
# ============================================================

def install():
    """
    Install SubVerter: dependencies, config, registry entries.
    Writes context menu entries under HKCU for current user only.
    Uses 'py' launcher for future-proofing.
    """
    import winreg
    import site
    import os

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
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "SubVerter")
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
    Requires Administrator privileges for HKCR/HKLM, but here we target HKCU.
    """
    import winreg

    print("\n🧹 SubVerter Uninstallation Started\n")

    # --- Admin check (kept from your original) ---
    try:
        test_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, "SubVerterUninstallTest")
        winreg.CloseKey(test_key)
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, "SubVerterUninstallTest")
    except PermissionError:
        print("❌ Administrator privileges required to modify registry.")
        print("🔒 Please run this script from an elevated command prompt.\n")
        return

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
    """
    from config_manager import load_config, is_valid_language_code

    cfg = load_config()
    tgt_lang = cfg["target_language"].lower()
    priority_list = cfg.get("source_language_priority", [])

    for f in files:
        print("\n" + "=" * 60)
        print(f"📂 Processing file: {f.name}")
        print("=" * 60 + "\n")

        if not f.exists():
            print(f"⚠️ Skipping missing file: {f}\n")
            continue

        src_lang = None
        temp_srt_to_cleanup = None

        # --- SRT handling ---
        if f.suffix.lower() == ".srt":
            src_lang = detect_language_from_srt(f)
            if src_lang:
                print(f"🌐 Detected source language: {src_lang}")
                if src_lang.lower() == tgt_lang:
                    print(f"⚠️ Already in target language ({cfg['target_language']}). Skipping.\n")
                    continue

        # --- MKV handling ---
        elif f.suffix.lower() == ".mkv":
            mkvmerge_path = Path(cfg["mkvmerge_path"])
            mkvextract_path = Path(cfg["mkvextract_path"])

            lang_code, track_id = get_mkv_sub_lang(
                f, mkvmerge_path, target_lang=tgt_lang, priority_list=priority_list
            )

            if lang_code:
                print(f"📦 MKV — best subtitle track {track_id} language: {lang_code}")
                if lang_code == tgt_lang:
                    print(f"⚠️ Already in target language ({tgt_lang}). Skipping.\n")
                    continue
                src_lang = lang_code
                temp_srt = Path(f"{f.stem}_temp.srt")
                try:
                    subprocess.run(
                        [str(mkvextract_path), "tracks", str(f), f"{track_id}:{temp_srt}"],
                        check=True
                    )
                    f = temp_srt
                    temp_srt_to_cleanup = temp_srt
                except FileNotFoundError:
                    print(f"❌ mkvextract not found at {mkvextract_path}\n")
                    continue
            else:
                print("📦 MKV — no language tag, extracting all tracks for detection...")
                src_lang, track_id, temp_srt = extract_and_select_best_subtitle(
                    f, mkvmerge_path, mkvextract_path, tgt_lang, priority_list
                )
                if src_lang is None:
                    if temp_srt:
                        temp_srt.unlink(missing_ok=True)
                    continue
                if temp_srt:
                    f = temp_srt
                    temp_srt_to_cleanup = temp_srt

        else:
            print("⚠️ Unsupported file type. Skipping.\n")
            continue

        # --- Post-detection ---
        if not src_lang:
            while True:
                src_lang = input("Enter source language code: ").strip()
                if is_valid_language_code(src_lang):
                    break
                print("⚠️ Invalid language code. Use ISO 639-1 or 639-2.")

        print(f"\n🎯 Target language: {cfg['target_language']}")
        print("➡️ Step 1: Parse and block build")
        print("➡️ Step 2: Send to model backend")
        print("➡️ Step 3: Validate and reformat")
        print("💾 Step 4: Write final SRT to output folder\n")

        if temp_srt_to_cleanup and temp_srt_to_cleanup.exists():
            temp_srt_to_cleanup.unlink(missing_ok=True)


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
        help="Install right-click context menu entry (dry-run by default)"
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Uninstall right-click context menu entry (dry-run by default)"
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