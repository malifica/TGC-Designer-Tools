import math
import os
import tkinter as tk
from functools import partial
from tkinter import ttk

import cv2
import numpy as np
import overpy
import pyproj
import rasterio
from PIL import Image, ImageTk
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling

import OSMTGC
from GeoPointCloud import GeoPointCloud
import tgc_tools


# Deterministic DEM terrain reducer.
# This follows the intent of the existing LiDAR reducer by biasing slightly
# toward the lower ground envelope, without inheriting LiDAR's order dependence.
DEM_LOWER_GROUND_PERCENTILE = 40.0


def _reduce_dem_lidar_style(dem, native_scale, target_scale, printf=print):
    # Reduce a dense square-pixel DEM to the requested terrain sample spacing.
    # Each output cell is treated as a terrain bin, analogous to multiple
    # LiDAR points falling inside one Map Scale cell.
    native_scale = float(native_scale)
    target_scale = float(target_scale)

    if target_scale <= native_scale + 1e-9:
        return np.array(dem, dtype=np.float32, copy=True)

    ratio = target_scale / native_scale
    src_h, src_w = dem.shape

    printf(
        "LiDAR-style DEM reduction: native " + str(native_scale) +
        " m -> target " + str(target_scale) +
        " m; lower-ground percentile=" +
        str(DEM_LOWER_GROUND_PERCENTILE)
    )

    # Fast exact-block path when target spacing is an integer multiple
    # of native DEM spacing.
    rounded_ratio = int(round(ratio))
    if rounded_ratio >= 1 and abs(ratio - rounded_ratio) <= 1e-6:
        block = rounded_ratio

        out_h = int(math.ceil(src_h / float(block)))
        out_w = int(math.ceil(src_w / float(block)))

        pad_h = out_h * block - src_h
        pad_w = out_w * block - src_w

        padded = np.pad(
            dem,
            ((0, pad_h), (0, pad_w)),
            mode="constant",
            constant_values=np.nan,
        )

        blocked = padded.reshape(out_h, block, out_w, block)

        with np.errstate(all="ignore"):
            reduced = np.nanpercentile(
                blocked,
                DEM_LOWER_GROUND_PERCENTILE,
                axis=(1, 3),
            )

        reduced = reduced.astype(np.float32)

        printf(
            "DEM reducer used exact " + str(block) + "x" + str(block) +
            " source-cell blocks; output " +
            str(out_w) + " x " + str(out_h)
        )
        return reduced

    # General fallback for arbitrary non-integer scale ratios.
    out_w = int(math.ceil((src_w * native_scale) / target_scale))
    out_h = int(math.ceil((src_h * native_scale) / target_scale))
    reduced = np.full((out_h, out_w), np.nan, dtype=np.float32)

    for out_row in range(out_h):
        src_r0 = int(math.floor((out_row * target_scale) / native_scale))
        src_r1 = int(math.ceil(((out_row + 1) * target_scale) / native_scale))
        src_r0 = max(0, min(src_h, src_r0))
        src_r1 = max(src_r0 + 1, min(src_h, src_r1))

        for out_col in range(out_w):
            src_c0 = int(math.floor((out_col * target_scale) / native_scale))
            src_c1 = int(math.ceil(((out_col + 1) * target_scale) / native_scale))
            src_c0 = max(0, min(src_w, src_c0))
            src_c1 = max(src_c0 + 1, min(src_w, src_c1))

            window = dem[src_r0:src_r1, src_c0:src_c1]
            valid = window[np.isfinite(window)]
            if valid.size:
                reduced[out_row, out_col] = np.percentile(
                    valid,
                    DEM_LOWER_GROUND_PERCENTILE,
                )

    printf(
        "DEM reducer used geometric bins for non-integer scale ratio; output " +
        str(out_w) + " x " + str(out_h)
    )
    return reduced



# DEM / GeoTIFF support for TGC Designer Tools.
# Output deliberately matches lidar_map_api.py:
#   heightmap.npy + mask.png -> existing tgc_image_terrain.generate_course()

rect = None
rectid = None
rectx0 = 0
recty0 = 0
rectx1 = 10
recty1 = 10
move = False
canvas = None


def _normalize_image(im):
    out = np.array(im, dtype=np.float32, copy=True)
    finite = out[np.isfinite(out)]
    if finite.size == 0:
        return np.zeros(out.shape, dtype=np.float32)

    lo = float(np.percentile(finite, 2.0))
    hi = float(np.percentile(finite, 98.0))
    if not math.isfinite(lo):
        lo = float(np.min(finite))
    if not math.isfinite(hi):
        hi = float(np.max(finite))
    if hi <= lo:
        hi = lo + 1.0

    out[~np.isfinite(out)] = lo
    out = np.clip(out, lo, hi)
    return (out - lo) / (hi - lo)


def _parse_local_osm(local_osm_file, printf=print):
    if not local_osm_file:
        return None

    printf("Loading LOCAL OpenStreetMap data for DEM preview/mask: " + str(local_osm_file))
    with open(local_osm_file, "r", encoding="utf-8") as f:
        xml_data = f.read()

    op = overpy.Overpass()
    result = op.parse_xml(xml_data)

    incomplete = []
    for way in result.ways:
        try:
            way.get_nodes(resolve_missing=False)
        except overpy.exception.DataIncomplete:
            incomplete.append(way.id)

    if incomplete:
        preview = ", ".join(str(x) for x in incomplete[:10])
        if len(incomplete) > 10:
            preview += ", ..."
        raise RuntimeError(
            "Local OSM contains " + str(len(incomplete)) +
            " incomplete ways with missing node references: " + preview
        )

    printf("Local OSM parsed for DEM mask: " + str(len(result.ways)) + " ways")
    return result


def _get_osm_for_grid(pc, local_osm_file=None, printf=print):
    if local_osm_file:
        try:
            result = _parse_local_osm(local_osm_file, printf=printf)
            printf("DEM local-OSM mode: online Overpass disabled.")
            return result
        except Exception as exc:
            printf("ERROR loading local OSM for DEM preview/mask: " + str(exc))
            printf("Local OSM mode will NOT fall back to online Overpass.")
            return None

    ul = pc.ulENU()
    lr = pc.lrENU()
    ul_ll = pc.enuToLatLon(*ul)
    lr_ll = pc.enuToLatLon(*lr)
    return OSMTGC.getOSMData(
        lr_ll[0], ul_ll[1], ul_ll[0], lr_ll[1], printf=printf
    )


def _is_metric_projected(crs):
    if crs is None or not crs.is_projected:
        return False
    try:
        unit = (crs.linear_units or "").lower()
    except Exception:
        unit = ""
    return unit in ("metre", "meter", "metres", "meters", "m")


def _bounds(transform, width, height):
    left = transform.c
    top = transform.f
    right = left + transform.a * width
    bottom = top + transform.e * height
    return (
        min(left, right),
        min(bottom, top),
        max(left, right),
        max(bottom, top),
    )


def _utm_for_bounds(src_crs, bounds):
    left, bottom, right, top = bounds
    transformer = pyproj.Transformer.from_crs(
        pyproj.CRS.from_user_input(src_crs),
        pyproj.CRS.from_epsg(4326),
        always_xy=True,
    )
    lon, lat = transformer.transform((left + right) / 2.0, (bottom + top) / 2.0)
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    zone = max(1, min(60, zone))
    epsg = 32600 + zone if lat >= 0.0 else 32700 + zone
    return rasterio.crs.CRS.from_epsg(epsg)


def _dem_vertical_unit_to_meters(dataset):
    # Return (unit_name, meters_per_vertical_unit, source).
    #
    # Prefer the raster band's declared unit. USGS/NOAA GeoTIFF DEMs often
    # store horizontal and vertical values in US survey feet, and Rasterio
    # exposes the elevation unit through dataset.units.
    unit_name = None
    try:
        if dataset.units and len(dataset.units) >= 1:
            unit_name = dataset.units[0]
    except Exception:
        unit_name = None

    source = "raster band unit"

    # Fallback for compound CRS files that explicitly include a vertical CRS.
    if not unit_name:
        try:
            crs = pyproj.CRS.from_user_input(dataset.crs)
            vertical_candidates = []
            if crs.is_vertical:
                vertical_candidates.append(crs)
            try:
                vertical_candidates.extend(
                    sub for sub in crs.sub_crs_list
                    if getattr(sub, "is_vertical", False)
                )
            except Exception:
                pass

            for vcrs in vertical_candidates:
                axes = list(vcrs.axis_info)
                if axes:
                    unit_name = axes[0].unit_name
                    source = "vertical CRS axis"
                    break
        except Exception:
            pass

    if not unit_name:
        return "unknown", 1.0, "none"

    normalized = str(unit_name).strip().lower()
    compact = (
        normalized
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )

    # Meter spellings.
    if compact in ("m", "meter", "meters", "metre", "metres"):
        return str(unit_name), 1.0, source

    # US survey foot: exactly 1200 / 3937 metres.
    if compact in (
        "ussurveyfoot",
        "ussurveyfeet",
        "surveyfoot",
        "surveyfeet",
        "ftus",
        "usft",
    ):
        return str(unit_name), 1200.0 / 3937.0, source

    # International foot.
    if compact in ("foot", "feet", "ft", "internationalfoot"):
        return str(unit_name), 0.3048, source

    return str(unit_name), None, source


def _get_dem_epsg_info(crs):
    # Return (source_epsg, horizontal_epsg).
    # For ordinary projected CRS these are usually the same.
    # For compound CRS, horizontal_epsg is taken from the projected/geographic
    # horizontal component when available.
    if crs is None:
        return None, None

    source_epsg = None
    horizontal_epsg = None

    try:
        source_epsg = crs.to_epsg()
    except Exception:
        pass

    try:
        parsed = pyproj.CRS.from_user_input(crs)

        if source_epsg is None:
            try:
                source_epsg = parsed.to_epsg()
            except Exception:
                pass

        # Ordinary projected/geographic CRS.
        if parsed.is_projected or parsed.is_geographic:
            try:
                horizontal_epsg = parsed.to_epsg()
            except Exception:
                pass

        # Compound CRS: find the horizontal projected/geographic component.
        if horizontal_epsg is None:
            try:
                for sub in parsed.sub_crs_list:
                    if sub.is_projected or sub.is_geographic:
                        try:
                            horizontal_epsg = sub.to_epsg()
                        except Exception:
                            horizontal_epsg = None
                        if horizontal_epsg is not None:
                            break
            except Exception:
                pass

    except Exception:
        pass

    return source_epsg, horizontal_epsg


def _load_dem(dem_files, target_sample_scale=None, printf=print):
    if not dem_files:
        raise RuntimeError("No DEM files selected.")

    datasets = []
    try:
        for path in dem_files:
            printf("Opening DEM: " + str(path))
            ds = rasterio.open(path)
            if ds.crs is None:
                ds.close()
                raise RuntimeError("DEM has no CRS/georeferencing: " + str(path))
            if ds.count < 1:
                ds.close()
                raise RuntimeError("DEM has no raster bands: " + str(path))
            datasets.append(ds)

        src_crs = datasets[0].crs

        source_epsg, horizontal_epsg = _get_dem_epsg_info(src_crs)
        if source_epsg is not None:
            printf("DEM source EPSG automatically detected: " + str(source_epsg))
        else:
            printf("DEM source EPSG code is not explicitly available; using embedded CRS definition.")

        if horizontal_epsg is not None and horizontal_epsg != source_epsg:
            printf("DEM horizontal EPSG automatically detected: " + str(horizontal_epsg))
        for ds in datasets[1:]:
            if ds.crs != src_crs:
                raise RuntimeError(
                    "DEM V1 requires selected tiles to use the same CRS. "
                    "Mismatched tile: " + str(ds.name)
                )

        # Determine vertical elevation units independently from horizontal CRS.
        # Horizontal reprojection changes X/Y units only; it does NOT scale
        # raster elevation values.
        vertical_units = []
        for ds in datasets:
            unit_name, unit_to_m, unit_source = _dem_vertical_unit_to_meters(ds)
            vertical_units.append((unit_name, unit_to_m, unit_source))

        first_unit_name, vertical_to_meters, first_unit_source = vertical_units[0]

        if vertical_to_meters is None:
            raise RuntimeError(
                "Unsupported DEM vertical elevation unit: " +
                str(first_unit_name) +
                ". Supported units are meters, US survey feet, and feet."
            )

        for unit_name, unit_to_m, unit_source in vertical_units[1:]:
            if unit_to_m is None or abs(unit_to_m - vertical_to_meters) > 1e-12:
                raise RuntimeError(
                    "Selected DEM tiles do not use matching vertical units: " +
                    str(first_unit_name) + " versus " + str(unit_name)
                )

        if first_unit_name == "unknown":
            printf(
                "WARNING: DEM vertical unit is not declared. "
                "Assuming elevation values are already meters."
            )
        else:
            printf(
                "DEM vertical units: " + str(first_unit_name) +
                " (" + str(first_unit_source) + ")"
            )

        printf(
            "DEM vertical conversion factor to meters: " +
            str(vertical_to_meters)
        )

        printf("Mosaicing " + str(len(datasets)) + " DEM tile(s)")
        mosaic, src_transform = merge(datasets, indexes=1, masked=True)

        if mosaic.ndim == 3:
            source_ma = np.ma.asarray(mosaic[0], dtype=np.float32)
        else:
            source_ma = np.ma.asarray(mosaic, dtype=np.float32)

        source = source_ma.filled(np.nan).astype(np.float32)

        # Convert Z/elevation values to meters BEFORE reprojection/downsampling.
        # Rasterio reprojection changes horizontal coordinates only and leaves
        # the raster sample values numerically unchanged.
        if abs(vertical_to_meters - 1.0) > 1e-12:
            finite_mask = np.isfinite(source)
            source[finite_mask] = (
                source[finite_mask] * vertical_to_meters
            ).astype(np.float32)
            printf(
                "Converted DEM elevations from " + str(first_unit_name) +
                " to meters."
            )
        else:
            printf("DEM elevations already in meters; no Z scaling needed.")

        finite_values = source[np.isfinite(source)]
        if finite_values.size:
            printf(
                "DEM elevation range after vertical conversion: " +
                str(round(float(np.min(finite_values)), 4)) + " to " +
                str(round(float(np.max(finite_values)), 4)) + " meters"
            )

        src_h, src_w = source.shape
        src_bounds = _bounds(src_transform, src_w, src_h)

        target_crs = src_crs
        reproject_needed = not _is_metric_projected(src_crs)

        if reproject_needed:
            target_crs = _utm_for_bounds(src_crs, src_bounds)
            printf("DEM CRS is not metric projected; reprojecting to " + str(target_crs))
            dst_transform, dst_w, dst_h = calculate_default_transform(
                src_crs, target_crs, src_w, src_h, *src_bounds
            )

            nodata = -999999.0  # Safe float32 nodata sentinel for terrestrial DEM elevations
            src_work = np.where(np.isfinite(source), source, nodata).astype(np.float32)
            dest = np.full((dst_h, dst_w), nodata, dtype=np.float32)

            reproject(
                source=src_work,
                destination=dest,
                src_transform=src_transform,
                src_crs=src_crs,
                src_nodata=nodata,
                dst_transform=dst_transform,
                dst_crs=target_crs,
                dst_nodata=nodata,
                resampling=Resampling.bilinear,
            )
            dem = dest
            dem[dem == nodata] = np.nan
            transform = dst_transform
        else:
            printf("DEM projected CRS: " + str(src_crs))
            dem = source
            transform = src_transform

        sx = abs(float(transform.a))
        sy = abs(float(transform.e))

        # Existing TGC path stores one image_scale, so force square pixels.
        if abs(sx - sy) > max(1e-6, 0.001 * max(sx, sy)):
            target_res = min(sx, sy)
            left, bottom, right, top = _bounds(
                transform, dem.shape[1], dem.shape[0]
            )
            new_w = int(math.ceil((right - left) / target_res))
            new_h = int(math.ceil((top - bottom) / target_res))
            new_transform = rasterio.transform.from_origin(
                left, top, target_res, target_res
            )

            nodata = -999999.0  # Safe float32 nodata sentinel for terrestrial DEM elevations
            src_work = np.where(np.isfinite(dem), dem, nodata).astype(np.float32)
            dest = np.full((new_h, new_w), nodata, dtype=np.float32)

            reproject(
                source=src_work,
                destination=dest,
                src_transform=transform,
                src_crs=target_crs,
                src_nodata=nodata,
                dst_transform=new_transform,
                dst_crs=target_crs,
                dst_nodata=nodata,
                resampling=Resampling.bilinear,
            )
            dem = dest
            dem[dem == nodata] = np.nan
            transform = new_transform
            sx = sy = target_res

        if not np.isfinite(dem).any():
            raise RuntimeError("DEM contains no finite elevation pixels.")

        native_scale = (sx + sy) / 2.0
        image_scale = native_scale

        # DEM rasters can be much denser than useful TGC terrain sampling.
        # Use the GUI Map Scale as the terrain sample-center spacing, matching
        # the existing LiDAR workflow. Never upsample finer than the DEM source.
        requested_scale = None
        if target_sample_scale is not None:
            try:
                requested_scale = float(target_sample_scale)
            except Exception:
                requested_scale = None

        if requested_scale is not None and requested_scale > 0.0:
            if requested_scale + 1e-6 < native_scale:
                printf(
                    "Requested DEM Map Scale " + str(requested_scale) +
                    " m is finer than native DEM spacing " + str(native_scale) +
                    " m; using native spacing instead."
                )
                requested_scale = native_scale

            if requested_scale > native_scale + 1e-6:
                left, bottom, right, top = _bounds(
                    transform, dem.shape[1], dem.shape[0]
                )

                dem = _reduce_dem_lidar_style(
                    dem,
                    native_scale=native_scale,
                    target_scale=requested_scale,
                    printf=printf,
                )

                transform = rasterio.transform.from_origin(
                    left,
                    top,
                    requested_scale,
                    requested_scale,
                )

                sx = requested_scale
                sy = requested_scale
                image_scale = requested_scale

                printf(
                    "DEM terrain grid after LiDAR-style reduction: " +
                    str(dem.shape[1]) + " x " + str(dem.shape[0]) +
                    " at " + str(requested_scale) + " m"
                )
            else:
                image_scale = native_scale
                printf(
                    "DEM Map Scale matches native spacing closely; no "
                    "additional resampling required."
                )
        else:
            printf(
                "No valid DEM target Map Scale supplied; using native DEM "
                "spacing " + str(native_scale) + " m."
            )

        # Rasterio row 0 is north/top. TGC tool internal image row 0 is south.
        dem_south_up = np.flipud(dem).astype(np.float32)

        left, bottom, right, top = _bounds(
            transform, dem.shape[1], dem.shape[0]
        )

        pc = GeoPointCloud()
        pc.proj = pyproj.Proj(target_crs.to_wkt())
        pc.origin = (left, bottom)
        pc.xmin = 0.0
        pc.ymin = 0.0
        pc.xmax = right - left
        pc.ymax = top - bottom
        pc.width = right - left
        pc.height = top - bottom

        printf(
            "DEM raster: " + str(dem_south_up.shape[1]) + " x " +
            str(dem_south_up.shape[0]) + " pixels"
        )
        printf("DEM pixel spacing: " + str(image_scale) + " meters")
        printf(
            "DEM coverage: " + str(round(pc.width, 2)) + " m x " +
            str(round(pc.height, 2)) + " m"
        )
        printf("DEM elevation values are normalized to meters before terrain generation.")

        return dem_south_up, float(image_scale), pc

    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass


def _start_rect(event):
    global move, rect, rectid, rectx0, recty0
    move = True
    rectx0 = canvas.canvasx(event.x)
    recty0 = canvas.canvasy(event.y)
    if rect is not None:
        canvas.delete(rect)
    rect = canvas.create_rectangle(
        rectx0, recty0, rectx0, recty0, outline="#ff0000", width=2
    )
    rectid = rect


def _move_rect(event):
    global rectx1, recty1
    if move:
        rectx1 = canvas.canvasx(event.x)
        recty1 = canvas.canvasy(event.y)
        canvas.coords(rectid, rectx0, recty0, rectx1, recty1)


def _stop_rect(event):
    global move, rectx1, recty1
    move = False
    rectx1 = canvas.canvasx(event.x)
    recty1 = canvas.canvasy(event.y)
    canvas.coords(rectid, rectx0, recty0, rectx1, recty1)


def _write_output(
    popup,
    dem,
    preview_rgb,
    pc,
    image_scale,
    output_dir,
    display_w,
    display_h,
    printf,
):
    popup.destroy()

    h, w = dem.shape
    x0, x1 = sorted((rectx0, rectx1))
    y0, y1 = sorted((recty0, recty1))

    if abs(x1 - x0) < 5 or abs(y1 - y0) < 5:
        printf("No DEM crop rectangle selected; using full DEM.")
        lower_x, upper_x = 0, w
        lower_y, upper_y = 0, h
    else:
        sx = float(w) / float(display_w)
        sy = float(h) / float(display_h)

        lower_x = max(0, min(w, int(math.floor(x0 * sx))))
        upper_x = max(0, min(w, int(math.ceil(x1 * sx))))

        top_display = max(0, min(h, int(math.floor(y0 * sy))))
        bottom_display = max(0, min(h, int(math.ceil(y1 * sy))))
        lower_y = h - bottom_display
        upper_y = h - top_display

    if upper_x <= lower_x or upper_y <= lower_y:
        printf("Invalid DEM crop; no files written.")
        return

    crop_w_m = (upper_x - lower_x) * image_scale
    crop_h_m = (upper_y - lower_y) * image_scale
    printf(
        "DEM crop: " + str(round(crop_w_m, 2)) + " m x " +
        str(round(crop_h_m, 2)) + " m"
    )
    if crop_w_m > 2200.0 or crop_h_m > 2200.0:
        printf("WARNING: DEM crop is larger than about 2.2 km in one dimension.")

    dem_crop = dem[lower_y:upper_y, lower_x:upper_x]
    heightmap = np.expand_dims(dem_crop.astype(np.float32), axis=2)

    visual_gray = _normalize_image(dem_crop)
    visual = cv2.cvtColor(visual_gray, cv2.COLOR_GRAY2RGB)

    mask_crop = preview_rgb[lower_y:upper_y, lower_x:upper_x]
    mask_disk = np.flip(mask_crop, 0)

    tgc_tools.create_directory(output_dir)

    mask_path = os.path.join(output_dir, "mask.png")
    printf("Saving DEM mask as: " + mask_path)
    cv2.imwrite(
        mask_path,
        cv2.cvtColor(
            np.clip(mask_disk * 255.0, 0, 255).astype(np.uint8),
            cv2.COLOR_RGB2BGR,
        ),
    )

    output_data = {
        "heightmap": heightmap,
        "visual": visual,
        "pointcloud": [],
        "image_scale": float(image_scale),
        "origin": pc.cv2ToLatLon(lower_y, lower_x, image_scale),
        "projection": pc.proj,
        "trees": [],
        "source": "DEM",
    }

    out_base = os.path.join(output_dir, "heightmap")
    printf("Saving DEM data as: " + out_base + ".npy")
    np.save(out_base, output_data)

    printf("DEM heightmap generation complete.")
    printf("DEM tree list is empty; OSM woods/trees remain available later.")
    printf("Use Import Terrain and Features exactly as with a LiDAR heightmap.")


def _request_crop(dem, pc, image_scale, output_dir, osm_result, printf=print):
    global canvas, rect, rectx0, recty0, rectx1, recty1

    preview_gray = _normalize_image(dem)
    preview_rgb = cv2.cvtColor(preview_gray, cv2.COLOR_GRAY2RGB)

    if osm_result:
        preview_rgb = OSMTGC.addOSMToImage(
            osm_result.ways,
            preview_rgb,
            pc,
            image_scale,
            printf=printf,
        )
        printf("OSM features rendered into DEM preview/mask.")

    display_rgb = np.flip(preview_rgb, 0)
    pil = Image.fromarray(
        np.clip(display_rgb * 255.0, 0, 255).astype(np.uint8),
        "RGB",
    )
    pil.thumbnail((700, 700), Image.LANCZOS)
    display_w, display_h = pil.size

    popup = tk.Toplevel()
    popup.wm_title("Select DEM Course Boundaries")
    popup.geometry(
        str(max(display_w + 40, 720)) + "x" + str(display_h + 120)
    )

    ttk.Label(
        popup,
        text=(
            "Draw a rectangle around the course, then click Accept.\n"
            "If no rectangle is drawn, the full DEM extent is used."
        ),
        justify=tk.CENTER,
    ).pack(pady=8)

    cim = ImageTk.PhotoImage(image=pil)
    canvas = tk.Canvas(popup, width=display_w, height=display_h)
    canvas.create_image(0, 0, image=cim, anchor=tk.NW)
    canvas.image = cim
    canvas.pack()

    rect = None
    rectx0 = 0
    recty0 = 0
    rectx1 = display_w
    recty1 = display_h

    canvas.bind("<Button-1>", _start_rect)
    canvas.bind("<ButtonRelease-1>", _stop_rect)
    canvas.bind("<Motion>", _move_rect)

    ttk.Button(
        popup,
        text="Accept",
        command=partial(
            _write_output,
            popup,
            dem,
            preview_rgb,
            pc,
            image_scale,
            output_dir,
            display_w,
            display_h,
            printf,
        ),
    ).pack(pady=8)

    popup.transient()
    popup.grab_set()
    popup.wait_window()


def generate_dem_previews(
    dem_files,
    output_dir_path,
    local_osm_file=None,
    sample_scale=None,
    printf=print,
):
    printf("Starting DEM / GeoTIFF processing.")
    printf("Rasterio version: " + str(rasterio.__version__))

    dem, image_scale, pc = _load_dem(
        dem_files,
        target_sample_scale=sample_scale,
        printf=printf
    )
    osm_result = _get_osm_for_grid(
        pc, local_osm_file=local_osm_file, printf=printf
    )

    if local_osm_file and osm_result is None:
        printf("Continuing DEM preview without OSM; no online fallback was used.")

    _request_crop(
        dem,
        pc,
        image_scale,
        output_dir_path,
        osm_result,
        printf=printf,
    )
