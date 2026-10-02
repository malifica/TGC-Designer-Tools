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
    ("Tree profile GUI selector", "tgc_gui.py", 'text="Regional Theme (Designer + Trees + Materials)"'),
    ("Tree scale GUI selector", "tgc_gui.py", 'text="Tree Scale"'),
    ("Heroic default", "tgc_gui.py", 'tree_scale_mode_var.set(tree_profile_manager.HEROIC_SCALE_MODE)'),
    ("Profile loader", "tree_profile_manager.py", "def load_profiles("),
    ("No-tree profile support", "tree_profile_manager.py", 'tree_generation not in ("profile", "none")'),
    ("Material preset loader", "tree_profile_manager.py", "visual_material_preset"),
    ("Material preset apply helper", "tree_profile_manager.py", "def apply_visual_material_preset("),
    ("Designer theme profile support", "tree_profile_manager.py", 'target_json["courseTheme"]'),
    ("Analyzer captures donor Designer theme", "tree_profile_analyzer.py", 'preset["theme"] = course.get("theme")'),
    ("Regional theme GUI label", "tgc_gui.py", 'text="Regional Theme (Designer + Trees + Materials)"'),
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
    ("Georgia Piedmont profile file", "BETA5_TREE_PROFILES.md", "Georgia Piedmont"),
    ("San Francisco Peninsula profile file", "BETA5_TREE_PROFILES.md", "San Francisco Peninsula"),
    ("Bass Strait Coastal Links profile file", "BETA5_TREE_PROFILES.md", "Bass Strait Coastal Links"),
    ("South Carolina Lowcountry profile file", "BETA5_TREE_PROFILES.md", "South Carolina Lowcountry"),
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
    assert texas.get("visual_material_preset", {}).get("theme") == 10
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
    assert niagara.get("visual_material_preset", {}).get("theme") == 14
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
    assert virginia.get("visual_material_preset", {}).get("theme") == 11
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
    assert carolina.get("visual_material_preset", {}).get("theme") == 14
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
    assert hudson.get("visual_material_preset", {}).get("theme") == 11
    assert hudson.get("display_name") == "Hudson Valley Mixed Forest"
    assert hudson.get("natural_reference_tree_count") == 1063
    assert hudson.get("excluded_vertical_massing_count") == 2141
    assert len(hudson.get("assets", [])) == 44
    print("PASS - Hudson Valley Mixed Forest enabled profile")
except Exception as exc:
    print("FAIL - Hudson Valley Mixed Forest enabled profile -", exc)
    failed.append("Hudson Valley Mixed Forest enabled profile")

northern_rockies_profile = ROOT / "tree_profiles" / "northern_rockies.json"
try:
    northern_rockies = json.loads(northern_rockies_profile.read_text(encoding="utf-8"))
    assert northern_rockies.get("enabled") is True
    assert northern_rockies.get("visual_material_preset")
    assert northern_rockies.get("visual_material_preset", {}).get("theme") == 12
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
    assert materials.get("theme") == 5
    assert materials.get("surfaces2", [])[0].get("name") == "Sand07"
    assert materials.get("surfaces2", [])[6].get("name") == "Green10"
    assert materials.get("surfaces2", [])[8].get("name") == "Fairway10"
    assert materials.get("surfaces2", [])[11].get("name") == "Splat0_TorreyPines"
    print("PASS - Monterey Bay Coast enabled profile + donor materials")
except Exception as exc:
    print("FAIL - Monterey Bay Coast enabled profile -", exc)
    failed.append("Monterey Bay Coast enabled profile")

south_carolina_profile = ROOT / "tree_profiles" / "south_carolina_lowcountry.json"
try:
    south_carolina = json.loads(south_carolina_profile.read_text(encoding="utf-8"))
    assert south_carolina.get("enabled") is True
    assert south_carolina.get("display_name") == "South Carolina Lowcountry"
    assert south_carolina.get("natural_reference_tree_count") == 1694
    assert south_carolina.get("excluded_vertical_massing_count") == 1035
    assert len(south_carolina.get("assets", [])) == 34
    materials = south_carolina.get("visual_material_preset", {})
    assert materials.get("theme") == 10
    assert materials.get("surfaces2", [])[0].get("name") == "Sand34_DetroitGC"
    assert materials.get("surfaces2", [])[6].get("name") == "Green46_Pinehurst"
    assert materials.get("surfaces2", [])[8].get("name") == "Fairway46_Pinehurst"
    print("PASS - South Carolina Lowcountry enabled profile + donor materials")
except Exception as exc:
    print("FAIL - South Carolina Lowcountry enabled profile -", exc)
    failed.append("South Carolina Lowcountry enabled profile")

georgia_profile = ROOT / "tree_profiles" / "georgia_piedmont.json"
try:
    georgia = json.loads(georgia_profile.read_text(encoding="utf-8"))
    assert georgia.get("enabled") is True
    assert georgia.get("display_name") == "Georgia Piedmont"
    assert georgia.get("natural_reference_tree_count") == 3628
    assert georgia.get("excluded_vertical_massing_count") == 1056
    assert len(georgia.get("assets", [])) == 42
    materials = georgia.get("visual_material_preset", {})
    assert materials.get("theme") == 7
    assert materials.get("surfaces2", [])[0].get("name") == "Sand17"
    assert materials.get("surfaces2", [])[6].get("name") == "Green40_TorreyPines"
    assert materials.get("surfaces2", [])[8].get("name") == "Fairway40_TorreyPines"
    print("PASS - Georgia Piedmont enabled profile + donor Designer theme/materials")
except Exception as exc:
    print("FAIL - Georgia Piedmont enabled profile -", exc)
    failed.append("Georgia Piedmont enabled profile")

san_francisco_profile = ROOT / "tree_profiles" / "san_francisco_peninsula.json"
try:
    san_francisco = json.loads(san_francisco_profile.read_text(encoding="utf-8"))
    assert san_francisco.get("enabled") is True
    assert san_francisco.get("display_name") == "San Francisco Peninsula"
    assert san_francisco.get("natural_reference_tree_count") == 751
    assert san_francisco.get("excluded_vertical_massing_count") == 602
    assert len(san_francisco.get("assets", [])) == 40
    materials = san_francisco.get("visual_material_preset", {})
    assert materials.get("theme") == 13
    assert materials.get("surfaces2", [])[6].get("name") == "Green50_StAndrews"
    assert materials.get("surfaces2", [])[8].get("name") == "Fairway50_StAndrews"
    assert materials.get("surfaces2", [])[12].get("name") == "Splat1_EastLakeGC"
    print("PASS - San Francisco Peninsula enabled profile + donor Designer theme/materials")
except Exception as exc:
    print("FAIL - San Francisco Peninsula enabled profile -", exc)
    failed.append("San Francisco Peninsula enabled profile")

bass_strait_profile = ROOT / "tree_profiles" / "bass_strait_coastal_links.json"
try:
    bass_strait = json.loads(bass_strait_profile.read_text(encoding="utf-8"))
    assert bass_strait.get("enabled") is True
    assert bass_strait.get("display_name") == "Bass Strait Coastal Links"
    assert bass_strait.get("tree_generation") == "none"
    assert bass_strait.get("all_speedtree_tree_count") == 0
    assert bass_strait.get("assets") == []
    materials = bass_strait.get("visual_material_preset", {})
    assert materials.get("theme") == 15
    assert len(materials.get("surfaces2", [])) == 15
    print("PASS - Bass Strait Coastal Links intentional no-tree profile")
except Exception as exc:
    print("FAIL - Bass Strait Coastal Links profile -", exc)
    failed.append("Bass Strait Coastal Links profile")

try:
    import tree_profile_manager
    tree_profile_manager.load_profiles(force=True)
    no_tree = tree_profile_manager.get_profile("Bass Strait Coastal Links")
    assert no_tree is not None
    assert no_tree.get("tree_generation") == "none"
    assert no_tree.get("assets") == []
    assert tree_profile_manager.choose_asset(no_tree) is None
    print("PASS - no-tree regional profile runtime behavior")
except Exception as exc:
    print("FAIL - no-tree regional profile runtime behavior -", exc)
    failed.append("no-tree regional profile runtime behavior")

try:
    import tree_profile_manager
    tree_profile_manager.load_profiles(force=True)
    test_course = {"theme": 2}
    tree_profile_manager.apply_visual_material_preset(
        test_course, "Georgia Piedmont", printf=lambda *_args: None
    )
    assert test_course.get("theme") == 7
    test_metadata = {"courseTheme": 2}
    tree_profile_manager.apply_visual_material_preset(
        test_metadata, "Georgia Piedmont", printf=lambda *_args: None, metadata=True
    )
    assert test_metadata.get("courseTheme") == 7
    print("PASS - regional theme overrides source Designer theme")
except Exception as exc:
    print("FAIL - regional Designer theme override -", exc)
    failed.append("regional Designer theme override")

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
