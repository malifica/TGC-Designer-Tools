from pathlib import Path
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


class Way:
    def __init__(self, wid, nodes, tags):
        self.id = wid
        self._nodes = list(nodes)
        self.tags = dict(tags)

    def get_nodes(self, resolve_missing=False):
        return list(self._nodes)


class Result:
    def __init__(self, nodes=None, ways=None, relations=None):
        self.nodes = list(nodes or [])
        self.ways = list(ways or [])
        self.relations = list(relations or [])


# Preserve V5 fallback semantics when no golf tags exist.
result = Result(nodes=[
    Node(40.0000, -105.0000),
    Node(40.0000, -104.9900),
    Node(40.0100, -104.9900),
    Node(40.0100, -105.0000),
])
placement = osm_custom_layout.build_custom_placement(result, 500000.0, 4400000.0)
pts = [placement.project(float(n.lon), float(n.lat)) for n in result.nodes]
xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
check("fallback custom placement centers OSM X on terrain", abs((min(xs)+max(xs))*0.5 - 500000.0) < 1e-6)
check("fallback custom placement centers OSM Y on terrain", abs((min(ys)+max(ys))*0.5 - 4400000.0) < 1e-6)

# V5.1 regression: unrelated OSM context must NOT own the detached center.
hole_nodes = [
    Node(41.0000, -72.0000),
    Node(41.0010, -71.9990),
    Node(41.0020, -71.9980),
]
far_nodes = [
    Node(40.9200, -72.0700),
    Node(41.0800, -71.9300),
]
anchored_result = Result(
    nodes=hole_nodes + far_nodes,
    ways=[
        Way(1, hole_nodes, {"golf": "hole", "ref": "1"}),
        Way(2, far_nodes, {"highway": "motorway"}),
    ],
)
anchored = osm_custom_layout.build_custom_placement(anchored_result, 1000.0, 2000.0)
info = anchored.diagnostics()
check("Custom centering prefers golf=hole anchor", info.get("anchor_strategy") == "golf=hole ways")
check("Custom anchor excludes far unrelated OSM context", float(info["source_width_m"]) < 500.0 and float(info["source_height_m"]) < 500.0)
hole_projected = [anchored.project(float(n.lon), float(n.lat)) for n in hole_nodes]
hx = [p[0] for p in hole_projected]; hy = [p[1] for p in hole_projected]
check("golf hole anchor centered on target X", abs((min(hx)+max(hx))*0.5 - 1000.0) < 1e-6)
check("golf hole anchor centered on target Y", abs((min(hy)+max(hy))*0.5 - 2000.0) < 1e-6)


class FakePC:
    origin = (500000.0, 4400000.0)
    width = 2000.0
    height = 2000.0

    def ulENU(self): return (0.0, 2000.0)
    def lrENU(self): return (2000.0, 0.0)
    def enuToTGC(self, x, y, z): return (x-1000.0, -z, y-1000.0)
    def projToTGC(self, x, y, z): return (x-501000.0, -z, y-4401000.0)
    def projToCV2(self, x, y, image_scale):
        return ((y-4400000.0)/image_scale, (x-500000.0)/image_scale)

wrapped_placement = osm_custom_layout.build_custom_placement(anchored_result, 501000.0, 4401000.0)
wrapped = osm_custom_layout.CustomTGCPointCloud(FakePC(), wrapped_placement)
center = wrapped.latlonToTGC(wrapped_placement.lat0, wrapped_placement.lon0)
check("custom TGC wrapper supports detached import", abs(center[0]) < 5.0 and abs(center[2]) < 5.0)
row, col = wrapped.latlonToCV2(wrapped_placement.lat0, wrapped_placement.lon0, 2.0)
check("custom point-cloud wrapper supports detached preview pixels", 450.0 < row < 550.0 and 450.0 < col < 550.0)

gui = read("tgc_gui.py")
layout = read("osm_custom_layout.py")
viewer = read("osm_alignment_viewer.py")
mask = read("osm_mask_alignment.py")
terrain = read("tgc_image_terrain.py")

check("V5.1 marker present", "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5_1" in gui and "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5_1" in layout)
check("LiDAR selection preview gets detached OSM overlay", '_apply_custom_unmatched_preview_overlay(' in gui and '"lidar"' in gui)
check("DEM selection preview gets detached OSM overlay", '_apply_custom_unmatched_preview_overlay(' in gui and '"dem"' in gui)
check("Preview overlay uses same custom point-cloud transform", "CustomTGCPointCloud" in gui and "build_custom_placement" in gui)
check("Custom preview does not feed detached result into ordinary output projector", 'prepared["custom_preview_osm_result"]' in gui)
check("CFS viewer still uses shared placement helper", "placement_for_master_grid" in viewer)
check("Aligned mask still uses shared placement helper", "placement_for_master_grid" in mask)
check("V5 custom masks become stale after V5.1 placement change", "custom_layout_patch_id" in mask and "placement logic changed" in mask)
check("Final course import still uses shared custom placement", "build_custom_placement" in terrain and "CustomTGCPointCloud" in terrain)
check("No rotation introduced", "rotation_degrees" not in layout and "math.cos" not in layout and "math.sin" not in layout)

for name in (
    "osm_custom_layout.py",
    "tgc_gui.py",
    "tgc_image_terrain.py",
    "osm_alignment_viewer.py",
    "osm_mask_alignment.py",
):
    try:
        py_compile.compile(str(ROOT / name), doraise=True)
        check("py_compile " + name, True)
    except Exception:
        check("py_compile " + name, False)

failed = [label for label, ok in checks if not ok]
if failed:
    print("\nBETA 6 CUSTOM / UNMATCHED OSM V5.1 VERIFICATION FAILED:")
    for label in failed:
        print(" - " + label)
    raise SystemExit(1)
print("\nBETA 6 CUSTOM / UNMATCHED OSM V5.1 VERIFICATION PASSED")
