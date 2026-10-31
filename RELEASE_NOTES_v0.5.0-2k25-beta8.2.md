# TGC Designer Tools 2K25 - Beta 8.2

**Version:** `v0.5.0-2k25-beta8.2`

**Windows executable:** `tgc_gui_2k25_beta8_2.exe`

## Surface parking lots

**Import Surface Parking Lots (Road Surface)** is a separate, default-off OSM import option. It creates filled parking areas using the same primary surface as traffic roads. Enable the parking option for lots and **Import Automobile Roads** separately if you also want their mapped vehicle lanes.

A valid closed `amenity=parking` area with `parking=surface`, or without a parking subtype, is eligible. Underground parking, garages, rooftop parking, mapped points and open boundaries do not turn into filled lots. Complete multipolygon lots retain their inner cutouts. Parking areas do not affect Auto Red Mask.

## Natural wood and terrain masks

**Import Natural Wood as Mulch (natural=wood)** is off by default. Only valid areas explicitly tagged `natural=wood` qualify. Meadow, forest-only and woodchip-only areas do not generate woodland mulch. A separately mapped wood island inside a meadow can qualify on its own. Individual OSM tree points remain independently selectable.

Woodland does not paint `mask.png` or contribute an Auto Red Mask keep area or buffer, during initial processing or an aligned CFS mask rebuild. To refresh an older affected project, back up your hand-painted mask, use **Apply + Rebuild Mask**, reapply wanted manual edits, then regenerate from your pre-import course. Earlier exports are not edited in place.
