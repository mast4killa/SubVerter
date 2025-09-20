#!/usr/bin/env python3
from __future__ import annotations

"""
Copilot Web automation client for SubVerter.

Uses Playwright to log in to https://copilot.microsoft.com and send prompts.
Stores session cookies in cfg/copilot_storage.json for reuse.
"""

import sys
import time
import random
from pathlib import Path
from typing import Optional

from playwright.sync_api import TimeoutError, sync_playwright, Page  # ✅ sync API

COPILOT_URL = "https://copilot.microsoft.com"
STORAGE_FILE = Path(__file__).parent.parent / "cfg" / "copilot_storage.json"

# Selector for the Copilot prompt text box.
# If Microsoft changes the DOM, update this in ONE place.
PROMPT_SELECTOR = "textarea#userInput"


class CopilotClient:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.storage_file = STORAGE_FILE
        # For persistent browser mode
        self._p = None
        self._browser = None
        self._context = None
        self._page: Optional[Page] = None

    def login_and_save_session(self) -> None:
        """
        Launch browser for manual login and save session cookies.
        """
        print("\n🔐 Launching Copilot login browser...")
        print("   ➡️ Please log in with your Microsoft account.")
        print("   ✅ Choose 'Stay signed in' when prompted.")
        print("   🧠 Switch mode to 'Smart (GPT‑5)' at the bottom.")
        print("   💬 Wait until the Copilot chat interface is fully loaded.")
        input("   ⏳ Press Enter here once you're logged in...")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto(COPILOT_URL)
                input("   ✅ Press Enter again to save session and close browser...")
                context.storage_state(path=str(self.storage_file))
                browser.close()
        except Exception as e:
            print(f"\n❌ Failed to complete login flow: {e}")
            print("   ⚠️ Try again or check your browser/network setup.")
            return

        print(f"\n💾 Session saved to: {self.storage_file}")

    # ------------------------------
    # Persistent session helpers
    # ------------------------------
    def launch(self, verbosity: int = 0) -> None:
        """
        Launch browser and open Copilot once (persistent browser mode).
        Also switches to Smart (GPT‑5) mode once per session.
        """
        if not self.storage_file.exists():
            raise FileNotFoundError(
                f"No saved session found at {self.storage_file}. "
                f"Run login_and_save_session() first."
            )
        if self._browser:
            return  # already launched

        try:
            self._p = sync_playwright().start()
            self._browser = self._p.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(storage_state=str(self.storage_file))
            self._page = self._context.new_page()
            if verbosity >= 3:
                print(f"➡️ Navigating to {COPILOT_URL}")
            self._page.goto(COPILOT_URL)
            if verbosity >= 3:
                print("⏳ Waiting for chat textarea…")
            self._page.wait_for_selector(PROMPT_SELECTOR, timeout=15000)
        except Exception as e:
            print(f"\n❌ Failed to launch Copilot browser: {e}")
            print("   ⚠️ Check your session file, network, or Playwright setup.")
            self.close()
            raise

        # Switch to Smart mode once per session
        if verbosity >= 3:
            print("🧠 Switching to Smart (GPT‑5) mode…")
        human_submit(
            self._page,
            "",  # no intro text
            "",  # no subtitles text
            "Tab,Tab,Enter,ArrowDown,ArrowDown,Enter,Shift+Tab,Shift+Tab"
        )
        human_delay(0.5, 1.2)

    def start_new_topic(self, verbosity: int = 0) -> None:
        """
        Use keyboard navigation to trigger 'New topic' in the Copilot UI.
        This is used in persistent browser mode so each translation block
        starts with a clean chat thread.

        Adjust the key sequence if Copilot changes its UI tab order.
        """
        if not self._page:
            raise RuntimeError("CopilotClient not launched. Call launch() first.")

        if verbosity >= 3:
            print("🆕 Starting a new chat topic via keyboard…")

        # Navigate to the "New topic" button and activate it using keyboard only.
        human_submit(
            self._page,
            "",  # no intro text
            "",  # no subtitles text
            "Tab,Tab,Tab,Enter,Enter"  # example: navigate to toolbar, press Enter twice
        )

        human_delay(0.5, 1.2)
        self._page.wait_for_selector(PROMPT_SELECTOR, timeout=10000)

    def send_prompt(self, prompt_text: str, timeout_sec: int = 30, verbosity: int = 0) -> Optional[str]:
        """
        Send a prompt in the already-open Copilot tab (persistent browser mode).
        """
        if not self._page:
            raise RuntimeError("CopilotClient not launched. Call launch() first.")

        if verbosity >= 3:
            print(f"⌨️ Entering prompt: {prompt_text!r}")
        self._page.fill(PROMPT_SELECTOR, prompt_text)
        self._page.keyboard.press("Enter")

        if verbosity >= 3:
            print("⏳ Waiting for assistant's reply container…")
        try:
            self._page.wait_for_selector('div[data-content="ai-message"]', timeout=timeout_sec * 1000)
        except TimeoutError:
            print("⚠️ Timed out waiting for assistant reply.")
            return None

        messages = self._page.query_selector_all('div[data-content="ai-message"]')
        if not messages:
            print("⚠️ No assistant reply received or found.")
            return None
        last_msg = messages[-1]

        if verbosity >= 3:
            print("⏳ Waiting for reply content to stabilise…")

        stable_count = 0
        last_html = ""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            current_html = last_msg.inner_html()
            if current_html == last_html:
                stable_count += 1
            else:
                stable_count = 0
                last_html = current_html
            if stable_count >= 2:
                break
            time.sleep(1)

        spans = last_msg.query_selector_all("span.font-ligatures-none.whitespace-pre-wrap")
        texts = [span.inner_text().strip() for span in spans if span.inner_text().strip()]
        if verbosity >= 3:
            print(f"📄 Found {len(texts)} spans in assistant's reply.")
        return "\n".join(texts).strip() if texts else None

    def close(self) -> None:
        """
        Close browser and Playwright (persistent browser mode).
        """
        try:
            if self._browser:
                self._browser.close()
        except Exception as e:
            print(f"⚠️ Failed to close browser: {e}")
        try:
            if self._p:
                self._p.stop()
        except Exception as e:
            print(f"⚠️ Failed to stop Playwright: {e}")
        self._browser = None
        self._context = None
        self._page = None
        self._p = None

    # ------------------------------
    # One-shot mode (current behaviour)
    # ------------------------------
    def run_prompt(self, prompt_text: str, timeout_sec: int = 30, verbosity: int = 0) -> Optional[str]:
        """
        Send a prompt to Copilot and return the full text response from the assistant only.
        Uses the <div data-content="ai-message"> container to detect when the reply is complete.
        """
        if not self.storage_file.exists():
            raise FileNotFoundError(
                f"No saved session found at {self.storage_file}. "
                f"Run login_and_save_session() first."
            )

        headless_mode = self.headless
        if verbosity >= 2:
            headless_mode = False
            print("🪟 Verbose mode: launching visible browser window for debugging…")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless_mode)
                context = browser.new_context(storage_state=str(self.storage_file))
                page = context.new_page()

                if verbosity >= 3:
                    print(f"➡️ Navigating to {COPILOT_URL}")
                page.goto(COPILOT_URL)

                if verbosity >= 3:
                    print("⏳ Waiting for chat textarea…")
                page.wait_for_selector(PROMPT_SELECTOR, timeout=15000)

                # Small human-like pause before interacting
                human_delay(0.8, 1.5)

                # 1) Switch to Smart mode (adjust sequence to match actual UI tab order)
                if verbosity >= 3:
                    print("🧠 Switching to Smart (GPT‑5) mode…")
                human_submit(
                    page,
                    "",  # no intro text
                    "",  # no subtitles text
                    "Tab,Tab,Enter,ArrowDown,ArrowDown,Enter,Shift+Tab,Shift+Tab"
                )
                human_delay(0.5, 1.2)

                # 2) Enter prompt and submit via keyboard
                if verbosity >= 3:
                    print(f"⌨️ Entering prompt via human_submit: {prompt_text!r}")
                human_submit(
                    page,
                    "",              # intro_text
                    prompt_text,     # subtitles_text
                    "Tab,Tab,Tab,Tab,Enter"  # navigate to submit button and press Enter
                )

                if verbosity >= 3:
                    print("⏳ Waiting for assistant's reply container…")
                page.wait_for_selector('div[data-content="ai-message"]', timeout=timeout_sec * 1000)

                messages = page.query_selector_all('div[data-content="ai-message"]')
                if not messages:
                    print("⚠️ No assistant reply received or found.")
                    return None
                last_msg = messages[-1]

                if verbosity >= 3:
                    print("⏳ Waiting for reply content to stabilise…")

                stable_count = 0
                last_html = ""
                start_time = time.time()
                while time.time() - start_time < timeout_sec:
                    current_html = last_msg.inner_html()
                    if current_html == last_html:
                        stable_count += 1
                    else:
                        stable_count = 0
                        last_html = current_html
                    if stable_count >= 2:
                        break
                    time.sleep(1)

                spans = last_msg.query_selector_all("span.font-ligatures-none.whitespace-pre-wrap")
                texts = [span.inner_text().strip() for span in spans if span.inner_text().strip()]
                if verbosity >= 3:
                    print(f"📄 Found {len(texts)} spans in assistant's reply.")

                response_text = "\n".join(texts)
                browser.close()
                return response_text.strip() if response_text else None
        except TimeoutError:
            print("⚠️ Timed out waiting for assistant reply.")
            return None
        except Exception as e:
            print(f"\n❌ Failed to run prompt: {e}")
            print("   ⚠️ Check your session file, network, or Playwright setup.")
            return None


# ================
# HUMAN-LIKE DELAY
# ================
def human_delay(short_range=(0.3, 3.0), long_range=(3.0, 8.0), long_chance=0.1):
    """
    Pause for a human-like random delay.

    - short_range: tuple(min, max) seconds for most pauses, or two floats
    - long_range: tuple(min, max) seconds for occasional longer pauses, or two floats
    - long_chance: probability (0-1) of using a long pause
    """
    # Normalise to tuples if floats are passed
    if not isinstance(short_range, (tuple, list)):
        short_range = (float(short_range), float(long_range))
        long_range = (3.0, 8.0)  # reset to default long range if floats were given
    elif not isinstance(long_range, (tuple, list)):
        long_range = (float(long_range), float(long_range))

    if random.random() < long_chance:
        delay = random.uniform(*long_range)
    else:
        delay = random.uniform(*short_range)

    time.sleep(delay)


# ======================
# HUMAN-LIKE MOUSE CLICK
# ======================
def human_click(page: Page, selector: str, move_steps=25):
    """
    Simulate a human-like mouse click:
    1. Start from a random point on a random edge of the viewport.
    2. Glide to a random point inside the target element (not dead-center).
    3. Click.
    4. Glide away to a random point on a random edge.

    - selector: CSS selector for the element to click
    - move_steps: number of interpolation steps for the glide
    """
    try:
        element = page.query_selector(selector)
        if not element:
            raise ValueError(f"Element {selector} not found on page.")
        bounds = element.bounding_box()
        if not bounds:
            raise ValueError(f"Element {selector} is not visible or has no bounding box.")
    except Exception as e:
        print(f"❌ Failed to locate or prepare element for click: {e}")
        return

    # Random click point inside element (±20% from center)
    target_x = bounds["x"] + bounds["width"] / 2 + random.uniform(-bounds["width"] * 0.2, bounds["width"] * 0.2)
    target_y = bounds["y"] + bounds["height"] / 2 + random.uniform(-bounds["height"] * 0.2, bounds["height"] * 0.2)

    viewport = page.viewport_size

    def random_edge_point():
        edge = random.choice(["top", "bottom", "left", "right"])
        if edge == "top":
            return random.uniform(0, viewport["width"]), 0
        elif edge == "bottom":
            return random.uniform(0, viewport["width"]), viewport["height"]
        elif edge == "left":
            return 0, random.uniform(0, viewport["height"])
        else:
            return viewport["width"], random.uniform(0, viewport["height"])

    # Start from random edge
    start_x, start_y = random_edge_point()
    page.mouse.move(start_x, start_y)

    # Glide to target with jitter
    for i in range(move_steps):
        nx = start_x + (target_x - start_x) * (i + 1) / move_steps + random.uniform(-2, 2)
        ny = start_y + (target_y - start_y) * (i + 1) / move_steps + random.uniform(-2, 2)
        page.mouse.move(nx, ny)
        time.sleep(random.uniform(0.01, 0.03))

    # Click
    page.mouse.click(target_x, target_y)

    # Glide away to random edge
    leave_x, leave_y = random_edge_point()
    for i in range(move_steps):
        nx = target_x + (leave_x - target_x) * (i + 1) / move_steps + random.uniform(-2, 2)
        ny = target_y + (leave_y - target_y) * (i + 1) / move_steps + random.uniform(-2, 2)
        page.mouse.move(nx, ny)
        time.sleep(random.uniform(0.01, 0.03))


# =====================
# FLEXIBLE HUMAN SUBMIT
# =====================
def human_submit(page: Page, intro_text: str, subtitles_text: str, sequence: str):
    """
    Paste intro + subtitles into the prompt box, then execute a sequence of key presses.

    - page: Playwright Page object
    - intro_text: string for the intro (e.g., "Translate the following subtitles:")
    - subtitles_text: the actual subtitles text
    - sequence: comma-separated string of Playwright key names
                Example: "Tab,Tab,Enter,ArrowDown,Enter"
                Valid key names: https://playwright.dev/docs/api/class-keyboard#keyboard-press
    """
    try:
        # Ensure prompt box is focused (check by selector)
        is_focused = page.evaluate(f"""
            document.activeElement === document.querySelector("{PROMPT_SELECTOR}")
        """)
        if not is_focused:
            page.focus(PROMPT_SELECTOR)
    except Exception as e:
        print(f"❌ Failed to focus prompt box: {e}")
        return

    try:
        # Paste intro + subtitles
        page.fill(PROMPT_SELECTOR, intro_text + "\n" + subtitles_text)
    except Exception as e:
        print(f"❌ Failed to fill prompt box: {e}")
        return

    human_delay(0.8, 2.0)

    # Execute sequence exactly as given
    for action in sequence.split(","):
        key = action.strip()
        if key:
            page.keyboard.press(key)
            human_delay(0.2, 0.6)
            
# Optional CLI entry point
if __name__ == "__main__":
    client = CopilotClient(headless=False)
    client.login_and_save_session()