import json
from pathlib import Path
from typing import Any

CONFIG_PATH: Path = Path(__file__).with_name("config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "_note": "Language codes follow ISO 639-1 or 639-2. See: https://codeberg.org/mbunkus/mkvtoolnix/wiki/Languages-in-Matroska-and-MKVToolNix",
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
    """
    if CONFIG_PATH.exists():
        print(f"   ⚠️ Config already exists at {CONFIG_PATH}")
        return

    def stringify_paths(obj):
        if isinstance(obj, dict):
            return {k: stringify_paths(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [stringify_paths(v) for v in obj]
        elif isinstance(obj, Path):
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
    If any are missing, fill them in and save the updated config.
    """
    updated = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = value
            updated = True
    if updated:
        save_config(cfg)
    return cfg


def normalise_paths(cfg: dict[str, Any]) -> dict[str, Any]:
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
    Ensures all keys exist and normalises paths.
    """
    if not CONFIG_PATH.exists():
        create_default_config()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = ensure_keys(cfg)
    cfg = normalise_paths(cfg)
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
    """
    ok = True
    updated = False

    print("   🔍 Validating configuration...")

    # --- Tool path checks ---
    print("      🛠️ Tool paths:")
    for tool_key in ("ollama_path", "mkvextract_path", "mkvmerge_path"):
        path = cfg.get(tool_key)
        if isinstance(path, str):
            path = Path(path)
        if not path.exists():
            print(f"         ❌ {tool_key} not found at {path}")
            ok = False
            if interactive:
                new_path = input(f"         Enter correct path for {tool_key} (or leave blank to skip): ").strip()
                if new_path:
                    cfg[tool_key] = Path(new_path)
                    if Path(new_path).exists():
                        print(f"         ✅ Updated {tool_key} to {new_path}")
                        ok = True
                        updated = True
                    else:
                        print(f"         ❌ Still not found at {new_path}")
        else:
            print(f"         ✅ {tool_key}: {path}")

    # --- Language code checks ---
    print("      🌐 Language codes:")
    if not is_valid_language_code(cfg.get("target_language", "")):
        print(f"         ⚠️ Invalid target_language: {cfg.get('target_language')}")
        ok = False
    for lang in cfg.get("allowed_src_langs_ordered", []):
        if not is_valid_language_code(lang):
            print(f"         ⚠️ Invalid allowed_src_langs_ordered entry: {lang}")
            ok = False

    # --- Save only if updated ---
    if interactive:
        if updated:
            save_config(cfg)
            print(f"   💾 Updated config at {CONFIG_PATH} (✅ Configuration valid)")
        else:
            print(f"   ℹ️ No changes made to config — keeping existing file (✅ Configuration valid)")

    return ok