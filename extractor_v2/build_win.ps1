#
# ROS Extractor System — Windows Packager
# Compiles "dist\ROS Extractor System\ROS Extractor System.exe". Run in PowerShell on Windows.
#
# Config (all optional, via environment):
#   $env:LLAMACPP_MODEL_PATH = "C:\path\to\model.gguf"   # overrides .env / default
#   $env:BUNDLE_MODEL = "0"                               # lean build (no baked-in model)
#

Write-Host "==================================================" -ForegroundColor Green
Write-Host "     Starting ROS Extractor System Windows Build   " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$AppName = "ROS Extractor System"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
    py -3 -m venv .venv
}

Write-Host "Installing/updating build + runtime dependencies..." -ForegroundColor Cyan
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\pip.exe install --upgrade pyinstaller pywebview pillow nicegui python-dotenv openpyxl pymupdf pydantic openai anthropic
# llama-cpp-python from the prebuilt CPU wheel (no Visual C++ Build Tools / no compile).
# NVIDIA GPU? replace 'cpu' below with your CUDA tag, e.g. 'cu124'.
& .venv\Scripts\pip.exe install --upgrade --prefer-binary --timeout 60 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python

# 1. Resolve model path: env -> .env -> default -> prompt.
$DefaultModel = "$env:USERPROFILE\.ollama\models\blobs\sha256-dde5aa3fc5ffc17176b5e8bdc82f587b24b2678c6c66101bf7da77af9f7ccdff"
$ModelPath = $env:LLAMACPP_MODEL_PATH
if ([string]::IsNullOrWhiteSpace($ModelPath) -and (Test-Path ".env")) {
    $line = Select-String -Path ".env" -Pattern '^LLAMACPP_MODEL_PATH=' | Select-Object -First 1
    if ($line) { $ModelPath = ($line.Line -replace '^LLAMACPP_MODEL_PATH=', '').Trim() }
}
if ([string]::IsNullOrWhiteSpace($ModelPath)) { $ModelPath = $DefaultModel }

$BundleModel = $env:BUNDLE_MODEL
if ([string]::IsNullOrWhiteSpace($BundleModel)) { $BundleModel = "1" }

$ModelArgs = @()
if ($BundleModel -eq "1") {
    if (-not (Test-Path $ModelPath)) {
        Write-Host "Warning: GGUF model not found at $ModelPath" -ForegroundColor Yellow
        $ModelPath = Read-Host "Enter the absolute path to your GGUF model (or Ctrl+C and re-run with BUNDLE_MODEL=0)"
        if (-not (Test-Path $ModelPath)) { Write-Host "Invalid path. Aborting." -ForegroundColor Red; Exit 1 }
    }
    Write-Host "Bundling model: $ModelPath" -ForegroundColor Cyan
    $ModelArgs = @("--add-data", "${ModelPath};data/model.gguf")
} else {
    Write-Host "Lean build: model will NOT be bundled." -ForegroundColor Cyan
}

# 2. App icon (.ico) — generate from the logo if missing (needs Pillow).
$IconPath = "data\logos\app_icon.ico"
if (-not (Test-Path $IconPath) -and (Test-Path "data\logos\logo_emblem.png")) {
    Write-Host "Building app icon from logo_emblem.png ..." -ForegroundColor Cyan
    & .venv\Scripts\python.exe -c "from PIL import Image; im=Image.open('data/logos/logo_emblem.png').convert('RGBA'); s=max(im.size); c=Image.new('RGBA',(s,s),(0,0,0,0)); c.paste(im,((s-im.width)//2,(s-im.height)//2),im); c.save('data/logos/app_icon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
}
$IconArgs = @()
if (Test-Path $IconPath) { $IconArgs = @("--icon", $IconPath) }

# 3. Compile (V2 entry point is extractor_v2/app.py).
Write-Host "Running PyInstaller..." -ForegroundColor Cyan
$piArgs = @(
    "--name", $AppName,
    "--noconsole",
    "--noconfirm",
    "--collect-all", "nicegui",
    "--collect-all", "llama_cpp",
    "--paths", "."
) + $IconArgs + @("--add-data", "data/logos;data/logos") + $ModelArgs + @("extractor_v2/app.py")

& .venv\Scripts\pyinstaller.exe @piArgs

Write-Host "==================================================" -ForegroundColor Green
Write-Host "Build Successful! Executable at:" -ForegroundColor Green
Write-Host "  dist\$AppName\$AppName.exe" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
