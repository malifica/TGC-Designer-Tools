from pathlib import Path
import py_compile
import json
import sys

ROOT = Path(__file__).resolve().parent

def read(name):
    p = ROOT / name
    if not p.exists():
        raise SystemExit(f"ERROR: required Beta 5 development file is missing: {name}")
    return p.read_text(encoding="utf-8")

sources = {
    "tgc_gui.py": read("tgc_gui.py"),
    "tgc_image_terrain.py": read("tgc_image_terrain.py"),
    "tree_profile_manager.py": read("tree_profile_manager.py"),
    "tree_profile_analyzer.py": read("tree_profile_analyzer.py"),
    "BETA5_TREE_PROFILES.md": read("BETA5_TREE_PROFILES.md"),
}

checks = [
    ("Beta 5 dev version", "tgc_gui.py", 'TGC_GUI_VERSION = "v0.5.0-2k25-beta5-dev"'),
    ("Beta 5 dev title", "tgc_gui.py", 'TGC_APP_TITLE = "TGC Designer Tools 2K25 - Beta 5 Development"'),
    ("Tree profile GUI selector", "tgc_gui.py", 'text="Tree Planting Theme"'),
    ("Tree scale GUI selector", "tgc_gui.py", 'text="Tree Scale"'),
    ("Heroic default", "tgc_gui.py", 'tree_scale_mode_var.set(tree_profile_manager.HEROIC_SCALE_MODE)'),
    ("Profile loader", "tree_profile_manager.py", "def load_profiles("),
    ("Weighted asset selection", "tree_profile_manager.py", "rng.choices("),
    ("Reference quantile scaling", "tree_profile_manager.py", "def scale_for_asset("),
    ("Uniform profile scale support", "tree_profile_manager.py", 'asset.get("uniform_scale")'),
    ("Analyzer excludes detail-tree props", "tree_profile_analyzer.py", '"/Foliage/SpeedTree" not in asset_path'),
    ("Course analyzer", "tree_profile_analyzer.py", "def analyze(paths, display_name):"),
    ("Runtime custom profile builder", "tgc_image_terrain.py", "def _get_profile_trees("),
    ("Profile option plumbing", "tgc_image_terrain.py", "tree_profile=options_dict.get('tree_profile')"),
    ("Heroic height target", "tgc_image_terrain.py", "max_height_scale = 1.55"),
    ("Texas Hill Country profile file", "BETA5_TREE_PROFILES.md", "Texas Hill Country"),
]

failed = []
print("TGC Designer Tools 2K25 Beta 5 development source verification")
for label, filename, needle in checks:
    ok = needle in sources[filename]
    print(("PASS" if ok else "FAIL"), "-", label)
    if not ok:
        failed.append(label)

for name in [
    "tgc_gui.py", "tgc_image_terrain.py", "tree_profile_manager.py",
    "tree_profile_analyzer.py", "tgc_definitions.py", "OSMTGC.py"
]:
    try:
        py_compile.compile(str(ROOT / name), doraise=True)
        print("PASS - py_compile", name)
    except Exception as exc:
        print("FAIL - py_compile", name, "-", exc)
        failed.append("py_compile " + name)

texas_profile = ROOT / "tree_profiles" / "texas_hill_country.json"
try:
    texas = json.loads(texas_profile.read_text(encoding="utf-8"))
    assert texas.get("enabled") is True
    assert texas.get("display_name") == "Texas Hill Country"
    assert len(texas.get("assets", [])) == 51
    print("PASS - Texas Hill Country enabled profile")
except Exception as exc:
    print("FAIL - Texas Hill Country enabled profile -", exc)
    failed.append("Texas Hill Country enabled profile")

template = ROOT / "tree_profiles" / "_template.json"
try:
    json.loads(template.read_text(encoding="utf-8"))
    print("PASS - tree profile JSON template")
except Exception as exc:
    print("FAIL - tree profile JSON template -", exc)
    failed.append("tree profile JSON template")

if failed:
    print("FINAL VERIFICATION FAILED")
    for item in failed:
        print(" -", item)
    sys.exit(1)

print("FINAL VERIFICATION PASSED")
