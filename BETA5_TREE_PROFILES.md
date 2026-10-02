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


## Northern Rockies

**Northern Rockies** is enabled from `Moonlight Basin.course`, identified
as The Reserve at Moonlight Basin in Big Sky, Montana.

The reference contains **9,050** actual SpeedTree tree placements. After Beta 5's
terrain-alignment filter:

- **7,219** natural / terrain-aligned trees remain;
- **1,831** buried/raised scenery-massing trees are excluded;
- all **19** retained natural-placement prefabs are kept because the palette is
  already highly concentrated;
- the three Norway Spruce prefabs account for about **95.8%** of natural placements;
- scale p10 / p50 / p90 is approximately **0.837 / 0.999 / 1.171**.

The real Big Sky / Northern Rockies montane forest is spruce-fir-pine / Douglas-fir
country with lodgepole pine and aspen. The course's Norway Spruce and Scots Pine
prefabs are therefore treated as visual stand-ins rather than literal local species.
Rare dead-tree forms are retained at their observed low weights as appropriate
mountain-forest snags.


## Regional themes now include materials

Beta 5 regional themes are no longer tree-only. The selected donor course now
supplies the root Designer theme as well as the visible playing-surface and terrain
material set. TGCTool applies the donor `theme`, `surfaces2`,
`secondarySurfaces`, cart-path texture and tee texture to the target course.
At export, `CourseMetadata.courseTheme` is synchronized too, so the visual result
does not depend on which Designer theme the starting template happened to use.

That includes bunker, green, fringe, fairway, light rough, heavy rough, and all
four terrain/splat channels (the general soil/dirt/topsoil-style terrain texture
slots). The packed CourseMetadata is synchronized at export.

Existing enabled regional profiles were retrofitted from their original donors.
For Niagara Escarpment, Devil's Paintbrush is currently the material donor.

## Monterey Bay Coast

Pasatiempo Golf Club in Santa Cruz, California is the first regional theme built
after donor materials became part of the profile. Its reference retains **2,221**
natural trees, excludes **505** scenery-massing trees, and uses a
**49-prefab / 95.0%** tree core. Pasatiempo's bunker/turf/terrain texture set is
stored in the profile and applied together with its tree palette.


## South Carolina Lowcountry

**South Carolina Lowcountry** is calibrated from Caledonia Golf & Fish Club in
Pawleys Island, South Carolina. The donor is an 18-hole, par-70 course using the
Delta base theme, but its tree palette is read from actual placed SpeedTree objects
rather than from the built-in theme.

The reference contains **2,729** SpeedTree tree placements. After the Beta 5
terrain-alignment filter:

- **1,694** natural / terrain-aligned trees remain;
- **1,035** buried/raised scenery-massing trees are excluded;
- the enabled core uses **34 prefabs / 1,611 trees / 95.1%** coverage;
- fallback Designer scale p10 / p50 / p90 is approximately
  **0.763 / 1.080 / 1.541**.

The retained mix is strongly Lowcountry: about **67% pine/conifer visual forms**
and **33% live-oak/oak forms**, with numerous Spanish-moss live-oak assets. This
matches Caledonia's real Pawleys Island character of mature live oaks and Southern
pines.

Caledonia explicitly supplies **Sand34_DetroitGC** bunkers,
**Green46_Pinehurst** greens, **Fringe46_Pinehurst**,
**Fairway46_Pinehurst**, **LightRough43_RenaissanceClub**, and
**HeavyRough19_TPC_Boston**. Its terrain/splat slots 11-14 are unnamed and
therefore depend on the donor's Delta theme defaults. Beta 5 preserves the exact slot structures and applies Caledonia's Delta root
Designer theme, so those unnamed terrain defaults resolve as they do in the donor.


## Georgia Piedmont

**Georgia Piedmont** is calibrated from Peachtree Golf Club in Atlanta, Georgia.
The 18-hole, par-72 donor uses Designer theme **7 (Countryside)** and its regional
profile carries that root theme along with its trees and explicit materials.

The reference contains **4,684** SpeedTree placements. After terrain-alignment
filtering, **3,628** natural / terrain-aligned trees remain and **1,056**
buried/raised scenery-massing trees are excluded. The enabled core uses
**42 prefabs / 3,466 trees / 95.5%** coverage, with fallback Designer scale
p10 / p50 / p90 approximately **0.627 / 0.908 / 1.215**.

The core is strongly pine-led (about **84%** narrow pine/conifer visual forms) with
ash, elm, beech and oak supplying the principal hardwood component. Peachtree's
explicit materials are **Sand17**, **Green40_TorreyPines**,
**Fringe40_TorreyPines**, **Fairway40_TorreyPines**, **LightRough06**, and
**HeavyRough06**. Its unnamed terrain/splat slots now resolve under the copied
Countryside root theme rather than the starting template's theme.


## San Francisco Peninsula

**San Francisco Peninsula** is calibrated from California Golf Club of San
Francisco in South San Francisco, California. The donor is an 18-hole, par-72
course using Designer theme **13 (Steppe)**, and the regional preset carries that
root theme together with the donor's tree matrix and material selections.

The reference contains **1,353** SpeedTree tree placements. After Beta 5's
terrain-alignment filter:

- **751** natural / terrain-aligned trees remain;
- **602** buried/raised scenery-massing trees are excluded;
- the enabled core uses **40 prefabs / 715 trees / 95.2%** coverage;
- fallback Designer scale p10 / p50 / p90 is approximately
  **0.715 / 0.985 / 1.360**.

The retained core is approximately **98% pine/cypress visual forms**, including a
substantial Monterey-cypress component. That makes this intentionally distinct from
the broader **Monterey Bay Coast** profile derived from Pasatiempo.

The donor explicitly supplies **Green50_StAndrews**, **Fringe50_StAndrews**,
**Fairway50_StAndrews**, **LightRough46_Pinehurst** and
**HeavyRough50_StAndrews**. It also explicitly selects
**Splat1_EastLakeGC / Splat2_RivieraCC / Splat3_Swiss**. Bunker slot 0 and
terrain slot 11 remain unnamed theme defaults, so the copied **Steppe (13)** root
Designer theme is required for the complete donor look.


## Intentional no-tree regional themes

Some real coastal courses are not tree landscapes at all. Beta 5 now supports
`"tree_generation": "none"` for reviewed regional profiles whose donor and
real-world environment are intentionally open, treeless links/heath.

These profiles still apply the donor root Designer theme and material structures,
but automatic LiDAR/OSM tree candidates do not become tree prefabs. This avoids
inventing a specimen-tree palette merely to satisfy the profile schema. Low scrub,
heath, dune grasses and similar vegetation remain a separate future massing/scrub
system.

## Coastal Links

**Coastal Links** is calibrated from Cape Wickham Golf Links on King
Island, Tasmania. The donor is an 18-hole, par-72 course using Designer theme
**15 (Highlands)**.

The course file contains **zero placed tree objects** and no explicitly named
`surfaces2` or `secondarySurfaces` material names. That result is treated as
intentional rather than as a failed tree donor because Cape Wickham is a pure,
windswept coastal links environment.

The enabled profile therefore uses:

- `tree_generation = "none"`;
- **Highlands (15)** as the authoritative root Designer theme;
- the donor's exact default `surfaces2` / `secondarySurfaces` structures;
- no invented tree assets.

This is intended to represent exposed Bass Strait links terrain until Beta 5 gains
a dedicated coastal-heath/scrub palette for low shrubs, pigface, grasses and other
wind-pruned vegetation.
