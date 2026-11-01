# TGC Designer Tools 2K25 - Beta 8.3

**Version:** `v0.5.0-2k25-beta8.3`

**Windows executable:** `tgc_gui_2k25_beta8_3.exe`

## Open islands in OSM rough and water hazards

A rough boundary explicitly used as an inner ring of an outer rough multipolygon now cuts an opening in the outer course spline. This includes a boundary that carries `golf=rough` itself and one whose rough classification comes from its own multipolygon. The importer joins the inner ring to the outer ring with a narrow lollipop slit and does not lay a second rough surface over the opening.

The same rule applies to water inside water. A water-hazard inner ring is a dry cutout, not a second water fill. The surrounding hazard retains its water material. Preview and generated masks respect the owned hole rather than painting it back in.

A separately mapped bunker or other feature inside a cutout keeps its own import settings. Where no other surface covers the opening, the underlying course surface shows through. Mere proximity does not establish an island: the boundaries must be related in the OSM data.

These changes apply when importing or regenerating a course. They do not remove previously generated splines from an existing export. Start from a pre-import course copy when retesting. Surface parking lots and the Natural Wood-only import remain available with their Beta 8.2 behavior.
