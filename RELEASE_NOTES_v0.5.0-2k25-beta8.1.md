# TGC Designer Tools 2K25 - Beta 8.1

**Release ID:** `v0.5.0-2k25-beta8.1`  
**Windows executable:** `tgc_gui_2k25_beta8_1.exe`

## Highlights

- Separate **Import Woods / Woodchip Areas (Mulch)** and **Import Individual OSM Tree Points** controls. Both default OFF; woodland surfaces no longer enable tree-point planting.
- Standard `natural=wood`, `landuse=forest`, and closed `surface=woodchips` areas generate dry native mulch, separate from water.
- Complete woodland multipolygons preserve inner cutouts; incomplete or invalid geometry is reported rather than filled across missing members.
- Unity/SVG export writes standard woodland or woodchip classifications and omits private `tgc:*` feature annotations.
- Obsolete `golf=mulch` areas warn and are skipped instead of being silently reclassified.
- Existing LiDAR-tree detection, weighted planting, regional themes, terrain, background registration, and local feature editing are retained.

## Using the two controls

For woodland groundcover without individual OSM trees, enable **Import Woods / Woodchip Areas (Mulch)** and leave **Import Individual OSM Tree Points** OFF. LiDAR-tree controls remain independent. Existing duplicate suppression still avoids adding OSM points when LiDAR trees are requested.

Keep `natural=wood` for tree-covered land, or `landuse=forest` where appropriate. Use `surface=woodchips` for genuine wood/bark-chip ground. These describe the real feature; the game's mulch surface is an importer choice. Do not retag a bare bed as woodland merely for a game material.

The earlier private `golf=mulch` workflow is retired. Review old private-tagged local polygons and assign their actual standard classification. They are not automatically guessed. Unity woodland mapping exports `natural=wood`; its mulch mapping exports `surface=woodchips` and `area=yes`.

Woodland areas remain dry: no water registration, blue-water mask, water elevation or carving operation is introduced. Preview, aligned-mask and native import handling use the same supported area classifications.

## Existing projects

Keep a backup of any hand-edited mask. After changing OSM tags or files, finalize CFS alignment, rebuild the aligned mask, then redo any intended manual mask edits and regenerate the course. Existing course exports do not change automatically. The processed heightmap can be reused when its terrain, map scale and coordinate frame are unchanged.

Standard tags do not make synthetic Unity/SVG coordinates suitable for the public OSM database. Synthetic exports retain `upload="never"`; their geography must not be uploaded.

## Scope and validation

This is the main TGC Designer Tools application. No separate utility release is included. This source preparation does not build or publish a Windows EXE, create a release tag, or change the published Beta 8 assets. Windows/in-game testing is not claimed here. The publication handoff must verify the supplied Beta 8.1 binary and matching source before publishing it unchanged.
