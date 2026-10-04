@echo off
setlocal EnableExtensions
cd /d C:\TGC-Designer-Tools

set REPO=malifica/TGC-Designer-Tools
set TAG=v0.5.0-2k25-beta4.1
set TITLE=TGC Designer Tools 2K25 - Beta 4.1 Hotfix
set EXENAME=tgc_gui_2k25_beta4_1
set PKG=TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4.1-Windows-x64
set RELEASEBASE=dist\release_beta4_1
set NOTES=RELEASE_NOTES_v0.5.0-2k25-beta4.1.1.md

echo.
echo ============================================================
echo TGC DESIGNER TOOLS 2K25 - BETA 4 PUBLISH
echo ============================================================
echo.

where gh >nul 2>nul
if errorlevel 1 (
  echo ERROR: GitHub CLI ^(gh^) is not installed or not on PATH.
  echo Install from https://cli.github.com/ and run: gh auth login
  goto :fail
)

gh auth status
if errorlevel 1 goto :fail

echo.
echo === Verify GitHub repository ===
gh repo view "%REPO%" >nul
if errorlevel 1 (
  echo ERROR: GitHub CLI cannot access %REPO%.
  goto :fail
)

if not exist "dist\%EXENAME%.exe" (
  echo ERROR: missing dist\%EXENAME%.exe
  echo Run BUILD_TGC_2K25_BETA4_1.bat first.
  goto :fail
)
if not exist "%RELEASEBASE%\%PKG%.zip" (
  echo ERROR: missing release ZIP.
  echo Run BUILD_TGC_2K25_BETA4_1.bat first.
  goto :fail
)
if not exist "%RELEASEBASE%\%EXENAME%.exe.sha256.txt" goto :missing
if not exist "%RELEASEBASE%\%PKG%.zip.sha256.txt" goto :missing
if not exist "%NOTES%" goto :missing

echo.
echo === Verify source before publishing ===
python VERIFY_BETA4_1_SOURCE.py
if errorlevel 1 goto :fail

echo.
echo === Check whether the release already exists ===
gh release view "%TAG%" --repo "%REPO%" >nul 2>nul
if not errorlevel 1 (
  echo ERROR: GitHub release %TAG% already exists.
  echo Delete/edit the existing release manually if you intend to replace it.
  goto :fail
)

echo.
echo === Create Beta 4.1 Hotfix prerelease ===
gh release create "%TAG%" --repo "%REPO%" ^
 "dist\%EXENAME%.exe" ^
 "%RELEASEBASE%\%EXENAME%.exe.sha256.txt" ^
 "%RELEASEBASE%\%PKG%.zip" ^
 "%RELEASEBASE%\%PKG%.zip.sha256.txt" ^
 --target main ^
 --title "%TITLE%" ^
 --notes-file "%NOTES%" ^
 --prerelease
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo RELEASE PUBLISHED:
echo https://github.com/malifica/TGC-Designer-Tools/releases/tag/%TAG%
echo ============================================================
pause
exit /b 0

:missing
echo ERROR: one or more Beta 4.1 Hotfix release files are missing.
echo Run BUILD_TGC_2K25_BETA4_1.bat first.
goto :fail

:fail
echo.
echo PUBLISH FAILED.
pause
exit /b 1
