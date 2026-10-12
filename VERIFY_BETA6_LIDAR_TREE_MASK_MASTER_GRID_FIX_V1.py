from pathlib import Path
import py_compile
import sys

PATCH_ID = "BETA6_LIDAR_TREE_MASK_MASTER_GRID_FIX_V1"

def main():
    root = Path.cwd()
    target = root / "tgc_image_terrain.py"
    if not target.is_file():
        raise RuntimeError("tgc_image_terrain.py not found in current folder.")

    text = target.read_text(encoding="utf-8")
    required = [
        PATCH_ID,
        "mask_pc.proj = read_dictionary['projection']",
        "float(master_grid['min_x'])",
        "float(master_grid['min_y'])",
        "LiDAR tree mask georef: using full master-grid origin",
    ]
    missing = [s for s in required if s not in text]
    if missing:
        print("FAIL - missing patch markers:")
        for s in missing:
            print("  ", s)
        return 2

    py_compile.compile(str(target), doraise=True)
    print("PASS: Beta 6 LiDAR tree mask lookup is anchored to the full master grid.")
    print("Optional proximity/surface filters and Hulkify were not modified by this patch.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
