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
    ("Tree profile GUI selector", "tgc_gui.py", 'text="Regional Theme (Trees + Materials)"'),
    ("Tree scale GUI selector", "tgc_gui.py", 'text="Tree Scale"'),
    ("Heroic default", "tgc_gui.py", 'tree_scale_mode_var.set(tree_profile_manager.HEROIC_SCALE_MODE)'),
    ("Profile loader", "tree_profile_manager.py", "def load_profiles("),
    ("Material preset loader", "tree_profile_manager.py", "visual_material_preset"),
    ("Material preset apply helper", "tree_profile_manager.py", "def apply_visual_material_preset("),
    ("Regional theme GUI label", "tgc_gui.py", 'text="Regional Theme (Trees + Materials)"'),
    ("Weighted asset selection", "tree_profile_manager.py", "rng.choices("),
    ("Reference quantile scaling", "tree_profile_manager.py", "def scale_for_asset("),
    ("Uniform profile scale support", "tree_profile_manager.py", 'asset.get("uniform_scale")'),
    ("Analyzer excludes detail-tree props", "tree_profile_analyzer.py", '"/Foliage/SpeedTree" not in asset_path'),
    ("Analyzer buried scenery filter", "tree_profile_analyzer.py", "DEFAULT_VERTICAL_TOLERANCE_M = 0.75"),
    ("Analyzer terrain replay", "tree_profile_analyzer.py", "class _TerrainPointSampler:"),
    ("Course analyzer", "tree_profile_analyzer.py", "def analyze("),
    ("Reference sample guard", "tree_profile_analyzer.py", "min_natural_trees=25"),
    ("Sparse reference override", "tree_profile_analyzer.py", "--allow-low-sample-reference"),
    ("Runtime custom profile builder", "tgc_image_terrain.py", "def _get_profile_trees("),
    ("Profile option plumbing", "tgc_image_terrain.py", "tree_profile=options_dict.get('tree_profile')"),
    ("Heroic height target", "tgc_image_terrain.py", "max_height_scale = 1.55"),
    ("Texas Hill Country profile file", "BETA5_TREE_PROFILES.md", "Texas Hill Country"),
    ("Niagara Escarpment profile file", "BETA5_TREE_PROFILES.md", "Niagara Escarpment"),
    ("Carolina Piedmont Autumn profile file", "BETA5_TREE_PROFILES.md", "Carolina Piedmont (Autumn)"),
    ("Virginia Coastal Plain profile file", "BETA5_TREE_PROFILES.md", "Virginia Coastal Plain"),
    ("Hudson Valley profile file", "BETA5_TREE_PROFILES.md", "Hudson Valley Mixed Forest"),
    ("Monterey Bay Coast profile file", "BETA5_TREE_PROFILES.md", "Monterey Bay Coast"),
    ("Equal multi-course weighting", "tree_profile_analyzer.py", "def equal_course_weight(asset_path):"),
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
    assert texas.get("visual_material_preset")
    assert texas.get("display_name") == "Texas Hill Country"
    assert len(texas.get("assets", [])) == 51
    assert texas.get("excluded_vertical_massing_count") == 1770
    assert texas.get("natural_reference_tree_count") == 1181
    print("PASS - Texas Hill Country enabled profile")
except Exception as exc:
    print("FAIL - Texas Hill Country enabled profile -", exc)
    failed.append("Texas Hill Country enabled profile")

niagara_profile = ROOT / "tree_profiles" / "niagara_escarpment.json"
try:
    niagara = json.loads(niagara_profile.read_text(encoding="utf-8"))
    assert niagara.get("enabled") is True
    assert niagara.get("visual_material_preset")
    assert niagara.get("display_name") == "Niagara Escarpment"
    assert niagara.get("weighting_method") == "equal_per_course"
    assert len(niagara.get("assets", [])) == 40
    print("PASS - Niagara Escarpment enabled profile")
except Exception as exc:
    print("FAIL - Niagara Escarpment enabled profile -", exc)
    failed.append("Niagara Escarpment enabled profile")

virginia_profile = ROOT / "tree_profiles" / "virginia_coastal_plain.json"
try:
    virginia = json.loads(virginia_profile.read_text(encoding="utf-8"))
    assert virginia.get("enabled") is True
    assert virginia.get("visual_material_preset")
    assert virginia.get("display_name") == "Virginia Coastal Plain"
    assert virginia.get("natural_reference_tree_count") == 2296
    assert virginia.get("excluded_vertical_massing_count") == 1331
    assert len(virginia.get("assets", [])) == 36
    print("PASS - Virginia Coastal Plain enabled profile")
except Exception as exc:
    print("FAIL - Virginia Coastal Plain enabled profile -", exc)
    failed.append("Virginia Coastal Plain enabled profile")

carolina_profile = ROOT / "tree_profiles" / "carolina_piedmont_autumn.json"
try:
    carolina = json.loads(carolina_profile.read_text(encoding="utf-8"))
    assert carolina.get("enabled") is True
    assert carolina.get("visual_material_preset")
    assert carolina.get("display_name") == "Carolina Piedmont (Autumn)"
    assert carolina.get("seasonal_character") == "autumn"
    assert len(carolina.get("assets", [])) == 37
    print("PASS - Carolina Piedmont Autumn enabled profile")
except Exception as exc:
    print("FAIL - Carolina Piedmont Autumn enabled profile -", exc)
    failed.append("Carolina Piedmont Autumn enabled profile")

hudson_profile = ROOT / "tree_profiles" / "hudson_valley_mixed_forest.json"
try:
    hudson = json.loads(hudson_profile.read_text(encoding="utf-8"))
    assert hudson.get("enabled") is True
    assert hudson.get("visual_material_preset")
    assert hudson.get("display_name") == "Hudson Valley Mixed Forest"
    assert hudson.get("natural_reference_tree_count") == 1063
    assert hudson.get("excluded_vertical_massing_count") == 2141
    assert len(hudson.get("assets", [])) == 44
    print("PASS - Hudson Valley Mixed Forest enabled profile")
except Exception as exc:
    print("FAIL - Hudson Valley Mixed Forest enabled profile -", exc)
    failed.append("Hudson Valley Mixed Forest enabled profile")

northern_rockies_profile = ROOT / "tree_profiles" / "northern_rockies_montane.json"
try:
    northern_rockies = json.loads(northern_rockies_profile.read_text(encoding="utf-8"))
    assert northern_rockies.get("enabled") is True
    assert northern_rockies.get("visual_material_preset")
    assert northern_rockies.get("display_name") == "Northern Rockies"
    assert northern_rockies.get("natural_reference_tree_count") == 7219
    assert northern_rockies.get("excluded_vertical_massing_count") == 1831
    assert len(northern_rockies.get("assets", [])) == 19
    print("PASS - Northern Rockies enabled profile")
except Exception as exc:
    print("FAIL - Northern Rockies enabled profile -", exc)
    failed.append("Northern Rockies enabled profile")

monterey_profile = ROOT / "tree_profiles" / "monterey_bay_coast.json"
try:
    monterey = json.loads(monterey_profile.read_text(encoding="utf-8"))
    assert monterey.get("enabled") is True
    assert monterey.get("display_name") == "Monterey Bay Coast"
    assert monterey.get("natural_reference_tree_count") == 2221
    assert monterey.get("excluded_vertical_massing_count") == 505
    assert len(monterey.get("assets", [])) == 49
    materials = monterey.get("visual_material_preset", {})
    assert materials.get("surfaces2", [])[0].get("name") == "Sand07"
    assert materials.get("surfaces2", [])[6].get("name") == "Green10"
    assert materials.get("surfaces2", [])[8].get("name") == "Fairway10"
    assert materials.get("surfaces2", [])[11].get("name") == "Splat0_TorreyPines"
    print("PASS - Monterey Bay Coast enabled profile + donor materials")
except Exception as exc:
    print("FAIL - Monterey Bay Coast enabled profile -", exc)
    failed.append("Monterey Bay Coast enabled profile")

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
