# Beta 5 development — real-life tree planting profiles

Beta 5 begins a new tree-generation system for the **main TGCTool**.

The goal is to let finished real-world courses define reusable planting profiles
instead of relying only on the game's built-in visual themes.

Initial target profile families:

- **Piney Woods**
- **Monterey Peninsula**
- **Upstate New York**
- **Scotland**
- **Florida**

These are planning targets until reference courses have been analyzed and reviewed.

## Why this belongs in the main tool

When LiDAR / OSM tree candidates are converted into placed objects, TGCTool still
knows the LiDAR position, canopy radius, approximate physical height, and tree
shape. That is the right time to select the prefab and Designer-like scale.

## Heroic scale

The historical LiDAR mapping used approximately X/Z **0.20–1.50** and Y
**0.50–1.20**.

The first Beta 5 Heroic test mapping is X/Z **0.70–1.65** and Y **0.85–1.55**.
Legacy LiDAR scaling remains selectable while we tune this.

## Excluding scenery-massing trees

Real-world profile calibration now distinguishes normal planted trees from a common
Designer scenery technique: oversized trees/foliage translated downward into the
terrain to form dense off-course overgrowth, hedges, or unmanaged forest walls.

These vertically manipulated objects are excluded by default. Terrain-snapped trees
remain eligible; finite-Y trees must be within **±0.75 m** of reconstructed terrain.
This rule applies to Texas Hill Country and to all future reference-course analyses.

## Calibrating a real-life profile

```bat
python tree_profile_analyzer.py --name "Piney Woods" "Reference Course.course"
```

Multiple reference courses can be combined. The analyzer captures prefab counts,
usage weights, and X/Y/Z p10/p50/p90 scale statistics. Candidate profiles are
disabled until reviewed.

For LiDAR trees, detected radius/height percentiles are mapped into the finished
course's scale distribution. OSM trees use the weighted mix and median profile
scale because our OSM tree nodes do not currently carry trustworthy dimensions.

Enabled JSON profiles in `tree_profiles\` automatically appear in the GUI's
**Tree Planting Theme** selector.


## First calibrated test profile

**Texas Hill Country** is now enabled for Beta 5 development testing.

Reference: `Canyon Springs SATX (L).course`

- **1,181** natural / terrain-aligned non-ornamental reference trees retained
- **1,770** vertically manipulated boundary/scenery tree placements excluded
- **1,064** placements in the 51-prefab first-test pool
- **90.1%** coverage of the natural retained population
- core Designer scale p10 / p50 / p90: **0.500 / 1.000 / 1.347**
- contextual Crape Myrtle, Chinese Fan Palm and Silver Maple placements excluded
  from random LiDAR/OSM distribution

After we inspect the generated result, we can split a dedicated skinny/juniper pool,
adjust species weights, or bring selected rare natural assets back into the profile.


## Multi-course regional profiles

For regional themes built from multiple courses, Beta 5 uses **equal per-course
weighting** for the prefab-use matrix. This is important when reference courses have
very different planting densities or design styles.

The second enabled regional test profile is **Niagara Escarpment**, built from
The Pulpit Club's Devil's Paintbrush and Devil's Pulpit. Buried/raised scenery
massing is excluded from both courses before the two natural planting matrices are
combined 50/50.


## Reference-course sample guard

Beta 5 now prevents a visually elaborate but scenery-massing-dominant course from
silently becoming a regional **tree** profile when it contains too few genuine
terrain-aligned specimen trees.

By default a reference course needs at least **25 natural / terrain-aligned tree
instances** to contribute to the theme matrix. Courses below that threshold are
still analyzed and reported, but their prefab mix and scale values are excluded
from calibration unless an expert deliberately uses
`--allow-low-sample-reference`.

A course with fewer than 25% natural tree objects is also flagged as
**scenery-massing dominant**. That warning does not automatically exclude a course
if it still has at least 25 valid natural trees; Devil's Paintbrush is an example
where enough genuine trees remain despite extensive off-course massing.


## Virginia Coastal Plain

**Virginia Coastal Plain** is enabled from Royal New Kent in Providence Forge,
Virginia. Royal New Kent's natural retained planting matrix is strongly mixed
pine/hardwood, matching the real New Kent County Coastal Plain landscape.

The Beta 5 calibration retains **2,296** natural trees, excludes **1,331**
vertically manipulated scenery-massing trees, and uses a **36-prefab** core
representing **95.5%** of the natural population. The profile is visual rather
than taxonomically literal: visually useful non-local prefab labels are allowed
when they reproduce the regional pine-hardwood character in-game.


## Carolina Piedmont (Autumn)

Tot Hill Farm is used as the first Carolina Piedmont/Uwharrie reference. The course
sits in Asheboro, North Carolina and its natural planting mix is visually consistent
with the region's pine-hardwood / oak-hickory character.

The reference contains **3,044** actual SpeedTree tree objects. After Beta 5's
terrain-alignment filter:

- **837** natural / terrain-aligned trees remain;
- **2,207** buried/raised scenery-massing trees are excluded;
- the core profile uses **37 prefabs / 799 trees / 95.5%** coverage;
- core scale p10 / p50 / p90 is approximately **0.696 / 1.064 / 1.787**.

Because more than 80% of the retained planting uses explicit fall/autumn asset
variants, the enabled profile is intentionally named **Carolina Piedmont (Autumn)**
rather than a generic Carolina Piedmont theme.


## Hudson Valley Mixed Forest

**Hudson Valley Mixed Forest** is enabled from `Trump Nat(1).course`, identified
from its exact hole-par sequence and near-matching championship yardages as Trump
National Golf Club Hudson Valley in Hopewell Junction, Dutchess County, New York.

The reference contains **3,204** actual SpeedTree tree placements. After Beta 5's
terrain-alignment filter:

- **1,063** natural / terrain-aligned trees remain;
- **2,141** buried/raised scenery-massing trees are excluded;
- the enabled core profile uses **44 prefabs / 1,012 trees / 95.2%** coverage;
- core scale p10 / p50 / p90 is approximately **1.000 / 1.146 / 1.269**.

The retained visual mix is strongly eastern-deciduous: elm, white oak, red/silver
maple, ash, birch and beech, with a smaller white-pine/conifer component. Some
non-local prefab labels are intentionally retained as visual analogs rather than
literal botanical claims.
