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
from typing import Any, Optional

# Path to the configuration file (stored alongside this script)
CONFIG_PATH: Path = Path(__file__).with_name("config.json")

# Mapping of common ISO 639-2 codes to ISO 639-1 equivalents
ISO639_MAP: dict[str, str] = {
    "eng": "en", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "spa": "es",
    "ita": "it", "nld": "nl", "dut": "nl", "por": "pt", "rus": "ru", "jpn": "ja",
    "zho": "zh", "chi": "zh", "ara": "ar", "tur": "tr", "pol": "pl", "swe": "sv",
    "nor": "no", "fin": "fi", "dan": "da", "ces": "cs", "cze": "cs", "ell": "el",
    "gre": "el", "kor": "ko"
}

# Default configuration values
DEFAULT_CONFIG: dict[str, Any] = {
    "_note": "Language codes follow ISO 639-1 or ISO 639-2. See: https://codeberg.org/mbunkus/mkvtoolnix/wiki/Languages-in-Matroska-and-MKVToolNix",
    "target_language": "nl",
    "ollama_path": str(Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"),
    "mkvextract_path": Path("C:/Program Files/MKVToolNix/mkvextract.exe"),
    "mkvmerge_path": Path("C:/Program Files/MKVToolNix/mkvmerge.exe"),
    "model": "mistral",
    "char_limit": 2500,
    "allowed_src_langs_ordered": ["en", "fr", "de", "es", "it"],
}


def create_default_config() -> None:
    """
    Create config.json with default values if it doesn't exist.
    Paths are converted to strings for JSON serialisation.
    """
    if CONFIG_PATH.exists():
        print(f"   ⚠️ Config already exists at {CONFIG_PATH}")
        return

    def stringify_paths(obj):
        if isinstance(obj, dict):
            return {k: stringify_paths(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [stringify_paths(v) for v in obj]
        if isinstance(obj, Path):
            return str(obj)
        return obj

    clean_config = stringify_paths(DEFAULT_CONFIG)
    CONFIG_PATH.write_text(json.dumps(clean_config, indent=2), encoding="utf-8")
    print(f"   ✅ Created default config at: {CONFIG_PATH}")
    print("   📄 Default values:")
    for key, value in clean_config.items():
        print(f"      {key}: {value}")


def ensure_keys(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure all expected keys from DEFAULT_CONFIG are present in cfg.
    Missing keys are added with default values.
    """
    updated = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = value
            updated = True
    if updated:
        save_config(cfg, updated=True)
    return cfg


def normalize_paths(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Convert any path strings in cfg to Path objects for consistency.
    """
    for key in ("ollama_path", "mkvextract_path", "mkvmerge_path"):
        if key in cfg and isinstance(cfg[key], str):
            cfg[key] = Path(cfg[key])
    return cfg


def load_config() -> dict[str, Any]:
    """
    Load config.json, creating it if missing.
    Ensures all keys exist and normalizes paths.
    """
    if not CONFIG_PATH.exists():
        create_default_config()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = ensure_keys(cfg)
    cfg = normalize_paths(cfg)
    return cfg


def save_config(cfg: dict[str, Any], updated: bool = True) -> None:
    """
    Save updated config to disk.
    Converts Path objects back to strings for JSON serialisation.
    """
    serialisable_cfg = {
        k: str(v) if isinstance(v, Path) else v
        for k, v in cfg.items()
    }
    CONFIG_PATH.write_text(json.dumps(serialisable_cfg, indent=2), encoding="utf-8")
    if updated:
        print(f"\n💾 Updated config at {CONFIG_PATH}")
    else:
        print(f"\n💾 Config re-saved (no changes) at {CONFIG_PATH}")


def normalize_lang_code(code: Optional[str]) -> Optional[str]:
    """
    Normalize a language code to ISO 639-1 when possible.

    Accepts:
    - 2-letter codes (e.g., 'en')
    - 3-letter codes (e.g., 'eng')
    - IETF tags with region/script (e.g., 'en-US', 'eng-Latn')

    Returns:
        2-letter code if recognized, otherwise None.
    """
    if not code:
        return None
    c = code.lower().strip()
    base = c.split("-")[0]  # strip region/script
    if len(base) == 2:
        return base
    if len(base) == 3:
        mapped = ISO639_MAP.get(base)
        return mapped if mapped and len(mapped) == 2 else None
    return None


def is_valid_language_code(code: str) -> bool:
    """
    Check if a language code is valid (ISO 639-1 or ISO 639-2).
    """
    valid_langs = {
        "en", "fr", "de", "es", "it", "nl", "pt", "ru", "ja", "zh", "ar", "tr", "pl", "sv", "no", "fi", "da", "cs", "el", "ko",
        "eng", "fra", "deu", "spa", "ita", "nld", "por", "rus", "jpn", "zho", "ara", "tur", "pol", "swe", "nor", "fin", "dan", "ces", "ell", "kor"
    }
    return code.lower() in valid_langs


def validate_config(cfg: dict[str, Any], interactive: bool = True) -> bool:
    """
    Validate config values and save only if changes were made.

    Checks performed:
    1. Tool paths (ollama, mkvextract, mkvmerge) must exist.
    2. Target language must be valid after normalization.
    3. Allowed source languages must be valid after normalization.

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
                new_path = input(f"         Enter correct path for {tool_key} (or leave blank to skip): ").strip()
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
        print(f"         ℹ️ Normalized allowed_src_langs_ordered: {raw_allowed} -> {normalized_allowed}")
        cfg["allowed_src_langs_ordered"] = normalized_allowed
        updated = True

    # --- Save only if updated ---
    if interactive:
        if updated:
            save_config(cfg, updated=True)
            print(f"   ✅ Configuration valid and saved")
        else:
            print(f"   ✅ Configuration valid (no changes)")

    return ok