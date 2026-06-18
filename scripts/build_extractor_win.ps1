#
# ROS Metadata Extractor — Windows Packager
# Compiles the application into a standalone .exe file.
# Run this script in a PowerShell terminal on a Windows host machine.
#
# Config (all optional, via environment):
#   $env:LLAMACPP_MODEL_PATH = "C:\path\to\model.gguf"   # overrides .env / default
#   $env:BUNDLE_MODEL = "0"                               # build lean (no baked-in model)
#

Write-Host "==================================================" -ForegroundColor Green
Write-Host "     Starting ROS Extractor Windows Build         " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

# Run from the repo root regardless of where the script is invoked.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# 1. Setup virtual environment and install requirements
Write-Host "Installing/updating build dependencies..." -ForegroundColor Cyan
& .venv\Scripts\pip.exe install --upgrade pyinstaller pywebview openpyxl pymupdf pillow

# 2. Resolve the GGUF model path: env var -> .env -> default -> prompt.
$DefaultModel = "$env:USERPROFILE\.ollama\models\blobs\sha256-dde5aa3fc5ffc17176b5e8bdc82f587b24b2678c6c66101bf7da77af9f7ccdff"
$ModelPath = $env:LLAMACPP_MODEL_PATH
if ([string]::IsNullOrWhiteSpace($ModelPath) -and (Test-Path ".env")) {
    $line = Select-String -Path ".env" -Pattern '^LLAMACPP_MODEL_PATH=' | Select-Object -First 1
    if ($line) { $ModelPath = ($line.Line -replace '^LLAMACPP_MODEL_PATH=', '').Trim() }
}
if ([string]::IsNullOrWhiteSpace($ModelPath)) { $ModelPath = $DefaultModel }

# Bundle the model into the exe folder? Default yes (offline, self-contained).
# Set $env:BUNDLE_MODEL = "0" for a lean build (model configured at runtime).
$BundleModel = $env:BUNDLE_MODEL
if ([string]::IsNullOrWhiteSpace($BundleModel)) { $BundleModel = "1" }

$ModelArgs = @()
if ($BundleModel -eq "1") {
    if (-not (Test-Path $ModelPath)) {
        Write-Host "Warning: Local GGUF model not found at $ModelPath" -ForegroundColor Yellow
        $ModelPath = Read-Host "Enter the absolute path to your GGUF model file (or Ctrl+C and re-run with BUNDLE_MODEL=0)"
        if (-not (Test-Path $ModelPath)) {
            Write-Host "Error: Model path is invalid. Aborting build." -ForegroundColor Red
            Exit 1
        }
    }
    Write-Host "Bundling model: $ModelPath" -ForegroundColor Cyan
    $ModelArgs = @("--add-data", "${ModelPath};data/model.gguf")
} else {
    Write-Host "Lean build: model will NOT be bundled (configure one at runtime)." -ForegroundColor Cyan
}

# 3. App icon (.ico) — generate from the logo if it is missing (needs Pillow).
$IconPath = "data\logos\app_icon.ico"
if (-not (Test-Path $IconPath) -and (Test-Path "data\logos\logo_emblem.png")) {
    Write-Host "Building app icon from data\logos\logo_emblem.png ..." -ForegroundColor Cyan
    & .venv\Scripts\python.exe -c "from PIL import Image; im=Image.open('data/logos/logo_emblem.png').convert('RGBA'); s=max(im.size); c=Image.new('RGBA',(s,s),(0,0,0,0)); c.paste(im,((s-im.width)//2,(s-im.height)//2),im); c.save('data/logos/app_icon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
}
$IconArgs = @()
if (Test-Path $IconPath) { $IconArgs = @("--icon", $IconPath) }

# 4. Compile the application using PyInstaller (splat the conditional args).
Write-Host "Running PyInstaller..." -ForegroundColor Cyan
$piArgs = @(
    "--name", "ROS_Extractor",
    "--noconsole",
    "--noconfirm",
    "--collect-all", "nicegui",
    "--collect-all", "llama_cpp",
    "--paths", "."
) + $IconArgs + @("--add-data", "data/logos;data/logos") + $ModelArgs + @("app/desktop_extractor.py")

& .venv\Scripts\pyinstaller.exe @piArgs

Write-Host "==================================================" -ForegroundColor Green
Write-Host "Build Successful! Standalone executable created at:" -ForegroundColor Green
Write-Host "  dist\ROS_Extractor\ROS_Extractor.exe" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host "To package this folder into a single one-click installer, download Inno Setup" -ForegroundColor Cyan
Write-Host "(https://jrsoftware.org/isinfo.php) and compile a standard Setup script." -ForegroundColor Cyan
