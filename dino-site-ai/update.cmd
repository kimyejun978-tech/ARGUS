@echo off
setlocal
cd /d "%~dp0.."
echo [Dino AI] Pulling latest ARGUS changes...
git pull origin main
if errorlevel 1 (
  echo.
  echo Update failed. Check Git authentication or network and try again.
  pause
  exit /b 1
)
echo.
echo Update complete.
echo 1. Open chrome://extensions
echo 2. Click Reload on "Chrome Dino Site AI"
echo 3. Reload https://chrome-dino.org/ko/classic/
echo.
pause
