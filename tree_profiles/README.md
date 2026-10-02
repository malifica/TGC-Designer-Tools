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


## Uniform Designer scaling

If a finished reference course uses the same X/Y/Z scale for a prefab instance,
the analyzer writes a compact `uniform_scale` p10/p50/p90 distribution. The
runtime applies that distribution to all three axes while still mapping LiDAR
radius and height percentiles independently.

The analyzer only treats actual `Assets/Foliage/SpeedTree...` tree prefabs as
tree samples. Course-detail props such as fallen logs are excluded.


### Texas Hill Country

The first enabled Beta 5 real-life test profile is **Texas Hill Country**, calibrated
from `Canyon Springs SATX (L).course`.

The test pool uses the 51 most-used non-ornamental foliage prefabs, representing
**2,668 placements / 90.4%** of the retained planted-tree population. Contextual
Crape Myrtle, Chinese Fan Palm, Silver Maple, fallen-tree detail props, and the
long tail of very rare assets are excluded from the first random LiDAR/OSM test.

The profile preserves the reference course's observed per-prefab uniform scale
p10/p50/p90 values and raw usage counts as selection weights.
