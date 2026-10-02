# Beta 5 real-life tree profiles

This directory contains real-life planting profiles for the main TGCTool.

Planned profile families include Piney Woods, Monterey Peninsula, Upstate New York,
Scotland, and Florida. Only JSON files with `"enabled": true` appear in the GUI.
Files beginning with `_` are ignored by the runtime loader.

Analyze one or more fully planted reference courses with:

```bat
python tree_profile_analyzer.py --name "Piney Woods" "Course A.course" "Course B.course"
```

The analyzer records prefab counts/weights and X/Y/Z p10/p50/p90 scale statistics.
Generated candidates are disabled until their normal/skinny classification and
contents have been reviewed.

LiDAR candidates use their relative radius/height rank to map into the reference
course's Designer scale distribution. OSM tree nodes use the weighted profile mix
and median reference scale because current OSM tree nodes do not carry reliable
physical dimensions.
