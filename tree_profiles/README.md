# Regional tree profiles

This directory contains the JSON-backed Regional Theme profiles used by TGC Designer Tools.

Each profile can define:
- `id` and `display_name`
- whether the profile is enabled
- tree-generation behavior
- a regional tree asset palette
- normal/skinny shape classification
- weighted asset selection
- retained historical X/Y/Z or uniform scale statistics (not used for generated tree sizing)
- an optional Designer theme and playing-surface/terrain material preset

The repository intentionally stores the finished regional profile data without source attribution.

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
- Pacific Northwest

## Tree generation

Profiles with normal automatic generation provide weighted SpeedTree selections for LiDAR/OSM tree candidates. A profile may explicitly disable automatic tree generation when that is more appropriate for the regional landscape.

## Scale data

Historical scale statistics may remain in the JSON for compatibility, but are not used to size generated trees. All palettes share the established LiDAR crown-radius/height mapping. Standard and Heroic retain their existing ranges; Epic is 1.20 x Heroic and Mythic is 1.80 x Heroic. OSM-only candidates use the common built-in fallback instead of profile-specific scale distributions.

## Material presets

Regional profiles may carry a coordinated Designer theme and surface/terrain material configuration. These settings are applied independently of the starting template so the chosen regional look remains consistent.
