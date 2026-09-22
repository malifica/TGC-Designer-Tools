@echo off
setlocal EnableExtensions
cd /d C:\TGC-Designer-Tools

set VERSION=v0.5.0-2k25-beta3.1
set EXENAME=tgc_gui_2k25_beta3_1
set PKG=TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3.1-Windows-x64
set RELEASEBASE=dist\release_beta3_1
set RELEASEDIR=%RELEASEBASE%\%PKG%

echo.
echo ============================================================
echo TGC DESIGNER TOOLS 2K25 - BETA 3.1 HOTFIX BUILD
echo ============================================================
echo.

call .venv_local_osm\Scripts\activate.bat
if errorlevel 1 goto :fail

echo === Python ===
python --version
if errorlevel 1 goto :fail

echo.
echo === Beta 3.1 source identity check ===
python -c "from pathlib import Path; s=Path('tgc_gui.py').read_text(encoding='utf-8'); req=['TGC_GUI_VERSION = \"v0.5.0-2k25-beta3.1\"','TGC_APP_TITLE = \"TGC Designer Tools 2K25 - Beta 3.1 Hotfix\"','root.title(TGC_APP_TITLE)']; miss=[x for x in req if x not in s]; print('Source title: TGC Designer Tools 2K25 - Beta 3.1 Hotfix' if not miss else 'ERROR: this folder still contains an older tgc_gui.py'); raise SystemExit(1 if miss else 0)"
if errorlevel 1 (
  echo.
  echo ERROR: You are NOT building from the Beta 3.1 hotfix source tree in this folder.
  echo Expected:
  echo   TGC_GUI_VERSION = v0.5.0-2k25-beta3.1
  echo   Window title = TGC Designer Tools 2K25 - Beta 3.1 Hotfix
  echo.
  echo Make sure the Beta 3.1 hotfix package files were extracted DIRECTLY into:
  echo   C:\TGC-Designer-Tools
  echo and not into:
  echo   C:\TGC-Designer-Tools\TGC-Designer-Tools
  goto :fail
)

echo.
echo === Rasterio / GDAL ===
python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
if errorlevel 1 goto :fail

echo.
echo === Compile exact LiDAR native rasterizer ===
set "NATIVE_LIDAR=PYTHON FALLBACK"
set "CC="
if defined TGC_CC if exist "%TGC_CC%" set "CC=%TGC_CC%"
if not defined CC if exist "D:\llvm-mingw\bin\x86_64-w64-mingw32-clang.exe" set "CC=D:\llvm-mingw\bin\x86_64-w64-mingw32-clang.exe"
if not defined CC (
  for %%I in (x86_64-w64-mingw32-clang.exe) do if not "%%~$PATH:I"=="" set "CC=%%~$PATH:I"
)
if not defined CC (
  for %%I in (x86_64-w64-mingw32-gcc.exe) do if not "%%~$PATH:I"=="" set "CC=%%~$PATH:I"
)

if defined CC (
  echo Native compiler: %CC%
  "%CC%" -O3 -shared -std=c11 -s -o tgc_lidar_fast_native.dll lidar_fast_native.c -lm
  if errorlevel 1 (
    echo WARNING: native LiDAR DLL compile failed.
    echo The EXE will still build with the exact Python fallback.
    if exist tgc_lidar_fast_native.dll del /q tgc_lidar_fast_native.dll
  ) else (
    set "NATIVE_LIDAR=NATIVE C"
  )
) else (
  echo WARNING: no MinGW-w64 compiler found.
  echo The EXE will use the exact Python rasterizer fallback.
)

echo.
echo === Syntax check ===
python -m py_compile ^
 tgc_gui.py ^
 dem_map_api.py ^
 lidar_map_api.py ^
 lidar_fast_native.py ^
 usgs_lidar_parser.py ^
 infill_image.py ^
 tgc_image_terrain.py ^
 OSMTGC.py ^
 auto_red_mask.py ^
 cfs_georef.py ^
 lidar_feature_filter.py ^
 osm_alignment_viewer.py
if errorlevel 1 goto :fail

echo.
echo === Clean previous Beta 3.1 hotfix build ===
if exist "build\%EXENAME%" rmdir /s /q "build\%EXENAME%"
if exist "dist\%EXENAME%.exe" del /q "dist\%EXENAME%.exe"
for %%F in ("dist\tgc_gui_2k25_beta2*.exe") do if exist "%%~fF" del /q "%%~fF"
if exist "%RELEASEBASE%" rmdir /s /q "%RELEASEBASE%"

echo.
echo === PyInstaller ===
if exist "tgc_lidar_fast_native.dll" (
  echo Bundling native LiDAR rasterizer DLL.
  python -m PyInstaller ^
   --noconfirm ^
   --clean ^
   --onefile ^
   --name "%EXENAME%" ^
   --add-binary "./laszip/laszip-cli.exe;laszip" ^
   --add-binary "tgc_lidar_fast_native.dll;." ^
   --additional-hooks-dir "./PyInstaller/hooks/" ^
   --runtime-hook "./PyInstaller/rthook_rasterio.py" ^
   tgc_gui.py
) else (
  echo Native DLL unavailable; building with Python fallback.
  python -m PyInstaller ^
   --noconfirm ^
   --clean ^
   --onefile ^
   --name "%EXENAME%" ^
   --add-binary "./laszip/laszip-cli.exe;laszip" ^
   --additional-hooks-dir "./PyInstaller/hooks/" ^
   --runtime-hook "./PyInstaller/rthook_rasterio.py" ^
   tgc_gui.py
)
if errorlevel 1 goto :fail
if not exist "dist\%EXENAME%.exe" goto :fail

echo.
echo === Package Beta 3.1 hotfix release ===
mkdir "%RELEASEDIR%"
copy /y "dist\%EXENAME%.exe" "%RELEASEDIR%\" >nul
copy /y "LICENSE" "%RELEASEDIR%\" >nul
copy /y "README.md" "%RELEASEDIR%\" >nul
copy /y "CHANGELOG.md" "%RELEASEDIR%\" >nul
copy /y "BUILD_WINDOWS.md" "%RELEASEDIR%\" >nul
copy /y "RELEASE_NOTES_v0.5.0-2k25-beta3.1.md" "%RELEASEDIR%\" >nul

powershell -NoProfile -Command ^
 "Compress-Archive -Path '%RELEASEDIR%\*' -DestinationPath '%RELEASEBASE%\%PKG%.zip' -Force"
if errorlevel 1 goto :fail

powershell -NoProfile -Command ^
 "(Get-FileHash 'dist\%EXENAME%.exe' -Algorithm SHA256).Hash + '  %EXENAME%.exe' | Out-File '%RELEASEBASE%\%EXENAME%.exe.sha256.txt' -Encoding ascii"
if errorlevel 1 goto :fail

powershell -NoProfile -Command ^
 "(Get-FileHash '%RELEASEBASE%\%PKG%.zip' -Algorithm SHA256).Hash + '  %PKG%.zip' | Out-File '%RELEASEBASE%\%PKG%.zip.sha256.txt' -Encoding ascii"
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo BUILD COMPLETE
echo EXE:
echo C:\TGC-Designer-Tools\dist\%EXENAME%.exe
echo.
echo RELEASE ZIP:
echo C:\TGC-Designer-Tools\%RELEASEBASE%\%PKG%.zip
echo.
echo LiDAR rasterizer: %NATIVE_LIDAR%
if "%NATIVE_LIDAR%"=="PYTHON FALLBACK" echo WARNING: Native Fast LiDAR was not included in this build.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
