# Beta 6 regional trees and size modes

## Tree-size selector

Beta 6 uses four simple labels:

1. **Standard (Lidar)** — the established LiDAR size calculation.
2. **Heroic** — the established larger LiDAR-derived size mapping.
3. **Epic** — exactly `1.20 × Heroic`.
4. **Mythic** — exactly `1.80 × Heroic`.

Built-in Designer themes and regional profiles share the same LiDAR crown-radius/height calculation. Epic and Mythic multiply that shared Heroic X/Y/Z result. Regional profile scale data does not override it. Heroic remains the default.

This is the established source-population mapping to native transform scales, not physical per-prefab metre calibration. Theme selection changes the model palette; identical accepted LiDAR measurements and mode produce identical transform scales.

## Pacific Northwest

The **Pacific Northwest** regional profile is added in Beta 6.

The profile uses a conifer-oriented seven-asset pool with Alaska cedar, generic conifer, and Scots pine assets as visual analogs rather than literal botanical claims.

The profile also includes coordinated Designer theme and bunker/turf/terrain material settings.
