param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildVenv = Join-Path $ProjectRoot ".venv-build"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$BrowserRoot = Join-Path $BuildVenv "Lib\site-packages\playwright\driver\package\.local-browsers"

Set-Location $ProjectRoot

if ($Clean) {
    if (Test-Path (Join-Path $ProjectRoot "build")) {
        Remove-Item -LiteralPath (Join-Path $ProjectRoot "build") -Recurse -Force
    }
    if (Test-Path (Join-Path $ProjectRoot "dist")) {
        Remove-Item -LiteralPath (Join-Path $ProjectRoot "dist") -Recurse -Force
    }
}

if (-not (Test-Path $BuildPython)) {
    py -3 -m venv $BuildVenv
}

& $BuildPython -m pip install --upgrade pip
& $BuildPython -m pip install -r requirements-build.txt

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
& $BuildPython -m playwright install chromium

if (-not (Test-Path $BrowserRoot)) {
    throw "Playwright Chromium was not installed into the build environment."
}

& $BuildPython -m PyInstaller --noconfirm --clean ARGUS.spec

$Output = Join-Path $ProjectRoot "dist\ARGUS"
if (-not (Test-Path (Join-Path $Output "ARGUS.exe"))) {
    throw "ARGUS.exe was not created."
}
if (-not (Test-Path (Join-Path $Output "argus-engine.exe"))) {
    throw "argus-engine.exe was not created."
}

Write-Host "PASS: portable build created at $Output"
