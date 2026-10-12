# Regional tree profiles

This directory contains the JSON-backed Regional Theme profiles used by TGC Designer Tools.

Each profile can define:
- `id` and `display_name`
- whether the profile is enabled
- tree-generation behavior
- a regional tree asset palette
- normal/skinny shape classification
- weighted asset selection
- calibrated X/Y/Z or uniform scale ranges
- an optional Designer theme and playing-surface/terrain material preset

The repository intentionally stores the finished regional profile data without identifying calibration/source courses.

## Available profiles

Current profiles include:
- Texas Hill Country
- Niagara Escarpment
- Carolina Piedmont (Autumn)
- Virginia Coastal Plain
- Hudson Valley Mixed Forest
- Northern Rockies
- Monterey Bay Coast
- Georgia Piedmont
- San Francisco Peninsula
- South Carolina Lowcountry
- Coastal Links
- Pacific Northwest when included by the active release package

## Tree generation

Profiles with normal automatic generation provide weighted SpeedTree selections for LiDAR/OSM tree candidates. A profile may explicitly disable automatic tree generation when that is more appropriate for the regional landscape.

## Scale data

Scale distributions are stored per asset or as profile defaults. Standard, Heroic, Epic, and Mythic modes apply the configured profile scaling rules without changing the selected regional asset palette.

## Material presets

Regional profiles may carry a coordinated Designer theme and surface/terrain material configuration. These settings are applied independently of the starting template so the chosen regional look remains consistent.
