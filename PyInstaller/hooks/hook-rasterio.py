from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    collect_delvewheel_libs_directory,
)

hiddenimports = collect_submodules("rasterio")
datas = collect_data_files("rasterio")
binaries = collect_dynamic_libs("rasterio")

# Rasterio Windows wheels may ship GDAL/PROJ DLLs in rasterio.libs,
# outside the package directory.
datas, binaries = collect_delvewheel_libs_directory(
    "rasterio", datas=datas, binaries=binaries
)
