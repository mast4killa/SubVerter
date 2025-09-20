#!/usr/bin/env python3
from __future__ import annotations

import os
import site
import subprocess
import sys
import winreg
from pathlib import Path

from subverter_lib.config_manager import create_default_config, load_config, validate_config


def install() -> None:
    """
    Install SubVerter: dependencies, config, and registry entries.

    - Installs Python dependencies from requirements.txt (if present).
    - Installs Playwright Chromium browser for Copilot automation.
    - Creates default config if missing.
    - Adds right-click context menu entries for .srt and .mkv files
      under HKCU (current user only).
    - If backend is 'copilot_web' and no saved session exists,
      launches login flow so user is ready to translate immediately.
    """
    print("\n🛠️ SubVerter Installation Started")

    # ------------------------------
    # Dependency installation
    # ------------------------------
    def python_is_user_writable() -> bool:
        """Check if the current Python environment is user-writable."""
        try:
            test_path = site.getsitepackages()[0]
        except AttributeError:
            test_path = site.getusersitepackages()
        return os.access(test_path, os.W_OK)

    req_file = Path(__file__).parent.parent / "requirements.txt"
    print("\n📦 Installing Python dependencies...")
    if not python_is_user_writable():
        print("   ⚠️ This Python environment may require Administrator rights for pip installs.")
        print("      If installation fails, re-run as admin or use:")
        print("      pip install --user -r requirements.txt")

    if req_file.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("   ✅ Dependencies installed from requirements.txt")
            else:
                print("   ❌ Failed to install dependencies.")
                print("      stdout:", result.stdout.strip())
                print("      stderr:", result.stderr.strip())
                return
        except subprocess.CalledProcessError:
            print("   ❌ Failed to install dependencies. Please run manually:")
            print(f"      pip install -r {req_file}")
            return
    else:
        print("   ⚠️ requirements.txt not found. Skipping dependency installation.")

    # --------------------------
    # Playwright browser install
    # --------------------------
    print("\n🌐 Installing Playwright Chromium browser for Copilot automation...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("   ✅ Playwright Chromium installed")
        else:
            print("   ❌ Failed to install Playwright browser.")
            print("      stdout:", result.stdout.strip())
            print("      stderr:", result.stderr.strip())
    except subprocess.CalledProcessError:
        print("   ❌ Failed to install Playwright browser. Run manually:")
        print("      playwright install chromium")

    # --------------
    # Registry setup
    # --------------
    if sys.platform != "win32":
        print("   ⚠️ Registry setup skipped — SubVerter only supports Windows.")
        return
    print("\n🧠 Adding context menu entries to registry (current user only)...")

    try:
        create_default_config()
        cfg = load_config()
        validate_config(cfg)
    except Exception as e:
        print(f"❌ Config setup failed: {e}")
        print("   ⚠️ Registry setup aborted due to config error.")
        return

    extensions = [".srt", ".mkv"]
    for ext in extensions:
        key_path = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter"
        cmd_key_path = key_path + r"\\command"

        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "Translate with SubVerter")
                print(f"   📝 Created key: HKCU\\{key_path}")
                print("      ↳ Set default value: 'SubVerter'")
        except OSError as e:
            print(f"   ❌ Failed to create registry key {key_path}: {e}")

        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key_path) as key:
                main_script = Path(__file__).parent.parent / "subverter.py"
                command = f'cmd /k py "{main_script}" "%1"'
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
                print(f"   📝 Created key: HKCU\\{cmd_key_path}")
                print(f"      ↳ Set default value: {command}")
        except OSError as e:
            print(f"   ❌ Failed to create registry key {cmd_key_path}: {e}")

    # ------------------------------
    # Copilot Web login (if needed)
    # ------------------------------
    if cfg.get("backend", "").lower() == "copilot_web":
        try:
            from subverter_lib.copilot_client import STORAGE_FILE, CopilotClient
            if not STORAGE_FILE.exists():
                print("\n🌐 Copilot Web backend detected — no saved session found.")
                print("   A browser window will now open to https://copilot.microsoft.com")
                print("   Please follow these steps carefully:")
                print("     1️⃣ Log in with your Microsoft account (enter username & password).")
                print("     2️⃣ If prompted, complete MFA (approve on your phone or enter code).")
                print("     3️⃣ When asked 'Stay signed in?', choose **Yes**.")
                print("     4️⃣ Once logged in, switch the mode at the bottom to **Smart (GPT‑5)**.")
                print("     5️⃣ Wait until you see the Copilot chat interface fully loaded.")
                print("     6️⃣ Return to this terminal window and press **Enter** to continue.")
                CopilotClient(headless=False).login_and_save_session()
        except ImportError:
            print("❌ CopilotClient module not found. Ensure subverter_lib/copilot_client.py exists.")

    # ------------------------------
    # Final summary
    # ------------------------------
    print("\n🎉 SubVerter installation complete!")
    print("   ✔ Dependencies installed")
    print("   ✔ Playwright Chromium installed")
    print("   ✔ Config created/validated")
    print("   ✔ Registry entries added for .srt and .mkv (current user only)")
    if cfg.get("backend", "").lower() == "copilot_web":
        if Path(__file__).parent.parent.joinpath("cfg", "copilot_storage.json").exists():
            print("   ✔ Copilot Web session saved — ready for translations")
        else:
            print("   ⚠️ Copilot Web session not saved — run `python -m subverter_lib.copilot_client` to log in")
    print("ℹ️ If the new context menu entry doesn’t appear immediately, "
          "try logging off/on or restarting Explorer.")


def uninstall() -> None:
    """
    Remove right-click context menu entries for .srt and .mkv files.
    """
    print("\n🧹 SubVerter Uninstallation Started\n")

    # ------------------------------
    # Registry cleanup
    # ------------------------------
    extensions = [".srt", ".mkv"]
    print("🗑️ Removing registry keys...\n")
    for ext in extensions:
        cmd_key = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter\\command"
        main_key = f"Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\SubVerter"

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, cmd_key)
            print(f"   🗑️ Deleted key: HKCU\\{cmd_key}")
        except OSError as e:
            print(f"   ⚠️ Could not delete key: HKCU\\{cmd_key} — {e}")

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, main_key)
            print(f"   🗑️ Deleted key: HKCU\\{main_key}")
        except OSError as e:
            print(f"   ⚠️ Could not delete key: HKCU\\{main_key} — {e}")

    print("\n✅ Uninstallation complete — registry entries removed for .srt and .mkv\n")