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

- 2,668 planted tree instances represented in the initial profile
- 51 core tree prefabs
- 90.4% coverage of the retained non-ornamental reference population
- overall Designer scale p10 / p50 / p90: **0.530 / 1.000 / 1.286**
- oak-dominant weighted mix, with mesquite and drought-tolerant accent forms
- contextual Crape Myrtle, Chinese Fan Palm and Silver Maple placements excluded
  from random LiDAR/OSM distribution

This is intentionally a first-pass regional planting profile for in-game testing.
After we inspect the generated result, we can split a dedicated skinny/juniper pool,
adjust species weights, or bring selected rare assets back into the profile.
