@echo off
setlocal
cd /d C:\TGC-Designer-Tools

call .venv_local_osm\Scripts\activate.bat
if errorlevel 1 goto :fail

echo.
echo === Python ===
python --version
if errorlevel 1 goto :fail

echo.
echo === Install Rasterio 1.4.4 for Python 3.11 ===
python -m pip install --upgrade "rasterio==1.4.4"
if errorlevel 1 goto :fail

echo.
echo === Rasterio diagnostic ===
python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
if errorlevel 1 goto :fail

echo.
echo === Syntax check ===
python -m py_compile dem_map_api.py tgc_gui.py lidar_map_api.py tgc_image_terrain.py OSMTGC.py infill_image.py usgs_lidar_parser.py
if errorlevel 1 goto :fail

echo.
echo === Build ===
python -m PyInstaller ^
 --noconfirm ^
 --clean ^
 --onefile ^
 --name "tgc_gui_2k25_LOCAL_OSM_DEM" ^
 --add-binary "./laszip/laszip-cli.exe;laszip" ^
 --additional-hooks-dir "./PyInstaller/hooks/" ^
 --runtime-hook "./PyInstaller/rthook_rasterio.py" ^
 tgc_gui.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo BUILD COMPLETE
echo EXE:
echo   C:\TGC-Designer-Tools\dist\tgc_gui_2k25_LOCAL_OSM_DEM.exe
echo ============================================================
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
