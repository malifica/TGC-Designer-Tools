@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv_local_osm\Scripts\python.exe" (
  echo ERROR: Activate or create the existing TGC Python environment first.
  echo See BUILD_WINDOWS.md for dependency setup.
  pause
  exit /b 1
)
".venv_local_osm\Scripts\python.exe" "BUILD_TGC_2K25_BETA7.py" "%CD%"
if errorlevel 1 (
  echo BUILD FAILED. The previous EXE was not replaced unless a verified build completed.
  pause
  exit /b 1
)
pause
exit /b 0
