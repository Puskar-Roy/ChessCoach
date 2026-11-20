@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo ChessCoach needs a Python 3.12 virtual environment. Follow the setup steps in README.md.
  pause
  exit /b 1
)
if not exist "app\node_modules\electron\dist\electron.exe" (
  echo Installing desktop dependencies...
  call npm --prefix app ci
  if errorlevel 1 (
    echo Setup failed. Check Node.js 22.12+ and your internet connection, then try again.
    pause
    exit /b 1
  )
)
start "" "app\node_modules\electron\dist\electron.exe" "app"
