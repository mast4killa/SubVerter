# SubVerter  
**Context‑aware subtitle translation using AI**

---

## Overview
SubVerter is a command‑line tool for translating `.srt` and `.mkv` subtitles with high fidelity.  
Uses **context‑aware prompts** and supports multiple backends, including **Copilot Web** (via Playwright automation) and **Ollama** (local models).   
The pipeline preserves subtitle structure, inline tags, and timing, while leveraging rolling summaries and surrounding context for better translation quality.

---

## Key Features
- **Multi‑format input**: Direct `.srt` translation or `.mkv` subtitle extraction.
- **Context‑aware translation**: Uses previous/next subtitles and rolling summaries.
- **Multiple backends**: Copilot Web, Ollama, with stubs for OpenAI, Azure, Hugging Face.
- **Automatic or interactive track selection** for MKV files.
- **Preserves formatting**: Inline tags, line breaks, and timing remain intact.
- **Configurable**: All settings in `cfg/config.json` — paths, languages, backend, limits.
- **Windows integration**: Optional right‑click context menu for `.srt` and `.mkv`.

### ✅ Tested & Supported
- **Backends**:
  - **Copilot Web** → fully tested and works reliably.
  - **Mistral** → functional, but current model struggles to follow the prompt accurately.
- **Operating systems**:
  - Only tested and supported on **Windows**.


---

## Installation / Uninstallation (Windows only)

**Install**  
```bash
python subverter.py --install
```  
Adds right‑click menu for `.srt`/`.mkv`, installs dependencies, default config, and Playwright browser.

**Uninstall**  
```bash
python subverter.py --uninstall
```  
Removes right‑click menu (keeps config and dependencies).

---

## Usage
Translate one or more files:
```bash
python subverter.py movie.srt
python subverter.py episode.mkv -vv
```

Verbosity levels:
- `-v` → basic debug info
- `-vv` → prompt/response previews
- `-vvv` → full prompt/response dumps

---

## Configuration
Edit `cfg/config.json` to set:
- `target_language` — ISO 639‑1/2 code for output language.
- `allowed_src_langs_ordered` — list of allowed source languages in priority order.
- Backend settings (`backend`, `model`, `ollama_path`, etc.).
- Character limits for prompts and summaries.

---

## Project Structure
```
subverter.py                  # CLI entry point
subverter_lib/
  config_manager.py           # Load/save/validate config
  installers.py               # Install/uninstall logic
  pipeline.py                 # Main translation workflow
  copilot_client.py           # Copilot Web automation
  lang_utils.py               # Language normalization/filtering
  llm_adapter.py              # Backend abstraction
  mkv_utils.py                # MKV probing/extraction
  prompt_utils.py             # Prompt building
  reformat.py                 # Subtitle reformatting
  srt_utils.py                # SRT parsing/context building
  translator.py               # Translation logic
cfg/
  config.json                 # User config
  copilot_storage.json        # Copilot Web session state
requirements.txt
README.md
```

---

## Example Workflow
1. **Load config** → validate paths, languages.
2. **For each file**:
   - `.srt`: detect language, verify allowed.
   - `.mkv`: select/extract subtitle track.
3. **Parse SRT** → split into blocks under char limit.
4. **Build prompt** → include rolling summary + context.
5. **Send to backend** → get translations.
6. **Reformat** → enforce width/line limits.
7. **Write output** → `<basename>.<target_lang>.srt`.

---

## License
MIT License — see LICENSE file for details.