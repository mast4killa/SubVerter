#!/usr/bin/env python3
from __future__ import annotations

"""
Configuration management for SubVerter.

Handles:
- Creating a default config file if missing.
- Loading and saving configuration values.
- Normalising and validating paths and language codes.
- Ensuring all required keys exist.
"""

import json
from pathlib import Path
from typing import Any

from subverter_lib.lang_utils import normalize_lang_code

# Path to the configuration file (stored in cfg/ at project root)
CONFIG_PATH = Path(__file__).parent.parent / "cfg" / "config.json"

# DEFAULT_CONFIG defines all required keys with safe defaults
DEFAULT_CONFIG: dict[str, Any] = {
    # Keep one browser window open and start a new chat per block (faster).
    # If false, launch and close a browser window for each block (slowest, but equivalent results).
    "keep_browser_alive": True,

    # Rolling summary length cap used when building prompts.
    "summary_max_chars": 500,

    "_note_target_language": (
        "Language codes follow ISO 639-1 or ISO 639-2. "
        "See: https://codeberg.org/mbunkus/mkvtoolnix/wiki/"
        "Languages-in-Matroska-and-MKVToolNix"
    ),
    "target_language": "nl",
    "allowed_src_langs_ordered": ["en", "fr", "de", "es", "it"],

    "backend": "copilot_web",
    "model": "ignored_for_copilot_web",

    "ollama_path": str(Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"),
    "mkvextract_path": Path("C:/Program Files/MKVToolNix/mkvextract.exe"),
    "mkvmerge_path": Path("C:/Program Files/MKVToolNix/mkvmerge.exe"),

    # Prompt character limit safeguard (applied to constructed prompts before sending).
    "char_limit": 2500,
}


def stringify_paths(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: stringify_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_paths(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def create_default_config() -> None:
    """
    Create config.json with default values if it doesn't exist.

    - Converts all Path objects to strings for JSON serialization.
    - Writes the config to disk at CONFIG_PATH.
    - Prints a warning if the file already exists.
    - Handles file system errors gracefully.

    Returns:
        None
    """
    if CONFIG_PATH.exists():
        print(f"   ⚠️ Config already exists at {CONFIG_PATH}")
        return

    clean_config = stringify_paths(DEFAULT_CONFIG)
    try:
        CONFIG_PATH.write_text(json.dumps(clean_config, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"   ❌ Failed to write config file: {e}")
        return

    print(f"   ✅ Created default config at: {CONFIG_PATH}")
    print("   📄 Default values:")
    for key, value in clean_config.items():
        print(f"      {key}: {value}")


def ensure_keys(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure all expected keys from DEFAULT_CONFIG are present in cfg.
    Missing keys are added with default values. If updated, the config is saved
    with all Path objects converted to strings for JSON serialization.

    Returns:
        dict[str, Any]: Updated configuration dictionary.
    """
    updated = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = value
            updated = True
    if updated:
        save_config(stringify_paths(cfg), updated=True)
    return cfg


def normalize_paths(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Convert specific config keys to Path objects for consistency.

    Only keys explicitly listed ("ollama_path", "mkvextract_path", "mkvmerge_path")
    are converted. Other path-like values remain as strings to avoid false positives.
    """
    for key in ("ollama_path", "mkvextract_path", "mkvmerge_path"):
        if key in cfg and isinstance(cfg[key], str):
            cfg[key] = Path(cfg[key])
    return cfg


def load_config() -> dict[str, Any]:
    """
    Load config.json, creating it if missing.
    Ensures all keys exist and normalizes paths.

    Returns:
        dict[str, Any]: Parsed and normalized configuration dictionary.

    Raises:
        json.JSONDecodeError: If config.json exists but is invalid.
        OSError: If reading the file fails.
    """
    if not CONFIG_PATH.exists():
        create_default_config()

    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"   ❌ Config file is corrupted: {e}")
        print(f"   ⚠️ Please fix or delete {CONFIG_PATH} and try again.")
        raise
    except OSError as e:
        print(f"   ❌ Failed to read config file: {e}")
        raise


    cfg = ensure_keys(cfg)
    cfg = normalize_paths(cfg)
    return cfg


def save_config(cfg: dict[str, Any], updated: bool = True) -> None:
    """
    Save updated config to disk.
    Converts Path objects back to strings for JSON serialization.

    Args:
        cfg (dict[str, Any]): Configuration dictionary to save.
        updated (bool): Whether the config was changed (affects print message).

    Returns:
        None
    """
    serialisable_cfg = {
        k: str(v) if isinstance(v, Path) else v for k, v in cfg.items()
    }

    try:
        CONFIG_PATH.write_text(json.dumps(serialisable_cfg, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"\n❌ Failed to save config file: {e}")
        return

    if updated:
        print(f"\n💾 Updated config at {CONFIG_PATH}")
    else:
        print(f"\n💾 Config re-saved (no changes) at {CONFIG_PATH}")


def is_valid_language_code(code: str) -> bool:
    """
    Check if a language code is valid (ISO 639-1 or ISO 639-2).
    """
    valid_langs = {
        "en", "fr", "de", "es", "it", "nl", "pt", "ru", "ja", "zh", "ar", "tr", "pl",
        "sv", "no", "fi", "da", "cs", "el", "ko",
        "eng", "fra", "deu", "spa", "ita", "nld", "por", "rus", "jpn", "zho", "ara",
        "tur", "pol", "swe", "nor", "fin", "dan", "ces", "ell", "kor",
    }
    return code.lower() in valid_langs


def validate_config(cfg: dict[str, Any], interactive: bool = True) -> bool:
    """
    Validate config values and save only if changes were made.

    Checks performed:
    1. Tool paths (ollama, mkvextract, mkvmerge) must exist.
    2. Target language must be valid after normalization.
    3. Allowed source languages must be valid after normalization.
    4. keep_browser_alive must be a boolean.
    5. summary_max_chars must be a positive integer.

    Args:
        cfg: The configuration dictionary to validate.
        interactive: If True, prompts the user to fix invalid paths.

    Returns:
        bool: True if configuration is valid, False otherwise.
    """
    ok = True
    updated = False

    print("   🔍 Validating configuration...")

    # --- Tool path checks ---
    print("      🛠️ Tool paths:")
    for tool_key in ("ollama_path", "mkvextract_path", "mkvmerge_path"):
        current_path = cfg.get(tool_key)
        if isinstance(current_path, str):
            current_path = Path(current_path)

        if not current_path or not current_path.exists():
            print(f"         ❌ {tool_key} not found at {current_path}")
            ok = False
            if interactive:
                new_path = input(
                    f"         Enter correct path for {tool_key} (or leave blank to skip): "
                ).strip()
                if new_path:
                    cfg[tool_key] = Path(new_path)
                    if Path(new_path).exists():
                        print(f"         ✅ Updated {tool_key} to {new_path}")
                        updated = True
                    else:
                        print(f"         ❌ Still not found at {new_path}")
        else:
            print(f"         ✅ {tool_key}: {current_path}")

    # --- Language code checks ---
    print("      🌐 Language codes:")

    # Target language
    raw_target = cfg.get("target_language", "")
    norm_target = normalize_lang_code(raw_target) or ""
    if not norm_target or not is_valid_language_code(norm_target):
        print(f"         ⚠️ Invalid target_language: {raw_target}")
        ok = False
    elif norm_target != raw_target:
        print(f"         ℹ️ Normalized target_language: {raw_target} -> {norm_target}")
        cfg["target_language"] = norm_target
        updated = True

    # Allowed source languages (ordered)
    raw_allowed = cfg.get("allowed_src_langs_ordered", []) or []
    normalized_allowed: list[str] = []
    for lang in raw_allowed:
        norm_lang = normalize_lang_code(lang)
        if not norm_lang or not is_valid_language_code(norm_lang):
            print(f"         ⚠️ Invalid allowed_src_langs_ordered entry: {lang}")
            ok = False
            continue
        normalized_allowed.append(norm_lang)

    if normalized_allowed != raw_allowed:
        print(
            f"         ℹ️ Normalized allowed_src_langs_ordered: "
            f"{raw_allowed} -> {normalized_allowed}"
        )
        cfg["allowed_src_langs_ordered"] = normalized_allowed
        updated = True

    # --- Context handling checks (present behaviour only) ---
    print("      🧠 Context handling:")
    keep_alive = cfg.get("keep_browser_alive", False)
    if not isinstance(keep_alive, bool):
        print(f"         ⚠️ Invalid keep_browser_alive: {keep_alive} (must be boolean)")
        ok = False
    else:
        print(f"         ✅ keep_browser_alive: {keep_alive}")

    # --- Summary max chars check ---
    summary_chars = cfg.get("summary_max_chars", 500)
    if not isinstance(summary_chars, int) or summary_chars < 0:
        print(f"         ⚠️ Invalid summary_max_chars: {summary_chars} (must be positive int)")
        ok = False
    else:
        print(f"         ✅ summary_max_chars: {summary_chars}")

    # --- Char limit check ---
    char_limit = cfg.get("char_limit", 2500)
    if not isinstance(char_limit, int) or char_limit < 0:
        print(f"         ⚠️ Invalid char_limit: {char_limit} (must be positive int)")
        ok = False
    else:
        print(f"         ✅ char_limit: {char_limit}")

    # --- Save only if updated ---
    if interactive:
        if updated:
            save_config(cfg, updated=True)
        else:
            print("   ✅ Configuration valid (no changes)")

    return ok