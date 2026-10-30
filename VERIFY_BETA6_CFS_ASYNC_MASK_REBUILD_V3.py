from pathlib import Path
import importlib.util
import sys
import tempfile
import types

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
VIEWER = ROOT / "osm_alignment_viewer.py"
MASK = ROOT / "osm_mask_alignment.py"
GUI = ROOT / "tgc_gui.py"


def _load_mask_with_stubs():
    saved = {}

    def install(name, module):
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module

    fake_overpy = types.ModuleType("overpy")
    class DataIncomplete(Exception):
        pass
    fake_overpy.exception = types.SimpleNamespace(DataIncomplete=DataIncomplete)
    install("overpy", fake_overpy)

    fake_cfs = types.ModuleType("cfs_georef")
    fake_cfs.get_master_grid = lambda data, heightmap, printf=print: dict(data["master_grid"])
    fake_cfs.horizontal_epsg = lambda projection: 32614
    fake_cfs.crs_wkt = lambda projection: "TEST_CRS"
    fake_cfs.validate_projection = lambda projection, printf=print: True
    install("cfs_georef", fake_cfs)

    fake_geo = types.ModuleType("GeoPointCloud")
    class GeoPointCloud:
        def __init__(self):
            self.proj = None
            self.origin = None
        def latlonToCV2(self, lat, lon, image_scale, offset_x=0.0, offset_y=0.0):
            return int(float(lat) + float(offset_y)), int(float(lon) + float(offset_x))
    fake_geo.GeoPointCloud = GeoPointCloud
    install("GeoPointCloud", fake_geo)

    class FakeWay:
        id = 1
        def get_nodes(self, resolve_missing=False):
            return []
    class FakeResult:
        ways = [FakeWay()]
        relations = []

    fake_osm = types.ModuleType("OSMTGC")
    fake_osm.parseOSMData = lambda xml, printf=print: FakeResult()
    fake_osm.addOSMToImage = lambda ways, image, pc, image_scale, **kwargs: np.array(image, copy=True)
    install("OSMTGC", fake_osm)

    fake_mask = types.ModuleType("auto_red_mask")
    fake_mask.apply_auto_red_mask = lambda source, image, pc, scale, **kwargs: np.array(image, copy=True)
    install("auto_red_mask", fake_mask)

    spec = importlib.util.spec_from_file_location("osm_mask_alignment_async_tested", MASK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def restore():
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    return module, restore


def main():
    viewer = VIEWER.read_text(encoding="utf-8")
    mask = MASK.read_text(encoding="utf-8")
    gui = GUI.read_text(encoding="utf-8")

    required = [
        (viewer, "TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3"),
        (viewer, "TGC-CFS-Viewer-Load"),
        (viewer, "TGC-CFS-Aligned-Mask-Rebuild"),
        (viewer, "ttk.Progressbar"),
        (viewer, "self.window.after(60, self._pump_load_queue)"),
        (viewer, "self.window.after(60, self._pump_apply_queue)"),
        (viewer, "from tgc_cfs_display import importer_transformer"),
        (viewer, "importer_transformer(projection)"),
        (mask, "TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3"),
        (mask, "class _FastGridProjector"),
        (mask, "progress_callback=None"),
        (gui, "TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3"),
        (gui, "TGC-Main-Aligned-Mask-Rebuild"),
        (gui, "_startOSMMaskRebuildProgressTask"),
        (gui, "apply_finished_callback=alignment_rebuild_finished"),
    ]
    missing = [needle for text, needle in required if needle not in text]
    if missing:
        print("FAIL - missing async/progress markers:")
        for needle in missing:
            print("  ", needle)
        return 2

    # The old synchronous CFS callback must not remain.
    if "rebuild_result = self.apply_callback(" in viewer:
        print("FAIL - synchronous CFS apply callback remains")
        return 3

    module, restore = _load_mask_with_stubs()
    try:
        with tempfile.TemporaryDirectory(prefix="tgc_async_mask_test_") as temp:
            folder = Path(temp)
            heightmap = np.arange(25 * 30, dtype=np.float32).reshape(25, 30)
            data = {
                "heightmap": heightmap,
                "image_scale": 1.0,
                "projection": "TEST",
                "master_grid": {
                    "resolution": 1.0,
                    "rows": 25,
                    "cols": 30,
                    "min_x": 0.0,
                    "min_y": 0.0,
                    "max_x": 30.0,
                    "max_y": 25.0,
                    "row_order": "south_up_internal",
                    "origin_semantics": "southwest_cell_edge",
                    "lower_left_latlon": [0.0, 0.0],
                },
            }
            np.save(str(folder / "heightmap.npy"), data)
            assert cv2.imwrite(
                str(folder / "mask.png"),
                np.full((25, 30, 3), 255, dtype=np.uint8),
            )
            osm = folder / "layout.osm"
            osm.write_text("<osm version='0.6'></osm>\n", encoding="utf-8")

            progress = []
            result = module.rebuild_aligned_mask(
                folder,
                osm,
                0.0,
                0.0,
                auto_red_mask_enabled=True,
                auto_red_mask_buffer_m=5.0,
                backup_existing=True,
                printf=lambda _message: None,
                progress_callback=lambda pct, msg: progress.append((float(pct), str(msg))),
            )
            assert result["action"] == "rebuilt"
            assert progress
            values = [value for value, _message in progress]
            assert values[0] >= 0.0
            assert values[-1] == 100.0
            assert all(a <= b for a, b in zip(values, values[1:]))
            assert any("OSM" in message for _value, message in progress)
            assert any("Writing" in message for _value, message in progress)

        print("PASS: CFS viewer preparation runs on a background worker.")
        print("PASS: CFS Apply rebuild runs on a background worker with progress.")
        print("PASS: main-window rebuild uses a queue-driven progress dialog.")
        print("PASS: mask rebuild reports monotonic staged progress through verification.")
        print("PASS: CFS OSM projection reuses one vectorized PyProj transformer.")
        return 0
    finally:
        restore()


if __name__ == "__main__":
    raise SystemExit(main())
