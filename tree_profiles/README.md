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


## Buried / raised scenery filtering

Finished Designer courses often use oversized trees or foliage partially buried
under terrain to create dense off-course forest/hedge boundaries. Those objects are
scenery construction, not representative individual trees, and are excluded by
default from future theme calibration.

Terrain-snapped objects (`position.y = -Infinity`) are retained. Finite-Y objects
are compared with reconstructed detailed terrain and background+detail terrain; if
neither is within the default **0.75 m** tolerance, the object is excluded from the
theme's prefab weights and scale statistics. Use `--keep-manual-height` only for
diagnostics or an intentional exception.

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

The recalibrated reference contains **1,181 natural / terrain-aligned non-ornamental
tree placements**. The first test pool uses the 51 most-used prefabs, representing
**1,064 placements / 90.1%** of that natural reference population.

A major reference-course bias was removed: **1,770 vertically manipulated tree
placements** were identified as buried/raised scenery or off-course boundary massing
and are excluded from the regional theme calculation. Finite-Y tree objects must be
within **±0.75 m** of reconstructed terrain to count as natural planting. Normal
terrain-snapped (`-Infinity` Y) trees remain eligible.

Contextual Crape Myrtle, Chinese Fan Palm, and Silver Maple placements are also
excluded from random Texas Hill Country LiDAR/OSM distribution.

The revised core profile's overall Designer scale p10 / p50 / p90 is approximately
**0.500 / 1.000 / 1.347**.


## Multi-course profile weighting

When more than one finished course is supplied for a regional profile, each course
contributes **equally** to the prefab-use matrix before the final weights are
combined. This prevents a densely planted course from overwhelming a more sparsely
planted reference course simply because it contains more tree objects.

Per-prefab scale statistics still use the valid natural placements of that prefab.
The profile-level fallback p10/p50/p90 scale values are averaged across the
reference courses so one dense course does not dominate fallback scale behavior.


### Niagara Escarpment

**Niagara Escarpment** is the second enabled Beta 5 regional test profile, calibrated
from The Pulpit Club's Devil's Paintbrush and Devil's Pulpit courses.

The two courses use dramatically different golf/planting styles, so their tree-use
matrices are combined with **50/50 per-course weighting** rather than pooling raw
tree counts.

After removing vertically buried/raised scenery-massing trees:

- Devil's Paintbrush contributes **57** natural / terrain-aligned trees from **14** prefabs;
- Devil's Pulpit contributes **534** natural / terrain-aligned trees from **54** prefabs;
- **326** Paintbrush and **1,480** Pulpit vertically manipulated scenery trees are excluded;
- the enabled core profile uses **40 prefabs**, covering **95.6%** of the equal-weighted combined mix;
- the equal-course fallback Designer scale p10 / p50 / p90 is approximately **0.821 / 1.611 / 2.397**.

Conifer, pine, spruce, and Lombardy-poplar forms are initially treated as skinny;
broadleaf birch, maple, ash, aspen, elm, plane, beech and similar forms are normal.


## Reference-course acceptance log

Courses that have been geographically identified and inspected but rejected or
deferred as tree-profile calibration sources are tracked in
`tree_profiles/REFERENCE_COURSE_REVIEWS.md`.


### Virginia Coastal Plain

**Virginia Coastal Plain** is the third enabled Beta 5 regional profile, calibrated
from `RNK(3).course` / Royal New Kent in Providence Forge, Virginia.

After filtering buried/raised scenery-massing trees:

- **2,296** natural / terrain-aligned tree placements are retained;
- **1,331** vertically manipulated scenery-massing tree placements are excluded;
- the enabled core profile uses **36 prefabs** representing **2,193 trees / 95.5%**
  of the natural retained population;
- core Designer scale p10 / p50 / p90 is approximately
  **0.811 / 1.202 / 1.649**.

The profile intentionally treats the course as a **visual pine-hardwood regional
reference**, not a literal botanical inventory. Some game prefab names such as
Scots Pine, Slash Pine, Monterey Cypress or Southern Live Oak are retained where
their in-game form contributes convincingly to the Virginia Coastal Plain look.


### Carolina Piedmont (Autumn)

**Carolina Piedmont (Autumn)** is calibrated from Tot Hill Farm in Asheboro,
North Carolina, in the Uwharrie / Carolina Piedmont landscape.

After removing vertically manipulated scenery massing, the reference contributes
**837 natural / terrain-aligned trees**. The enabled core profile uses the **37**
most-used prefabs, representing **799 placements / 95.5%** of the natural
reference population.

This profile is explicitly seasonal: **83.6%** of all retained natural placements
and **86.6%** of the core pool use fall/autumn prefab variants. A future green-leaf
Carolina Piedmont reference should become a separate non-autumn profile rather than
silently mixing seasonal asset colors.
