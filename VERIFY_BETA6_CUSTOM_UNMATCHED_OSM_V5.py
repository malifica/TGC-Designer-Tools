from pathlib import Path
import math
import py_compile

import osm_custom_layout

ROOT = Path(__file__).resolve().parent

def read(name):
    return (ROOT / name).read_text(encoding="utf-8")

checks = []

def check(label, ok):
    checks.append((label, bool(ok)))
    print(("PASS" if ok else "FAIL") + " - " + label)

class Node:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon

class Result:
    def __init__(self):
        self.nodes = [
            Node(40.0000, -105.0000),
            Node(40.0000, -104.9900),
            Node(40.0100, -104.9900),
            Node(40.0100, -105.0000),
        ]
        self.ways = []

result = Result()
placement = osm_custom_layout.build_custom_placement(result, 500000.0, 4400000.0)
pts = [placement.project(float(n.lon), float(n.lat)) for n in result.nodes]
xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
check("custom placement centers OSM X on terrain", abs((min(xs)+max(xs))*0.5 - 500000.0) < 1e-6)
check("custom placement centers OSM Y on terrain", abs((min(ys)+max(ys))*0.5 - 4400000.0) < 1e-6)
check("custom placement preserves metre-scale source width", 800.0 < (max(xs)-min(xs)) < 900.0)
check("custom placement preserves metre-scale source height", 1100.0 < (max(ys)-min(ys)) < 1120.0)

class FakePC:
    def ulENU(self): return (0.0, 2000.0)
    def lrENU(self): return (2000.0, 0.0)
    def enuToTGC(self, x, y, z): return (x-1000.0, -z, y-1000.0)
    def projToTGC(self, x, y, z): return (x-500000.0, -z, y-4400000.0)

wrapped = osm_custom_layout.CustomTGCPointCloud(FakePC(), placement)
center = wrapped.latlonToTGC(placement.lat0, placement.lon0)
check("custom TGC wrapper maps source center near terrain center", abs(center[0]) < 5.0 and abs(center[2]) < 5.0)
shifted = wrapped.latlonToTGC(placement.lat0, placement.lon0, 12.5, -7.25)
check("CFS E/W and N/S shifts remain metre translations", abs((shifted[0]-center[0])-12.5) < 1e-6 and abs((shifted[2]-center[2])+7.25) < 1e-6)

gui = read("tgc_gui.py")
viewer = read("osm_alignment_viewer.py")
mask = read("osm_mask_alignment.py")
terrain = read("tgc_image_terrain.py")
check("Custom / Unmatched UI checkbox", 'text="Custom / Unmatched"' in gui)
check("Local OSM path box shortened", 'width=48' in gui and 'textvariable=local_osm_var' in gui)
check("Custom mode skips LiDAR OSM master reframe", 'if local_osm_file and not custom_unmatched_osm:' in gui)
check("Custom mode leaves DEM terrain CRS authoritative", 'processing_local_osm_file = ""' in gui)
check("AWS OSM-location discovery blocked in custom mode", 'AWS discovery is disabled in this mode' in gui)
check("CFS viewer supports custom centered projection", 'custom_unmatched_osm=self.custom_unmatched_osm' in viewer and 'placement_for_master_grid' in viewer)
check("Aligned mask supports custom centered projection", 'custom_placement=custom_placement' in mask and 'custom_unmatched_osm' in mask)
check("Mask sidecar tracks custom mode", '"custom_unmatched_osm": bool(custom_unmatched_osm)' in mask)
check("Final OSM course import uses custom point-cloud wrapper", 'CustomTGCPointCloud' in terrain and "Custom / Unmatched OSM import" in terrain)
check("No rotation added in custom transform", "rotation_degrees" not in read("osm_custom_layout.py") and "math.cos" not in read("osm_custom_layout.py") and "math.sin" not in read("osm_custom_layout.py"))

for name in ("osm_custom_layout.py", "tgc_gui.py", "tgc_image_terrain.py", "osm_alignment_viewer.py", "osm_mask_alignment.py"):
    try:
        py_compile.compile(str(ROOT / name), doraise=True)
        check("py_compile " + name, True)
    except Exception:
        check("py_compile " + name, False)

failed = [label for label, ok in checks if not ok]
if failed:
    print("\nBETA 6 CUSTOM / UNMATCHED OSM V5 VERIFICATION FAILED:")
    for label in failed:
        print(" - " + label)
    raise SystemExit(1)
print("\nBETA 6 CUSTOM / UNMATCHED OSM V5 VERIFICATION PASSED")
