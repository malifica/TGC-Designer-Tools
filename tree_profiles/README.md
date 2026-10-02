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


### Hudson Valley Mixed Forest

**Hudson Valley Mixed Forest** is calibrated from `Trump Nat(1).course`, the
Hudson Valley course in Hopewell Junction, New York.

After removing vertically manipulated scenery massing, **1,063** natural /
terrain-aligned trees remain from **3,204** actual SpeedTree placements. The enabled
core profile uses **44 prefabs**, representing **1,012 placements / 95.2%** of the
natural reference population.

The profile is dominated by elm, oak, red/silver maple, ash, birch and beech forms,
with a smaller eastern-white-pine / conifer component. The overall core Designer
scale p10 / p50 / p90 is approximately **1.000 / 1.146 / 1.269**.


### Northern Rockies

Calibrated from The Reserve at Moonlight Basin in Big Sky, Montana. The enabled
profile retains **7,219** natural / terrain-aligned trees and excludes **1,831**
vertically manipulated scenery-massing trees. The natural palette is extremely
focused: three Norway Spruce prefab variants account for about **95.8%** of the
retained planting, with smaller Douglas-fir, Scots-pine, generic-conifer,
deciduous/aspen-like analog, and dead-snag components.

All **19** retained natural-placement prefabs are preserved in the profile.


## Donor surface and terrain materials

Beta 5 regional profiles now carry the donor course's root Designer theme and
visible material selection, not just its tree mix. Selecting a regional theme
replaces the starting template's Designer theme and applies the donor's bunker,
green, fringe, fairway, rough, heavy-rough and terrain/splat materials.

The runtime copies `theme`, `surfaces2`, `secondarySurfaces`,
`cartPathTexture`, and `teeTexture` into the target CourseDescription. At
export it mirrors `surfaces2` and the root theme into
`CourseMetadata.surfaces2` / `CourseMetadata.courseTheme` so the packed course
remains consistent.

For 2K25 `surfaces2`, the material slots used by the regional-theme system are:
0 bunker; 6 green; 7 fringe; 8 fairway; 9 light rough; 10 heavy rough; and 11-14
the four general terrain/splat channels used for soil/dirt/topsoil-style terrain
textures.

All existing Beta 5 regional themes have been retrofitted from their original
donor courses. Niagara Escarpment currently uses Devil's Paintbrush as its
material donor while its tree matrix still uses both Paintbrush and Pulpit.


### Monterey Bay Coast

**Monterey Bay Coast** is calibrated from Pasatiempo Golf Club in Santa Cruz,
California. The reference retains **2,221** natural / terrain-aligned trees,
excludes **505** vertically manipulated scenery-massing trees, and uses a
**49-prefab / 2,111-tree / 95.0%** core.

Its donor materials are preserved with the regional theme: **Sand07** bunkers,
**Green10** greens, **Fringe10**, **Fairway10**, **LightRough46_Pinehurst**,
**HeavyRough09**, and the terrain channels **Splat0_TorreyPines /
Splat1_Steppe / Splat2_TorreyPines / Splat3_Harvest**.


### South Carolina Lowcountry

**South Carolina Lowcountry** is calibrated from `Caledonia 2K25_Standard.course`,
representing Caledonia Golf & Fish Club in Pawleys Island, South Carolina.

After scenery-massing filtering, **1,694** natural trees remain from **2,729**
SpeedTree placements and **1,035** buried/raised trees are excluded. The enabled
core uses **34 prefabs / 1,611 trees / 95.1%** coverage, with fallback Designer
scale p10 / p50 / p90 of approximately **0.763 / 1.080 / 1.541**.

The retained palette is dominated by Southern-pine analogs and Spanish-moss
Southern-live-oak forms, making it intentionally distinct from Virginia Coastal
Plain and Carolina Piedmont (Autumn).

Caledonia provides explicit bunker and turf material names. Its four terrain/splat
slots are unnamed Delta-theme defaults, so the profile records the exact slot
structures and applies Caledonia's Delta root Designer theme to resolve them.


### Georgia Piedmont

**Georgia Piedmont** is calibrated from `PeachTree_ADAPTIVE(1).course`, identified
as Peachtree Golf Club in Atlanta, Georgia.

The reference contains **4,684** SpeedTree placements. After the Beta 5
terrain-alignment filter, **3,628** natural trees remain and **1,056**
buried/raised scenery trees are excluded. The enabled core uses **42 prefabs /
3,466 trees / 95.5%** coverage with fallback scale p10 / p50 / p90 approximately
**0.627 / 0.908 / 1.215**.

The palette is strongly pine-led with a smaller mature hardwood component. The
profile also applies Peachtree's **Countryside (theme 7)** root Designer theme,
making its unnamed terrain/splat defaults independent of the starting template.


### San Francisco Peninsula

**San Francisco Peninsula** is calibrated from `Cali Club (1)(1).course`,
identified as California Golf Club of San Francisco in South San Francisco,
California.

The donor contains **1,353** SpeedTree placements. After scenery-massing
filtering, **751** natural trees remain and **602** buried/raised trees are
excluded. The enabled core uses **40 prefabs / 715 trees / 95.2%** coverage,
with fallback scale p10 / p50 / p90 of approximately
**0.715 / 0.985 / 1.360**.

Its natural core is approximately **98% pine/cypress visual forms**, with Monterey
Cypress especially prominent. The profile applies the donor's **Steppe (theme 13)**
root Designer theme as well as its explicit turf and terrain materials, ensuring
unnamed theme-default slots do not depend on the starting template.


## Intentional no-tree profiles

A reviewed regional profile may set `"tree_generation": "none"` and use an empty
`assets` array. This is reserved for environments that are intentionally not
tree landscapes, such as exposed coastal links/heath. The profile still applies
the donor Designer theme and materials; automatic LiDAR/OSM tree candidates are
suppressed instead of being mapped to a fabricated tree palette.

### Coastal Links

**Coastal Links** is calibrated from
`Cape Wickham 1.0 Adaptive(3).course`, identified as Cape Wickham Golf Links on
King Island, Tasmania.

The donor contains **0 placed SpeedTree trees**, and its surface/terrain material
slots are unnamed defaults. The profile therefore applies **Highlands (theme 15)**
as the authoritative donor environment and sets `tree_generation = "none"`.

This matches the course's exposed links character while leaving coastal heath,
scrub, pigface and dune-grass generation for the future massing/scrub system rather
than misclassifying those forms as specimen trees.


## Separate root and tree themes

A regional profile may set `tree_generation` to `"designer_theme"` and provide
a separate `tree_theme_id`. This allows the root Designer environment to come
from one theme while automatic tree generation uses another theme's 2K25 tree
palette.

Example: `visual_material_preset.theme = 14` keeps Autumn procedural/background
grass and unnamed visual defaults, while `tree_theme_id = 54` generates trees
from the full Fjordland tree lists.

The packed course still has only one root Designer theme ID. The split is performed
by TGCTool because generated trees are explicit `placedObjects4` prefab paths.
