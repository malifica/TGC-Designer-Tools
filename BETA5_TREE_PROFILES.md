# Beta 5 regional tree profiles

Beta 5 introduced JSON-backed **Regional Theme** profiles for LiDAR/OSM vegetation.

Regional profiles can define:
- A curated SpeedTree asset palette and weighted planting mix.
- Normal/skinny tree-shape behavior.
- Calibrated X/Y/Z scale distributions.
- A coordinated Designer theme and playing-surface/terrain material preset.
- Optional profile-specific tree-generation behavior.

Enabled regional profiles include Texas Hill Country, Niagara Escarpment, Carolina Piedmont (Autumn), Virginia Coastal Plain, Hudson Valley Mixed Forest, Northern Rockies, Monterey Bay Coast, Georgia Piedmont, San Francisco Peninsula, and South Carolina Lowcountry.

The profile files intentionally describe the regional result without source attribution. Asset names are treated as in-game visual analogs rather than literal botanical claims.

## Tree placement filtering

Regional profiles work with the LiDAR/OSM tree-placement pipeline. Terrain-aligned natural placements are retained while vertically displaced scenery/massing placements are excluded from calibration and automatic placement behavior.

## Materials

A regional profile may also provide a root Designer theme plus bunker, green, fringe, fairway, rough, heavy-rough, and terrain material selections. These settings are applied as a coordinated regional visual preset.

## Scale behavior

Standard LiDAR behavior remains available alongside larger calibrated tree-size modes. Regional scale distributions are applied consistently across the supported LiDAR/OSM tree workflows.
