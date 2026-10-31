@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PY=%CD%\.venv_local_osm\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\TGC-Designer-Tools\.venv_local_osm\Scripts\python.exe"
if not exist "%PY%" (
  echo ERROR: Existing .venv_local_osm Python was not found.
  exit /b 1
)
"%PY%" "%~dp0BUILD_TGC_2K25_BETA8_2.py" "%CD%"
exit /b %errorlevel%
