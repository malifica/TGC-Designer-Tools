import os
import sys

base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

for key, path in (
    ("GDAL_DATA", os.path.join(base, "rasterio", "gdal_data")),
    ("PROJ_LIB", os.path.join(base, "rasterio", "proj_data")),
    ("PROJ_DATA", os.path.join(base, "rasterio", "proj_data")),
):
    if os.path.isdir(path) and not os.environ.get(key):
        os.environ[key] = path
