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

from playwright.sync_api import sync_playwright, Page  # ✅ sync API

COPILOT_URL = "https://copilot.microsoft.com"
STORAGE_FILE = Path(__file__).parent.parent / "cfg" / "copilot_storage.json"


class CopilotClient:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.storage_file = STORAGE_FILE

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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(COPILOT_URL)
            input("   ✅ Press Enter again to save session and close browser...")
            context.storage_state(path=str(self.storage_file))
            browser.close()

        print(f"\n💾 Session saved to: {self.storage_file}")

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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless_mode)
            context = browser.new_context(storage_state=str(self.storage_file))
            page = context.new_page()

            if verbosity >= 3:
                print(f"➡️ Navigating to {COPILOT_URL}")
            page.goto(COPILOT_URL)

            if verbosity >= 3:
                print("⏳ Waiting for chat textarea…")
            page.wait_for_selector("textarea", timeout=15000)

            if verbosity >= 3:
                print(f"⌨️ Filling prompt: {prompt_text!r}")
            page.fill("textarea", prompt_text)
            page.keyboard.press("Enter")

            if verbosity >= 3:
                print("⏳ Waiting for assistant's reply container…")

            # Wait for a new ai-message container to appear
            page.wait_for_selector('div[data-content="ai-message"]', timeout=timeout_sec * 1000)

            # Get the last ai-message container (assistant's reply)
            messages = page.query_selector_all('div[data-content="ai-message"]')
            last_msg = messages[-1]

            if verbosity >= 3:
                print("⏳ Waiting for reply content to stabilise…")

            # Wait until the HTML inside the container stops changing
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

                if stable_count >= 2:  # unchanged for ~2 seconds
                    break

                time.sleep(1)

            # Extract only the spans inside this message
            spans = last_msg.query_selector_all("span.font-ligatures-none.whitespace-pre-wrap")
            texts = [span.inner_text().strip() for span in spans if span.inner_text().strip()]

            if verbosity >= 3:
                print(f"📄 Found {len(texts)} spans in assistant's reply.")

            response_text = "\n".join(texts)

            browser.close()
            return response_text.strip() if response_text else None


# ==============================
# HUMAN-LIKE DELAY (sync version)
# ==============================
def human_delay(short_range=(0.3, 3.0), long_range=(3.0, 8.0), long_chance=0.1):
    """
    Pause for a human-like random delay.
    - short_range: tuple(min, max) seconds for most pauses
    - long_range: tuple(min, max) seconds for occasional longer pauses
    - long_chance: probability (0-1) of using a long pause
    """
    if random.random() < long_chance:
        delay = random.uniform(*long_range)
    else:
        delay = random.uniform(*short_range)
    time.sleep(delay)


# ==============================
# HUMAN-LIKE MOUSE CLICK (sync)
# ==============================
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
    element = page.query_selector(selector)
    bounds = element.bounding_box()
    if not bounds:
        raise ValueError(f"Element {selector} not found or not visible")

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


# ==============================
# FLEXIBLE HUMAN SUBMIT (sync)
# ==============================

# Selector for the Copilot prompt text box.
# If Microsoft changes the DOM, update this in ONE place.
# Tip: You can inspect the page in your browser to find the new selector.
PROMPT_SELECTOR = "textarea.prompt-input"

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
    # Ensure prompt box is focused (check by selector)
    is_focused = page.evaluate(f"""
        document.activeElement === document.querySelector("{PROMPT_SELECTOR}")
    """)
    if not is_focused:
        page.focus(PROMPT_SELECTOR)

    # Paste intro + subtitles
    page.fill(PROMPT_SELECTOR, intro_text + "\n" + subtitles_text)
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