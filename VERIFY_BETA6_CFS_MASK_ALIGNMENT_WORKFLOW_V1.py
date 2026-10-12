from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import types

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "osm_mask_alignment.py"


def _load_with_test_stubs():
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

    def add_osm_to_image(
        ways,
        image,
        pc,
        image_scale,
        x_offset=0.0,
        y_offset=0.0,
        printf=print,
    ):
        out = np.array(image, copy=True)
        col = 10 + int(round(float(x_offset) / float(image_scale)))
        row = 10 + int(round(float(y_offset) / float(image_scale)))
        if 0 <= row < out.shape[0] and 0 <= col < out.shape[1]:
            out[row, col, :] = (0.0, 0.0, 1.0)
        return out

    fake_osm.addOSMToImage = add_osm_to_image
    install("OSMTGC", fake_osm)

    fake_mask = types.ModuleType("auto_red_mask")
    def apply_auto_red_mask(
        osm_source,
        image_rgb,
        pc,
        image_scale,
        buffer_m=5.0,
        x_offset=0.0,
        y_offset=0.0,
        printf=print,
    ):
        out = np.zeros_like(image_rgb, dtype=np.float32)
        out[:, :, 0] = 1.0
        col = 10 + int(round(float(x_offset) / float(image_scale)))
        row = 10 + int(round(float(y_offset) / float(image_scale)))
        radius = max(1, int(round(float(buffer_m) / float(image_scale))))
        r0 = max(0, row - radius)
        r1 = min(out.shape[0], row + radius + 1)
        c0 = max(0, col - radius)
        c1 = min(out.shape[1], col + radius + 1)
        out[r0:r1, c0:c1, :] = image_rgb[r0:r1, c0:c1, :]
        return out
    fake_mask.apply_auto_red_mask = apply_auto_red_mask
    install("auto_red_mask", fake_mask)

    spec = importlib.util.spec_from_file_location("osm_mask_alignment_tested", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def restore():
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    return module, restore


def _write_initial_project(folder):
    heightmap = np.arange(30 * 30, dtype=np.float32).reshape(30, 30)
    data = {
        "heightmap": heightmap,
        "image_scale": 1.0,
        "projection": "TEST",
        "master_grid": {
            "resolution": 1.0,
            "rows": 30,
            "cols": 30,
            "min_x": 0.0,
            "min_y": 0.0,
            "max_x": 30.0,
            "max_y": 30.0,
            "row_order": "south_up_internal",
            "origin_semantics": "southwest_cell_edge",
            "lower_left_latlon": [0.0, 0.0],
        },
    }
    np.save(str(folder / "heightmap.npy"), data)
    initial = np.full((30, 30, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(folder / "mask.png"), initial)
    (folder / "layout.osm").write_text("<osm version='0.6'></osm>\n", encoding="utf-8")


def main():
    source = TARGET.read_text(encoding="utf-8")
    required = [
        "TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1",
        "x_offset=float(adjust_ew_m)",
        "y_offset=float(adjust_ns_m)",
        "manual_mask_edits_permitted_after_rebuild",
        "adopt_existing_zero_shift_mask",
        "invalidate_alignment_record",
    ]
    missing = [needle for needle in required if needle not in source]
    if missing:
        print("FAIL - missing source markers:")
        for item in missing:
            print("  ", item)
        return 2

    module, restore = _load_with_test_stubs()
    try:
        with tempfile.TemporaryDirectory(prefix="tgc_mask_alignment_test_") as temp:
            folder = Path(temp)
            _write_initial_project(folder)
            osm = folder / "layout.osm"

            first = module.rebuild_aligned_mask(
                folder,
                osm,
                0.0,
                0.0,
                auto_red_mask_enabled=True,
                auto_red_mask_buffer_m=2.0,
                backup_existing=True,
                printf=lambda _message: None,
            )
            assert first["action"] == "rebuilt"
            assert Path(first["backup_path"]).is_file()

            status = module.get_alignment_status(folder, osm, 0.0, 0.0, True, 2.0)
            assert status["state"] == "current"

            # Manual edits must not invalidate a current alignment record.
            edited = cv2.imread(str(folder / "mask.png"), cv2.IMREAD_COLOR)
            edited[0, 0] = (0, 255, 0)
            assert cv2.imwrite(str(folder / "mask.png"), edited)
            status = module.get_alignment_status(folder, osm, 0.0, 0.0, True, 2.0)
            assert status["state"] == "current"

            # Any later terrain/mask processor must explicitly invalidate the
            # alignment record even when the master-grid dimensions stay the same.
            assert module.invalidate_alignment_record(
                folder,
                "Synthetic processing regenerated mask.png.",
                printf=lambda _message: None,
            )
            invalidated = module.get_alignment_status(folder, osm, 0.0, 0.0, True, 2.0)
            assert invalidated["state"] == "stale"
            assert "Synthetic processing" in invalidated["message"]

            module.rebuild_aligned_mask(
                folder,
                osm,
                0.0,
                0.0,
                auto_red_mask_enabled=True,
                auto_red_mask_buffer_m=2.0,
                backup_existing=True,
                printf=lambda _message: None,
            )

            stale = module.get_alignment_status(folder, osm, 5.0, 0.0, True, 2.0)
            assert stale["state"] == "stale"

            second = module.rebuild_aligned_mask(
                folder,
                osm,
                5.0,
                0.0,
                auto_red_mask_enabled=True,
                auto_red_mask_buffer_m=2.0,
                backup_existing=True,
                printf=lambda _message: None,
            )
            assert Path(second["backup_path"]).is_file()
            current = module.get_alignment_status(folder, osm, 5.0, 0.0, True, 2.0)
            assert current["state"] == "current"

            # The shifted protected area must move five pixels to the east.
            mask_bgr = cv2.imread(str(folder / "mask.png"), cv2.IMREAD_COLOR)
            mask_rgb_internal = np.flip(cv2.cvtColor(mask_bgr, cv2.COLOR_BGR2RGB), 0)
            assert tuple(mask_rgb_internal[10, 15]) == (0, 0, 255)
            assert tuple(mask_rgb_internal[10, 10]) == (255, 0, 0)

            # Legacy zero-shift adoption preserves bytes exactly.
            sidecar = folder / module.SIDECAR_NAME
            sidecar.unlink()
            before = (folder / "mask.png").read_bytes()
            module.adopt_existing_zero_shift_mask(
                folder,
                osm,
                0.0,
                0.0,
                auto_red_mask_enabled=True,
                auto_red_mask_buffer_m=2.0,
                printf=lambda _message: None,
            )
            after = (folder / "mask.png").read_bytes()
            assert before == after
            adopted = module.get_alignment_status(folder, osm, 0.0, 0.0, True, 2.0)
            assert adopted["state"] == "current"

        print("PASS: post-CFS aligned mask rebuild moves with the final alignment.")
        print("PASS: changed alignment is detected as stale before import.")
        print("PASS: later terrain/mask processing explicitly invalidates the alignment record.")
        print("PASS: manual mask edits do not invalidate a current alignment record.")
        print("PASS: legacy zero-shift adoption preserves mask.png byte-for-byte.")
        return 0
    finally:
        restore()


if __name__ == "__main__":
    raise SystemExit(main())
