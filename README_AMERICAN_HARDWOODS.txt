TGC Designer Tools 2K25 - Beta 8.5
American Hardwoods - Summer update

NEW THEME
Select "American Hardwoods - Summer" in the Regional Theme dropdown.
This build includes 26 factory themes, including this new theme.

The new automatic planting palette contains 31 native tree variants:
American elm, white oak, southern live oak, silver maple, green ash,
American beech, and willow oak. Pine, fir, spruce, other conifers, named
fall/autumn variants, and red-maple models with uncertain foliage color
are excluded. The existing Hudson Valley playing-surface and terrain
material preset is retained.

FILTER READY
Enable "Filter Ready" beside the theme selection when exporting a course.
Its matching catalog contains 40 unique nature objects: 31 trees, 5 grass
samples, and 4 plants. The trees match the planting palette exactly.
One sample of each missing asset is placed in an unused plot corner.
This works even when no LiDAR trees are present. Repeated exports do not
add duplicate samples for asset types already planted.

RUN THE NEW EXE
Extract TGC_Beta8_5_American_Hardwoods_Summer_Windows_x64.zip into a folder
and run tgc_gui_2k25_beta8_5.exe. The application title remains Beta 8.5.
The 26 themes and their Filter Ready catalogs are embedded in the EXE;
they remain available when the EXE is moved into another folder.
An external tree_profiles folder is not required for the built-in themes.

USE JUST THE NEW THEME JSON FILES
Extract American_Hardwoods_Summer_Theme.zip beside an existing compatible
Beta 8.5 EXE, retaining the folder structure:

tree_profiles/american_hardwoods_summer.json
tree_profiles/filter_ready/american_hardwoods_summer.json

Restart the application after adding or editing the files. An external
profile with the same display_name overrides the built-in copy.

VALIDATION
The build runs the existing Beta 8.5 source and frozen-EXE checks, plus
the new hardwood palette, nature-only catalog, no-LiDAR export, and
repeat-export checks. The EXE is also tested in an otherwise empty
directory to verify all 26 embedded themes and catalogs.
Native foliage identities were audited; this update was not visually
rendered inside PGA TOUR 2K25 during the build.

Existing manually planted objects in an imported course remain intact.
