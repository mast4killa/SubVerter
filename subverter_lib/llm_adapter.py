#!/usr/bin/env python3
from __future__ import annotations

"""
Model-agnostic LLM adapter for SubVerter.

Provides a unified interface to send prompts to different LLM backends.
Currently supports:
- Ollama (local models, e.g., Mistral)
- Copilot Web (Playwright automation)

Stub methods are included for:
- OpenAI API
- Azure OpenAI
- Hugging Face Inference API
"""

import json
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMConfig:
    """
    Configuration for the LLMAdapter.

    Attributes:
        backend: Backend type ("ollama", "copilot_web", "openai", "azure", "huggingface").
        model: Model name or ID (e.g., "mistral" for Ollama; ignored for copilot_web).
        ollama_path: Path to the Ollama executable (if backend is "ollama").
        timeout_sec: Timeout in seconds for model calls.
    """
    backend: str
    model: str
    ollama_path: Optional[str] = None
    timeout_sec: int = 120


class LLMAdapter:
    """
    Adapter class to communicate with different LLM backends.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate(self, prompt: str, verbosity: int = 0) -> Optional[str]:
        """
        Send a prompt to the configured backend and return the generated text.

        Args:
            prompt: The input text to send to the model.
            verbosity: Verbosity level for optional debug output.

        Returns:
            The model's output as a string, or None if the call failed.
        """
        backend = self.config.backend.lower()

        if verbosity >= 1:
            print(f"   🛈 [LLMAdapter] Using backend '{backend}' with model '{self.config.model}'")

        if backend == "ollama":
            return self._call_ollama(prompt, verbosity=verbosity)
        if backend == "copilot_web":
            return self._call_copilot_web(prompt, verbosity=verbosity)
        if backend == "openai":
            return self._call_openai(prompt)
        if backend == "azure":
            return self._call_azure(prompt)
        if backend == "huggingface":
            return self._call_hf(prompt)

        print(f"❌ Unsupported backend: {self.config.backend}")
        return None


    # ------------------------------
    # Ollama backend
    # ------------------------------
    def _call_ollama(self, prompt: str, verbosity: int = 0) -> Optional[str]:
        """
        Call a local Ollama model with the given prompt.
        """
        if not self.config.ollama_path:
            print("❌ Ollama path not set in config.")
            return None

        if verbosity >= 3:
            print("\n      🛈 [LLMAdapter] Full prompt being sent to Ollama:\n" + prompt + "\n")
        elif verbosity == 2:
            lines = prompt.splitlines()
            preview = "\n".join(lines[:5] + (["..."] if len(lines) > 10 else []) + lines[-5:])
            print("\n      🛈 [LLMAdapter] Prompt preview:\n" + preview + "\n")

        try:
            proc = subprocess.run(
                [str(self.config.ollama_path), "run", self.config.model],
                input=prompt,
                text=True,
                encoding="utf-8",   # ✅ Force UTF-8 so all Unicode chars are supported
                capture_output=True,
                timeout=self.config.timeout_sec,
                check=True,
            )

            out = proc.stdout.strip()
            if not out:
                return None

            if verbosity >= 3:
                print("      🛈 [LLMAdapter] Full raw output from Ollama:\n" + out + "\n")
            elif verbosity == 2:
                out_lines = out.splitlines()
                preview_out = "\n".join(out_lines[:5] + (["..."] if len(out_lines) > 10 else []) + out_lines[-5:])
                print("      🛈 [LLMAdapter] Output preview:\n" + preview_out + "\n")

            # If output looks like JSON, try to parse and extract "response"
            if out.startswith("{") and out.endswith("}"):
                try:
                    obj = json.loads(out)
                    if isinstance(obj, dict) and "response" in obj:
                        return str(obj["response"]).strip()
                except json.JSONDecodeError:
                    pass

            return out

        except subprocess.TimeoutExpired:
            print(f"❌ Ollama call timed out after {self.config.timeout_sec}s")
            return None
        except subprocess.CalledProcessError as e:
            print(f"❌ Ollama call failed: {e}\nSTDERR:\n{e.stderr}")
            return None

    # ------------------------------
    # Copilot Web backend
    # ------------------------------
    def _call_copilot_web(self, prompt: str, verbosity: int = 0) -> Optional[str]:
        """
        Call Copilot Web (https://copilot.microsoft.com) via Playwright automation.
        Requires subverter_lib/copilot_client.py and a saved login session.
        """
        try:
            from subverter_lib.copilot_client import CopilotClient
        except ImportError:
            print("❌ CopilotClient module not found. Ensure subverter_lib/copilot_client.py exists.")
            return None

        if verbosity >= 3:
            print("\n      🛈 [LLMAdapter] Full prompt being sent to Copilot Web:\n" + prompt + "\n")
        elif verbosity == 2:
            lines = prompt.splitlines()
            preview = "\n".join(lines[:5] + (["..."] if len(lines) > 10 else []) + lines[-5:])
            print("\n      🛈 [LLMAdapter] Prompt preview:\n" + preview + "\n")

        client = CopilotClient(headless=(verbosity < 2))
        try:
            resp = client.run_prompt(prompt, timeout_sec=self.config.timeout_sec, verbosity=verbosity)
            if verbosity >= 3 and resp:
                print("      🛈 [LLMAdapter] Full raw output from Copilot Web:\n" + resp + "\n")
            elif verbosity == 2 and resp:
                out_lines = resp.splitlines()
                preview_out = "\n".join(out_lines[:5] + (["..."] if len(out_lines) > 10 else []) + out_lines[-5:])
                print("      🛈 [LLMAdapter] Output preview:\n" + preview_out + "\n")
            return resp
        except FileNotFoundError as e:
            print(f"❌ {e}")
            print("   ↳ Run CopilotClient.login_and_save_session() first to create a session.")
            return None
        except Exception as e:
            print(f"❌ Copilot Web call failed: {e}")
            return None


    # ------------------------------
    # OpenAI backend (stub)
    # ------------------------------
    def _call_openai(self, prompt: str) -> Optional[str]:
        """
        Call an OpenAI model with the given prompt.
        Requires `openai` Python package and API key in environment.
        """
        print("ℹ️ OpenAI backend not yet implemented.")
        # Example skeleton:
        # import openai
        # openai.api_key = os.getenv("OPENAI_API_KEY")
        # resp = openai.ChatCompletion.create(
        #     model=self.config.model,
        #     messages=[{"role": "user", "content": prompt}],
        #     temperature=0.2,
        # )
        # return resp.choices[0].message["content"].strip()
        # When implemented, ensure UTF-8 encoding for any subprocess or file I/O
        return None

    # ------------------------------
    # Azure OpenAI backend (stub)
    # ------------------------------
    def _call_azure(self, prompt: str) -> Optional[str]:
        """
        Call an Azure OpenAI deployment with the given prompt.
        Requires `openai` Python package and Azure endpoint/key in environment.
        """
        print("ℹ️ Azure OpenAI backend not yet implemented.")
        # Example skeleton:
        # import openai
        # openai.api_type = "azure"
        # openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
        # openai.api_version = "2023-05-15"
        # openai.api_key = os.getenv("AZURE_OPENAI_KEY")
        # resp = openai.ChatCompletion.create(
        #     engine=self.config.model,
        #     messages=[{"role": "user", "content": prompt}],
        #     temperature=0.2,
        # )
        # return resp.choices[0].message["content"].strip()
        # When implemented, ensure UTF-8 encoding for any subprocess or file I/O
        return None

    # ------------------------------
    # Hugging Face backend (stub)
    # ------------------------------
    def _call_hf(self, prompt: str) -> Optional[str]:
        """
        Call a Hugging Face Inference API model with the given prompt.
        Requires `huggingface_hub` or `requests` and API token in environment.
        """
        print("ℹ️ Hugging Face backend not yet implemented.")
        # Example skeleton:
        # from huggingface_hub import InferenceClient
        # client = InferenceClient(token=os.getenv("HF_API_TOKEN"))
        # resp = client.text_generation(model=self.config.model, prompt=prompt, max_new_tokens=500)
        # return resp.generated_text.strip()
        # When implemented, ensure UTF-8 encoding for any subprocess or file I/O
        return None