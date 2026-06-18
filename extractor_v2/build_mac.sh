#!/usr/bin/env bash
#
# ROS Metadata Extractor V2 — macOS Packager
# Builds dist/ROS_Extractor_V2.app and a drag-and-drop .dmg installer.
#
# Config (all optional, via environment):
#   LLAMACPP_MODEL_PATH=/path/to/model.gguf   # overrides .env / built-in default
#   BUNDLE_MODEL=0                             # lean build (do NOT bake the model in)
#   BUNDLE_ID=lk.roscribe.extractor.v2         # macOS bundle identifier
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="ROS Extractor System"
echo "=================================================="
echo "      Starting ${APP_NAME} macOS Build            "
echo "=================================================="

# 1. Resolve the GGUF model path: env var -> .env -> built-in default.
DEFAULT_MODEL="/Users/laksh/.ollama/models/blobs/sha256-dde5aa3fc5ffc17176b5e8bdc82f587b24b2678c6c66101bf7da77af9f7ccdff"
MODEL_PATH="${LLAMACPP_MODEL_PATH:-}"
if [ -z "$MODEL_PATH" ] && [ -f ".env" ]; then
    MODEL_PATH="$(grep -E '^LLAMACPP_MODEL_PATH=' .env | head -1 | cut -d= -f2- | xargs || true)"
fi
MODEL_PATH="${MODEL_PATH:-$DEFAULT_MODEL}"

BUNDLE_MODEL="${BUNDLE_MODEL:-1}"
BUNDLE_ID="${BUNDLE_ID:-lk.roscribe.extractor.v2}"

MODEL_ARG=()
if [ "$BUNDLE_MODEL" = "1" ]; then
    if [ ! -f "$MODEL_PATH" ]; then
        echo "Error: GGUF model not found at: $MODEL_PATH"
        echo "  -> set LLAMACPP_MODEL_PATH, add it to .env, or build lean with BUNDLE_MODEL=0"
        exit 1
    fi
    echo "Bundling model: $MODEL_PATH"
    MODEL_ARG=(--add-data "$MODEL_PATH:data/model.gguf")
else
    echo "Lean build: model will NOT be bundled (configure one at runtime)."
fi

# 2. App icon (.icns) — generate from the logo if missing.
ICON_PATH="data/logos/app_icon.icns"
if [ ! -f "$ICON_PATH" ] && [ -f "data/logos/logo_emblem.png" ]; then
    echo "Building app icon from data/logos/logo_emblem.png ..."
    ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
    for s in 16 32 64 128 256 512; do
        sips -z "$s" "$s"     data/logos/logo_emblem.png --out "$ICONSET/icon_${s}x${s}.png"    >/dev/null 2>&1 || true
        d=$((s*2)); sips -z "$d" "$d" data/logos/logo_emblem.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
    done
    iconutil -c icns "$ICONSET" -o "$ICON_PATH" || ICON_PATH=""
fi
ICON_ARG=()
[ -n "$ICON_PATH" ] && [ -f "$ICON_PATH" ] && ICON_ARG=(--icon "$ICON_PATH")

echo "Checking build requirements..."
.venv/bin/pip install --upgrade pyinstaller dmgbuild pywebview openpyxl pymupdf

# 3. PyInstaller (the V2 entry point is extractor_v2/app.py).
echo "Running PyInstaller..."
.venv/bin/pyinstaller \
    --name "$APP_NAME" \
    --windowed \
    --noconfirm \
    --collect-all nicegui \
    --collect-all llama_cpp \
    --paths . \
    --osx-bundle-identifier "$BUNDLE_ID" \
    ${ICON_ARG[@]+"${ICON_ARG[@]}"} \
    --add-data "data/logos:data/logos" \
    ${MODEL_ARG[@]+"${MODEL_ARG[@]}"} \
    extractor_v2/app.py

echo "Build complete: dist/${APP_NAME}.app"
xattr -cr "dist/${APP_NAME}.app" || true

# 4. DMG installer.
echo "Generating DMG installer..."
rm -f "dist/${APP_NAME}.dmg"
.venv/bin/dmgbuild -s extractor_v2/dmg_settings.py "ROS Extractor System" "dist/${APP_NAME}.dmg"

echo "=================================================="
echo "Build Successful! DMG installer created at:"
echo "  dist/${APP_NAME}.dmg"
echo "=================================================="
