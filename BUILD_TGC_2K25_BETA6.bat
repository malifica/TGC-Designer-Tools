@echo off
setlocal EnableExtensions
cd /d C:\TGC-Designer-Tools

set VERSION=v0.5.0-2k25-beta6
set EXENAME=tgc_gui_2k25_beta6
set PKG=TGC-Designer-Tools-2K25-v0.5.0-2k25-beta6-Windows-x64
set RELEASEBASE=dist\release_beta6
set RELEASEDIR=%RELEASEBASE%\%PKG%

echo.
echo ============================================================
echo TGC DESIGNER TOOLS 2K25 - BETA 6 BUILD
echo ============================================================
echo.

call .venv_local_osm\Scripts\activate.bat
if errorlevel 1 goto :fail

echo === Python ===
python --version
if errorlevel 1 goto :fail

echo.
echo === Beta 6 source identity check ===
python -c "from pathlib import Path; s=Path('tgc_gui.py').read_text(encoding='utf-8'); req=['TGC_GUI_VERSION = \"v0.5.0-2k25-beta6\"','TGC_APP_TITLE = \"TGC Designer Tools 2K25 - Beta 6\"','root.title(TGC_APP_TITLE)']; miss=[x for x in req if x not in s]; print('Source title: TGC Designer Tools 2K25 - Beta 6' if not miss else 'ERROR: this folder does not contain the Beta 6 source identity'); raise SystemExit(1 if miss else 0)"
if errorlevel 1 (
  echo.
  echo ERROR: You are NOT building from the Beta 6 source tree in this folder.
  echo Run PREPARE_TGC_2K25_BETA6_STANDALONE_V4.py first.
  goto :fail
)

echo.
echo === Beta 6 full source verification ===
python VERIFY_BETA6_SOURCE.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_SPLINE_SURFACE_FIX_V1.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py
if errorlevel 1 goto :fail

python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py
if errorlevel 1 goto :fail

echo.
echo === LiDAR tree-size hotfix verification ===
python tgc_tree_size_test1_entry.py --verify-lidar-trees
if errorlevel 1 goto :fail

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
 usgs_ept_downloader.py ^
 infill_image.py ^
 tgc_image_terrain.py ^
 tgc_definitions.py ^
 tgc_tools.py ^
 tree_profile_manager.py ^
 tree_profile_analyzer.py ^
 OSMTGC.py ^
 auto_red_mask.py ^
 cfs_georef.py ^
 lidar_feature_filter.py ^
 osm_mask_alignment.py ^
 osm_custom_layout.py ^
 osm_alignment_viewer.py ^
 VERIFY_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1.py ^
 VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py ^
 VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py ^
 VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py ^
 VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py ^
 VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py ^
 VERIFY_BETA6_SPLINE_SURFACE_FIX_V1.py
if errorlevel 1 goto :fail

echo.
echo === Clean previous Beta 6 build ===
if exist "build\%EXENAME%" rmdir /s /q "build\%EXENAME%"
if exist "dist\%EXENAME%.exe" del /q "dist\%EXENAME%.exe"
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
   --add-data "./tree_profiles;tree_profiles" ^
   tgc_tree_size_test1_entry.py
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
   --add-data "./tree_profiles;tree_profiles" ^
   tgc_tree_size_test1_entry.py
)
if errorlevel 1 goto :fail
if not exist "dist\%EXENAME%.exe" goto :fail
"dist\%EXENAME%.exe" --verify-lidar-trees
if errorlevel 1 goto :fail

echo.
echo === Package Beta 6 release ===
mkdir "%RELEASEDIR%"
copy /y "dist\%EXENAME%.exe" "%RELEASEDIR%\" >nul
copy /y "LICENSE" "%RELEASEDIR%\" >nul
copy /y "README.md" "%RELEASEDIR%\" >nul
copy /y "CHANGELOG.md" "%RELEASEDIR%\" >nul
copy /y "BUILD_WINDOWS.md" "%RELEASEDIR%\" >nul
copy /y "BETA6_TREE_PROFILES.md" "%RELEASEDIR%\" >nul
copy /y "BETA6_LIDAR_TREE_HOTFIX.md" "%RELEASEDIR%\" >nul
copy /y "RELEASE_NOTES_v0.5.0-2k25-beta6.md" "%RELEASEDIR%\" >nul
if exist "BETA6_HOTFIX.md" copy /y "BETA6_HOTFIX.md" "%RELEASEDIR%\" >nul
if exist "extras\splines.json" copy /y "extras\splines.json" "%RELEASEDIR%\splines.json" >nul
if exist "BETA6_OSM_CARTPATH_ROAD_SPLIT_V4.txt" copy /y "BETA6_OSM_CARTPATH_ROAD_SPLIT_V4.txt" "%RELEASEDIR%\" >nul
if exist "BETA6_OSM_GOLF_PATH_ONLY_V4_1.txt" copy /y "BETA6_OSM_GOLF_PATH_ONLY_V4_1.txt" "%RELEASEDIR%\" >nul
if exist "SPLINES_JSON_ROAD_EXAMPLE.json" copy /y "SPLINES_JSON_ROAD_EXAMPLE.json" "%RELEASEDIR%\" >nul
if exist "BETA6_CUSTOM_UNMATCHED_OSM_V5_1.txt" copy /y "BETA6_CUSTOM_UNMATCHED_OSM_V5_1.txt" "%RELEASEDIR%\" >nul
xcopy /E /I /Y "tree_profiles" "%RELEASEDIR%\tree_profiles" >nul

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
