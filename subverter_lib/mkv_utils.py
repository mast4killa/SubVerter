#!/usr/bin/env python3
from __future__ import annotations

"""
MKV subtitle utilities for SubVerter.

Provides:
- Probing MKV files for subtitle tracks.
- Extracting subtitle tracks to SRT.
- Interactive selection of subtitle tracks, including language detection
  for untagged tracks.
- High-level selection strategy with auto-selection when possible.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from subverter_lib.lang_utils import normalize_lang_code, filter_allowed_candidates
from subverter_lib.srt_utils import detect_language_from_srt


def probe_mkv_subtitles(
    mkvmerge_path: Path,
    mkv_path: Path
) -> tuple[list[dict[str, Any]], list[int]]:
    """
    Use mkvmerge -J to read all tracks and split into:
    - tagged_subs: list of dicts {id, lang_raw, lang_norm, name, codec}
    - untagged_ids: list of subtitle track IDs with no usable language tag
    """
    try:
        # First attempt: keep stderr separate so JSON stays clean
        result_json = subprocess.run(
            [str(mkvmerge_path), "-J", str(mkv_path)],
            capture_output=True,
            text=True,
            check=True
        )
        try:
            info = json.loads(result_json.stdout)
        except json.JSONDecodeError:
            # Retry with merged stderr for diagnostics
            print("❌ mkvmerge output was not valid JSON. Retrying with merged stderr for diagnostics...")
            debug_run = subprocess.run(
                [str(mkvmerge_path), "-J", str(mkv_path)],
                capture_output=True,
                text=True,
                check=False,
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

    tagged_subs: list[dict[str, Any]] = []
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


def extract_track_to_srt(
    mkvextract_path: Path,
    mkv_path: Path,
    tid: int,
    out_path: Path
) -> bool:
    """
    Extract a single track to SRT.

    Args:
        mkvextract_path: Path to mkvextract executable.
        mkv_path: Path to MKV file.
        tid: Track ID to extract.
        out_path: Destination SRT file path.

    Returns:
        True if extraction succeeded, False otherwise.
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
    tagged_subs: list[dict[str, Any]],
    untagged_ids: list[int],
    allowed_src_langs_ordered: list[str],
) -> tuple[str | None, int | None, Path | None, list[Path]]:
    """
    Build a candidate list and let the user choose.

    - For untagged tracks: extract and detect language up front.
    - For tagged tracks: show tag only; extract/validate only if chosen.
    - Filters to allowed languages (already excludes target language).

    Returns:
        (lang_norm, track_id, srt_path, cleanup_paths)
    """
    cleanup_paths: list[Path] = []
    candidates: list[dict[str, Any]] = []

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
    High-level selection strategy for choosing a subtitle track from an MKV.

    Strategy:
        1. Probe tags using mkvmerge.
        2. Fast-path: if all tracks are tagged, pick the highest-priority allowed language:
            - If exactly one track matches → auto-select it (extract + validate).
            - If multiple tracks match → interactive selection, restricted to those tracks.
        3. If any untagged tracks exist → interactive selection with full candidate list.

    Args:
        mkv_path: Path to the MKV file.
        mkvmerge_path: Path to mkvmerge executable.
        mkvextract_path: Path to mkvextract executable.
        allowed_src_langs_ordered: List of allowed source languages in priority order.

    Returns:
        (src_lang_norm, track_id, srt_path, cleanup_paths)
    """
    cleanup_paths: list[Path] = []

    tagged, untagged_ids = probe_mkv_subtitles(mkvmerge_path, mkv_path)

    # --- Fast-path: all tagged, no untagged ---
    if tagged and not untagged_ids:
        for pref_lang in allowed_src_langs_ordered:
            matches = filter_allowed_candidates(tagged, [pref_lang])
            if not matches:
                continue

            if len(matches) == 1:
                choice = matches[0]
                print(
                    f"📦 MKV — auto-selected tagged subtitle track {choice['id']} "
                    f"({choice['lang_norm']}) based on priority."
                )
                out_srt = mkv_path.with_name(f"{mkv_path.stem}_track{choice['id']}.srt")
                if extract_track_to_srt(mkvextract_path, mkv_path, choice["id"], out_srt):
                    cleanup_paths.append(out_srt)
                    lang = detect_language_from_srt(out_srt)
                    if lang:
                        norm = normalize_lang_code(lang)
                        print(
                            f"   ✅ Extracted and validated track {choice['id']} "
                            f"(detected: {lang})"
                        )
                        return norm, choice["id"], out_srt, cleanup_paths
                    else:
                        print(
                            f"   ❌ Language detection failed for extracted track {choice['id']}"
                        )
                        return None, None, None, cleanup_paths
                else:
                    print(f"   ❌ Extraction failed for track {choice['id']}")
                    return None, None, None, cleanup_paths

            # Multiple tracks for the highest available priority language → interactive
            print(
                "ℹ️ Multiple tracks found for highest available priority language — asking user."
            )
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