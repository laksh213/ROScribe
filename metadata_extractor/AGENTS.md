# Standalone Extractor Application: Developer & Agent Guide

This document is a direct handoff guide for other agentic coding assistants (e.g., Claude Code, Cursor, Windsurf) working on the standalone **ROS Metadata Extractor** desktop application.

---

## 📂 File Architecture

The standalone extractor app is built on top of the NiceGUI framework in Python and packaged via PyInstaller. The key files are located at:

* **Entry Point (App Logic):**
  * [`app/desktop_extractor.py`](file:///Users/laksh/Desktop/ROScribe/app/desktop_extractor.py) - Contains the native-mode (`native=True`) NiceGUI UI layout, uploader event handler, progress indicator, real-time table, and openpyxl Excel spreadsheet generator. Runs offline without authentication.
* **Extraction Engine:**
  * [`metadata_extractor/extractor.py`](file:///Users/laksh/Desktop/ROScribe/metadata_extractor/extractor.py) - Dispatches requests to `llamacpp`, `openai`, or `anthropic` providers. Reuses the prewarmed Llama GGUF model singleton from `src.analyze` under `_llama_guard()` lock.
  * [`metadata_extractor/models.py`](file:///Users/laksh/Desktop/ROScribe/metadata_extractor/models.py) - Holds the target Pydantic schemas (`JudgmentMetadata`, `PartyDetails`) used to structure LLM outputs.
* **Packaging Configurations & Scripts:**
  * **macOS:**
    * [`scripts/build_extractor_mac.sh`](file:///Users/laksh/Desktop/ROScribe/scripts/build_extractor_mac.sh) - Compiles the app bundle (`dist/ROS_Extractor.app`) and generates the DMG using `dmgbuild`.
    * [`scripts/dmg_extractor_settings.py`](file:///Users/laksh/Desktop/ROScribe/scripts/dmg_extractor_settings.py) - Window and icon layout for the generated DMG installer.
  * **Windows:**
    * [`scripts/build_extractor_win.ps1`](file:///Users/laksh/Desktop/ROScribe/scripts/build_extractor_win.ps1) - PowerShell script to build `ROS_Extractor.exe` on a Windows host machine.

---

## ⚙️ Environment Configuration (`.env`)

For local development or GGUF execution, the app reads settings from the `.env` file in the root:

```ini
# Provider to use: "llamacpp" for local offline GGUF, or "openai" / "anthropic"
LLM_PROVIDER=llamacpp

# Path to the local Llama/Qwen GGUF model file on disk
LLAMACPP_MODEL_PATH=/Users/laksh/.ollama/models/blobs/sha256-dde5aa3fc5ffc17176b5e8bdc82f587b24b2678c6c66101bf7da77af9f7ccdff

# GPU layers offload (-1 to auto-detect/offload where available)
LLAMACPP_GPU_LAYERS=-1

# (Optional) API Keys if utilizing cloud providers
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

> **Note:** the block above shows only the keys the extractor itself reads. The
> project's real `.env` also carries embedding/storage/context settings
> (`EMBEDDING_MODEL`, `ROSCRIBE_EMBEDDER`, `OLLAMA_NUM_CTX`, `SQLITE_PATH`,
> `CHROMA_DIR`, …). Copy the full set from the working `.env` rather than this
> snippet — `src.analyze`'s model prewarming and the bge embedder depend on them.

---

## 🛠️ Developer Commands

Ensure you are in the project root and activate the virtual environment before executing:
```bash
cd /Users/laksh/Desktop/ROScribe
source .venv/bin/activate
```

### 1. Run in Development Mode
To launch the native desktop GUI locally (without packaging):
```bash
python app/desktop_extractor.py
```

### 2. Package for macOS
Compiles `dist/ROS_Extractor.app` and creates the installer `dist/ROS_Extractor.dmg`:
```bash
./scripts/build_extractor_mac.sh
```

### 3. Package for Windows (Run on a Windows Host in PowerShell)
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\scripts\build_extractor_win.ps1
```

### Build options (env vars, both platforms)
- `LLAMACPP_MODEL_PATH=/abs/path/model.gguf` — model to bundle; resolved as env
  var → `.env` → built-in default (no longer a hardcoded user-specific path).
- `BUNDLE_MODEL=0` — **lean build**: do not bake the ~2 GB GGUF into the app. It
  then loads a model at runtime from a `.env` beside the app, the in-UI "Model or
  GGUF Path" field, or an API provider.
- `BUNDLE_ID=lk.roscribe.extractor` — macOS bundle identifier.
- App icons: `data/logos/app_icon.icns` / `app_icon.ico` (auto-generated from
  `logo_emblem.png` if absent). Direct builds also work via
  `pyinstaller ROS_Extractor.spec` (reads the same env vars).

---

## 📝 Key Implementation Details

1. **Authentication:** The desktop app runs offline as a native window, so the authentication route checker (`@ui.page` checks) is omitted. All UI is served at `/`.
2. **Model Sharing:** To avoid OOM crashes on 18GB Macs, the extractor shares the prewarmed GGUF singleton:
   * It calls `_get_llama()` from `src.analyze` to get the pre-loaded instance.
   * All decoding is wrapped under `_llama_guard()` to serialize inference requests and prevent context corruption.
3. **Reactivity:** When modifying table rows in NiceGUI, the reference must be re-assigned (`results_table.rows = list(table_rows)`) to trigger WS updates.
