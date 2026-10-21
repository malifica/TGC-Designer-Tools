# Beta 6 - Multipolygon Preview and Mulch Water

## Multipolygon preview and mandatory mulch-water hotfix - 2026-10-21

- Relation-owned golf and water multipolygons render in the selection preview and mask whether Auto Red Mask is ON or OFF.
- Complete relation tags, outer boundaries and inner islands are retained in the ordinary LiDAR/DEM overlay and aligned/custom-OSM mask paths.
- Imported 2K25 water polygons and streams use native mulch category 10. Mulch05 is explicitly retained at surfaces2[2] after regional-theme application and immediately before final archive encoding.
- Asphalt roads use native category 8; cart paths remain category 7. Water/stream geometry and width settings remain configurable, but a primary-surface override cannot change imported water away from mulch.
- Red-mask exclusion/buffering/cleanup, CFS placement, terrain reconstruction, LiDAR tree sizing and all regional profiles are unchanged.

Existing projects: use Rebuild Mask from Current OSM Alignment to regenerate mask.png from the saved heightmap and alignment. Refresh the selection preview separately when needed. Reimport the course features for the water correction; old exported files and PNGs are not rewritten automatically.

This release applies the supplied hotfix to current Beta 6, including a correction to its installer anchors so all six preview call-site edits are actually applied. The native-overpy test fixture is corrected without changing application behavior. The LiDAR tree-sizing hotfix and existing entry point are retained. Automated checks validate geometry and serialized material assignments; native Designer appearance still requires a visual check.

