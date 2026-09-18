@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d C:\TGC-Designer-Tools

set VERSION=v0.5.0-2k25-beta2
set EXENAME=tgc_gui_2k25_beta2
set PKG=TGC-Designer-Tools-2K25-v0.5.0-2k25-beta2-Windows-x64
set RELEASEDIR=dist\release_beta2

echo.
echo ============================================================
echo TGC DESIGNER TOOLS 2K25 - FINAL BETA 2 BUILD
echo ============================================================
echo.

call .venv_local_osm\Scripts\activate.bat
if errorlevel 1 goto :fail

echo === Python ===
python --version
if errorlevel 1 goto :fail

echo.
echo === Dependencies ===
python -m pip install --upgrade "rasterio==1.4.4"
if errorlevel 1 goto :fail

python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
if errorlevel 1 goto :fail

echo.
echo === Final Beta 2 source validation / release docs ===
python PREPARE_BETA2_FINAL_RELEASE.py
if errorlevel 1 goto :fail

echo.
echo === Clean previous build output ===
if exist "build\%EXENAME%" rmdir /s /q "build\%EXENAME%"
if exist "dist\%EXENAME%.exe" del /q "dist\%EXENAME%.exe"
if exist "dist\%PKG%" rmdir /s /q "dist\%PKG%"
if exist "dist\%PKG%.zip" del /q "dist\%PKG%.zip"
if exist "%RELEASEDIR%" rmdir /s /q "%RELEASEDIR%"

echo.
echo === PyInstaller build ===
python -m PyInstaller ^
 --noconfirm ^
 --clean ^
 --onefile ^
 --name "%EXENAME%" ^
 --add-binary "./laszip/laszip-cli.exe;laszip" ^
 --additional-hooks-dir "./PyInstaller/hooks/" ^
 --runtime-hook "./PyInstaller/rthook_rasterio.py" ^
 tgc_gui.py
if errorlevel 1 goto :fail

if not exist "dist\%EXENAME%.exe" (
  echo ERROR: Expected EXE was not created.
  goto :fail
)

echo.
echo === Package binary release ===
mkdir "dist\%PKG%"
copy /y "dist\%EXENAME%.exe" "dist\%PKG%\" >nul
copy /y "LICENSE" "dist\%PKG%\" >nul
copy /y "README.md" "dist\%PKG%\" >nul
copy /y "CHANGELOG.md" "dist\%PKG%\" >nul
copy /y "RELEASE_NOTES_v0.5.0-2k25-beta2.md" "dist\%PKG%\" >nul

powershell -NoProfile -Command "Compress-Archive -Path 'dist\%PKG%\*' -DestinationPath 'dist\%PKG%.zip' -Force"
if errorlevel 1 goto :fail

echo.
echo === SHA-256 checksums ===
powershell -NoProfile -Command "$h=(Get-FileHash 'dist\%EXENAME%.exe' -Algorithm SHA256); ($h.Hash.ToLower() + '  ' + [IO.Path]::GetFileName($h.Path)) | Set-Content 'dist\%EXENAME%.exe.sha256.txt' -Encoding ascii"
if errorlevel 1 goto :fail

powershell -NoProfile -Command "$h=(Get-FileHash 'dist\%PKG%.zip' -Algorithm SHA256); ($h.Hash.ToLower() + '  ' + [IO.Path]::GetFileName($h.Path)) | Set-Content 'dist\%PKG%.zip.sha256.txt' -Encoding ascii"
if errorlevel 1 goto :fail

echo.
echo === Assemble GitHub upload folder ===
mkdir "%RELEASEDIR%"
copy /y "dist\%EXENAME%.exe" "%RELEASEDIR%\" >nul
copy /y "dist\%EXENAME%.exe.sha256.txt" "%RELEASEDIR%\" >nul
copy /y "dist\%PKG%.zip" "%RELEASEDIR%\" >nul
copy /y "dist\%PKG%.zip.sha256.txt" "%RELEASEDIR%\" >nul
copy /y "RELEASE_NOTES_v0.5.0-2k25-beta2.md" "%RELEASEDIR%\" >nul

(
echo TGC Designer Tools 2K25 - %VERSION%
echo.
echo Release executable:
echo   %EXENAME%.exe
echo.
echo Release archive:
echo   %PKG%.zip
echo.
echo Git tag:
echo   %VERSION%
echo.
echo Automatic Carve Blue Mask Banks feature:
echo   NOT INCLUDED IN BETA 2
echo.
echo Legacy blue-mask controls retained:
echo   Fill Holes Under Blue Mask
echo   Remove All Terrain Under Blue Mask
) > "%RELEASEDIR%\RELEASE_MANIFEST.txt"

echo.
echo === Final file verification ===
for %%F in (
 "dist\%EXENAME%.exe"
 "dist\%EXENAME%.exe.sha256.txt"
 "dist\%PKG%.zip"
 "dist\%PKG%.zip.sha256.txt"
 "%RELEASEDIR%\RELEASE_NOTES_v0.5.0-2k25-beta2.md"
 "%RELEASEDIR%\RELEASE_MANIFEST.txt"
) do (
  if not exist %%F (
    echo ERROR: Missing expected release file %%F
    goto :fail
  )
)

echo.
echo ============================================================
echo FINAL BETA 2 BUILD COMPLETE
echo ============================================================
echo.
echo EXE:
echo   C:\TGC-Designer-Tools\dist\%EXENAME%.exe
echo.
echo RELEASE ZIP:
echo   C:\TGC-Designer-Tools\dist\%PKG%.zip
echo.
echo GITHUB UPLOAD FOLDER:
echo   C:\TGC-Designer-Tools\%RELEASEDIR%
echo.
echo CHECKSUMS:
type "dist\%EXENAME%.exe.sha256.txt"
type "dist\%PKG%.zip.sha256.txt"
echo.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ============================================================
echo BETA 2 BUILD FAILED
echo ============================================================
echo.
echo No release should be published from this run.
pause
exit /b 1
