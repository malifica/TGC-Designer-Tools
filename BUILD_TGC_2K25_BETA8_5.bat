@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem TGC_BETA8_5_HILLSHADE_DEFAULTS_V1
cd /d "%~dp0"
set "TGC_BUILD_PY=%CD%\.venv_local_osm\Scripts\python.exe"
if not exist "%TGC_BUILD_PY%" set "TGC_BUILD_PY=C:\TGC-Designer-Tools\.venv_local_osm\Scripts\python.exe"
if not exist "%TGC_BUILD_PY%" (
  echo ERROR: Existing .venv_local_osm Python was not found.
  exit /b 1
)
"%TGC_BUILD_PY%" "%~dp0BUILD_TGC_2K25_BETA8_5.py" "%CD%"
exit /b %errorlevel%
