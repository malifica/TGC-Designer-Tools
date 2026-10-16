# TGC Designer Tools 2K25 — Beta 6 Hotfix

This hotfix applies the verified **Spline Surface Fix V1** to the existing Beta 6 release.

## Fixed

- OSM water polygons now default to the mulch custom surface instead of the cart-path surface.
- OSM streams now default to mulch and have an independent `stream` section in `splines.json`.
- Automobile roads now default to the asphalt custom surface and remain independently configurable from golf cart paths.
- Golf cart paths retain the selected Designer theme's Cart Path material while honoring `cartpath.pathWidth` and valid `primarySurface` settings.
- `water` and `stream` now have independent `splines.json` sections; the legacy `placeholder` section remains a backward-compatible fallback for closed-water geometry.
- Invalid `splines.json` syntax now stops processing with the exact filename, line, and column instead of silently falling back to defaults.
- Misnamed files such as `splines(2).json` are reported when the required `splines.json` is missing.
- The processing log now reports the effective cart-path, road, water, and stream surfaces and widths.
- CFS/aligned-mask road-width tracking now uses the same validated spline configuration loader as final OSM import.

## Default behavior

- Cart path: selected theme's Cart Path material; 2.0 m unless overridden.
- Automobile road: asphalt; 6.0 m unless overridden.
- Closed water polygon: mulch; 0.01 m boundary width unless overridden.
- Stream: mulch; 2.0 m unless overridden.

The release remains `v0.5.0-2k25-beta6`; the EXE and Windows ZIP retain their established Beta 6 filenames.
