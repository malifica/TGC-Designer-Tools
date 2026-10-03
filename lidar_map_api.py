import tkinter as tk
from tkinter import filedialog
from tkinter import *
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText
import PIL
from PIL import Image, ImageTk

import cv2
from functools import partial
import json
import math
import numpy as np
import os
from pathlib import Path
import shutil
import overpy
import scipy
import pyproj
import sys
import time
import urllib

import OSMTGC
import auto_red_mask
import cfs_georef
import tgc_tools
import tree_mapper
import lidar_feature_filter
import lidar_fast_native
from usgs_lidar_parser import *

# Parameters
desired_visible_points_per_pixel = 1.0
lidar_sample = 1 # Use every Nths lidar point.  1 is use all, 10 is use one of out 10
lidar_to_disk = False
status_print_duration = 1.0 # Print progress every n seconds

# 1 Unassigned
# 2 Ground
# 3 Low Vegetation
# 4 Medium Vegetation
# 5 High Vegetation
# 6 Building
# 7 Noise
# 8 Model Key Points
# 9 Water

wanted_classifications = [2, 8] # These are considered "bare earth"

# Global Variables for the UI
rect = None
rectid = None
rectx0 = 0
recty0 = 0
rectx1 = 10
recty1 = 10

lower_x = 0
lower_y = 0
upper_x = 10
upper_y = 10

running_as_main = False
canvas = None
im_img = None
sat_canvas = None
sat_img = None

move = False
selection_outline_color = "#ff0000"  # red normally; black over Auto Red Mask

def normalize_image(im):
    # Set Nans and Infs to minimum value
    finite_pixels = im[np.isfinite(im)]
    im[np.isnan(im)] = np.min(finite_pixels)
    # Limit outlier pixels
    # Use the median of valid pixels only to ensure that the contrast is good
    im = np.clip(im, 0.0, 3.5*np.median(finite_pixels))
    # Scale from 0.0 to 1.0
    min_value = np.min(im)
    max_value = np.max(im)
    return (im - min_value) / (max_value - min_value)

def createCanvasBinding():
    global canvas
    global move
    global rect
    global rectid
    global rectx0
    global rectx1
    global recty0
    global recty1
    canvas.bind( "<Button-1>", startRect )
    canvas.bind( "<ButtonRelease-1>", stopRect )
    canvas.bind( "<Motion>", movingRect )

def startRect(event):
    global selection_outline_color
    global canvas
    global move
    global rect
    global rectid
    global rectx0
    global rectx1
    global recty0
    global recty1
    move = True
    rectx0 = canvas.canvasx(event.x)
    recty0 = canvas.canvasy(event.y) 
    if rect is not None:
        canvas.delete(rect)
    rect = canvas.create_rectangle(
        rectx0, recty0, rectx0, recty0, outline=selection_outline_color, width=2)
    rectid = canvas.find_closest(rectx0, recty0, halo=2)

def movingRect(event):
    global canvas
    global move
    global rectid
    global rectx0
    global rectx1
    global recty0
    global recty1
    if move: 
        rectx1 = canvas.canvasx(event.x)
        recty1 = canvas.canvasy(event.y)
        canvas.coords(rectid, rectx0, recty0,
                      rectx1, recty1)

def stopRect(event):
    global canvas
    global move
    global rectid
    global rectx0
    global rectx1
    global recty0
    global recty1
    move = False
    rectx1 = canvas.canvasx(event.x)
    recty1 = canvas.canvasy(event.y) 
    canvas.coords(rectid, rectx0, recty0,
                  rectx1, recty1)


def _compute_crop_bounds(input_size, canvas_size):
    max_canvas_dimension = max([canvas_size[0], canvas_size[1]])
    width_over_height_ratio = float(input_size[0]) / float(input_size[1])
    canvas_width = max_canvas_dimension * width_over_height_ratio
    canvas_height = max_canvas_dimension
    if width_over_height_ratio > 1.0:
        canvas_width = max_canvas_dimension
        canvas_height = max_canvas_dimension / width_over_height_ratio

    width_ratio = float(input_size[0]) / float(canvas_width)
    height_ratio = float(input_size[1]) / float(canvas_height)

    lx = int(width_ratio * rectx0)
    ux = int(width_ratio * rectx1)
    if lx > ux:
        lx, ux = ux, lx

    ly = int(height_ratio * (canvas_size[1] - recty0))
    uy = int(height_ratio * (canvas_size[1] - recty1))
    if ly > uy:
        ly, uy = uy, ly

    return (lx, ly, ux, uy)


def closeWindow(main, bundle, input_size, canvas_size, printf):
    """Legacy synchronous path retained for CLI/backward compatibility."""
    crop_bounds = _compute_crop_bounds(input_size, canvas_size)
    main.destroy()
    generate_lidar_heightmap(*bundle, crop_bounds=crop_bounds, printf=printf)

def request_course_outline(course_image, sat_image=None, bundle=None, printf=print):
    global selection_outline_color
    # TGC_MASK_AWARE_SELECTION_RECT_V1
    # Auto Red Mask makes most of the preview red, so use black there.
    # Otherwise retain the legacy red crop rectangle.
    auto_mask_active = False
    try:
        auto_mask_active = bool(bundle is not None and len(bundle) >= 6 and bundle[5])
    except Exception:
        auto_mask_active = False
    selection_outline_color = "#000000" if auto_mask_active else "#ff0000"
    global running_as_main
    global canvas
    global im_img
    global sat_canvas
    global sat_img

    input_size = (course_image.shape[1], course_image.shape[0]) # width, height
    preview_size = (600, 600) # Size of image previews

    # Create new window since this tool could be used as main
    if running_as_main:
        popup = tk.Tk()
    else:
        popup = tk.Tk() if running_as_main else tk.Toplevel()
    popup.geometry("1250x700")
    popup.wm_title("Select Course Boundaries")

    # Convert and resize for display
    im = Image.fromarray((255.0*course_image).astype(np.uint8), 'RGB')
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    im.thumbnail(preview_size, PIL.Image.LANCZOS) # Thumbnail is just resize but preserves aspect ratio
    cim = ImageTk.PhotoImage(image=im)

    instruction_frame = tk.Frame(popup)
    B1 = ttk.Button(instruction_frame, text="Accept", command = partial(closeWindow, popup, bundle, input_size, im.size, printf))
    label = ttk.Label(instruction_frame, text="Draw the rectangle around the course on the left (black with Auto Red Mask; red otherwise)\n \
                                   Then close this window using the Accept Button.\n \
                                   IF YOU DON'T SEE YOUR COURSE IN BOTH BOXES YOU HAVE THE WRONG EPSG!", justify=CENTER)
    label.pack(fill="x", padx=10, pady=10)
    B1.pack()

    instruction_frame.pack()

    # Show both images
    image_frame = tk.Frame(popup)
    image_frame.pack()

    canvas = tk.Canvas(image_frame, width=preview_size[0], height=preview_size[1])
    im_img = canvas.create_image(0,0,image=cim,anchor=tk.NW)
    canvas.itemconfig(im_img, image=cim)
    canvas.image = im_img
    canvas.grid(row=0, column=0, sticky='w')

    if sat_image is not None:
        sim = Image.fromarray((sat_image).astype(np.uint8), 'RGB')
        sim.thumbnail(preview_size, PIL.Image.LANCZOS) # Thumbnail is just resize but preserves aspect ratio
        scim = ImageTk.PhotoImage(image=sim)
        sat_canvas = tk.Canvas(image_frame, width=preview_size[0], height=preview_size[1])
        sat_img = sat_canvas.create_image(0,0,image=scim,anchor=tk.NW)
        sat_canvas.itemconfig(sat_img, image=scim)
        sat_canvas.image = sat_img
        sat_canvas.grid(row=0, column=preview_size[0]+10, sticky='e')

    createCanvasBinding()

    popup.mainloop()


def _rasterize_preview_last_write(img_points, image_height, image_width, value_axis, sampling):
    out = np.full((image_height, image_width, 1), math.nan, np.float32)
    pts = np.asarray(img_points[0::sampling])
    if len(pts) == 0:
        return out

    rows = pts[:, 0].astype(np.int64, copy=False)
    cols = pts[:, 1].astype(np.int64, copy=False)
    valid = (
        (rows >= 0) & (rows < image_height) &
        (cols >= 0) & (cols < image_width)
    )
    rows = rows[valid]
    cols = cols[valid]
    vals = pts[valid, value_axis]
    if len(rows) == 0:
        return out

    flat = rows * int(image_width) + cols
    # Historical behavior overwrites the pixel for every point; retain the
    # final point in the original order for each pixel without a Python loop.
    _, reverse_first = np.unique(flat[::-1], return_index=True)
    last_pos = (len(flat) - 1) - reverse_first
    out_flat = out[:, :, 0].reshape(-1)
    out_flat[flat[last_pos]] = vals[last_pos].astype(np.float32, copy=False)
    return out


def prepare_lidar_previews(lidar_dir_path, sample_scale, output_dir_path, force_epsg=None, force_unit=None, printf=print, local_osm_file=None, auto_red_mask_enabled=False, auto_red_mask_buffer_m=5.0):
    """Heavy, Tk-free LiDAR preparation suitable for a worker thread."""
    tgc_tools.create_directory(output_dir_path)

    pc = load_usgs_directory(
        lidar_dir_path,
        force_epsg=force_epsg,
        force_unit=force_unit,
        printf=printf,
    )
    if pc is None:
        return None

    image_width = math.ceil(pc.width / sample_scale) + 1
    image_height = math.ceil(pc.height / sample_scale) + 1

    printf("Generating lidar intensity image (vectorized)")
    img_points = pc.pointsAsCV2(sample_scale)
    num_points = len(img_points)
    point_density = float(num_points) / (image_width * image_height)
    visible_sampling = math.floor(
        point_density / desired_visible_points_per_pixel
    )
    if visible_sampling < 1.0:
        visible_sampling = 1

    visualization_axis = 3
    if pc.imin == pc.imax:
        printf("No lidar intensity found, using elevation instead")
        visualization_axis = 2

    im = _rasterize_preview_last_write(
        img_points,
        image_height,
        image_width,
        visualization_axis,
        visible_sampling,
    )

    printf("Adding golf features to lidar data")
    im = normalize_image(im)
    im = cv2.cvtColor(im, cv2.COLOR_GRAY2RGB)

    upper_left_enu = pc.ulENU()
    lower_right_enu = pc.lrENU()
    upper_left_latlon = pc.enuToLatLon(*upper_left_enu)
    lower_right_latlon = pc.enuToLatLon(*lower_right_enu)

    if local_osm_file:
        result = None
        try:
            printf(
                "Loading LOCAL OpenStreetMap data for LiDAR preview/mask: "
                + str(local_osm_file)
            )
            with open(local_osm_file, "r", encoding="utf-8") as osm_file:
                local_osm_xml = osm_file.read()

            osm_parser = overpy.Overpass()
            result = osm_parser.parse_xml(local_osm_xml)

            incomplete_ways = []
            for way in result.ways:
                try:
                    way.get_nodes(resolve_missing=False)
                except overpy.exception.DataIncomplete:
                    incomplete_ways.append(way.id)

            if incomplete_ways:
                preview = ", ".join(str(x) for x in incomplete_ways[:10])
                if len(incomplete_ways) > 10:
                    preview += ", ..."
                raise RuntimeError(
                    "Local OSM contains " + str(len(incomplete_ways)) +
                    " incomplete ways with missing node references: " + preview
                )

            golf_water_count = 0
            other_water_count = 0
            for way in result.ways:
                golf_type = way.tags.get("golf", None)
                natural_type = way.tags.get("natural", None)
                waterway_type = way.tags.get("waterway", None)
                if golf_type in ("water_hazard", "lateral_water_hazard"):
                    golf_water_count += 1
                elif natural_type == "water" or waterway_type is not None:
                    other_water_count += 1

            printf(
                "Local OSM parsed for mask: " + str(len(result.ways)) +
                " ways; golf water polygons=" + str(golf_water_count) +
                "; other water-tagged ways=" + str(other_water_count)
            )
        except Exception as exc:
            printf("ERROR loading local OSM for LiDAR preview/mask: " + str(exc))
            printf("Local OSM mode will NOT fall back to online Overpass.")
            result = None
    else:
        result = OSMTGC.getOSMData(
            lower_right_latlon[0],
            upper_left_latlon[1],
            upper_left_latlon[0],
            lower_right_latlon[1],
            printf=printf,
        )

    if result:
        im = OSMTGC.addOSMToImage(
            result.ways,
            im,
            pc,
            sample_scale,
            printf=printf,
        )
        if local_osm_file:
            printf("Local OSM features rendered into LiDAR preview/mask source image")
    else:
        if local_osm_file:
            printf("No local OSM overlay was rendered into the preview/mask.")
        else:
            printf(
                "OpenStreetMap download failed. You won't see helpful OSM "
                "outlines or drawings on your preview or mask."
            )

    if auto_red_mask_enabled and result is not None:
        im = auto_red_mask.apply_auto_red_mask(
            result,
            im,
            pc,
            sample_scale,
            buffer_m=auto_red_mask_buffer_m,
            printf=printf,
        )

    origin_projected_coordinates = pc.origin
    gps_center = pc.projToLatLon(
        origin_projected_coordinates[0] + pc.width / 2.0,
        origin_projected_coordinates[1] + pc.height / 2.0,
    )

    sat_image = np.zeros((400, 400, 3), np.uint8)
    sat_image[:] = (255, 255, 255)
    font = cv2.FONT_HERSHEY_SIMPLEX
    fontScale = 0.5
    fontColor = (0, 0, 0)
    lineType = 2
    cv2.putText(sat_image, "Sat Images Disabled As of 2024", (10, 50), font, fontScale, fontColor, lineType)
    cv2.putText(sat_image, "Make sure a few OSM features show on the left", (10, 150), font, fontScale, fontColor, lineType)
    cv2.putText(sat_image, "GPS Center Coordinates: ", (10, 250), font, fontScale, fontColor, lineType)
    cv2.putText(sat_image, str(gps_center), (10, 350), font, fontScale, fontColor, lineType)

    return {
        "course_image": im,
        "sat_image": sat_image,
        "pc": pc,
        "img_points": img_points,
        "sample_scale": sample_scale,
        "output_dir_path": output_dir_path,
        "osm_result": result,
        "auto_red_mask_enabled": auto_red_mask_enabled,
        "auto_red_mask_buffer_m": auto_red_mask_buffer_m,
    }


def show_prepared_lidar_preview(prepared, printf=print):
    """Tk-only boundary selection. Returns source-image crop bounds."""
    global selection_outline_color
    global canvas, im_img, sat_canvas, sat_img
    global rectx0, rectx1, recty0, recty1, rect

    course_image = prepared["course_image"]
    sat_image = prepared.get("sat_image")
    selection_outline_color = (
        "#000000" if prepared.get("auto_red_mask_enabled", False)
        else "#ff0000"
    )

    input_size = (course_image.shape[1], course_image.shape[0])
    preview_size = (600, 600)

    popup = tk.Toplevel()
    popup.geometry("1250x700")
    popup.wm_title("Select Course Boundaries")

    im = Image.fromarray((255.0 * course_image).astype(np.uint8), 'RGB')
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    im.thumbnail(preview_size, PIL.Image.LANCZOS)
    cim = ImageTk.PhotoImage(image=im)

    result = {"accepted": False, "crop": None}

    def accept():
        result["crop"] = _compute_crop_bounds(input_size, im.size)
        result["accepted"] = True
        popup.destroy()

    def cancel():
        result["accepted"] = False
        popup.destroy()

    instruction_frame = tk.Frame(popup)
    ttk.Label(
        instruction_frame,
        text=(
            "Draw the rectangle around the course on the left "
            "(black with Auto Red Mask; red otherwise)\n"
            "Then close this window using the Accept Button.\n"
            "IF YOU DON'T SEE YOUR COURSE IN BOTH BOXES YOU HAVE THE WRONG EPSG!"
        ),
        justify=CENTER,
    ).pack(fill="x", padx=10, pady=10)
    ttk.Button(instruction_frame, text="Accept", command=accept).pack()
    instruction_frame.pack()

    image_frame = tk.Frame(popup)
    image_frame.pack()
    canvas = tk.Canvas(image_frame, width=preview_size[0], height=preview_size[1])
    im_img = canvas.create_image(0, 0, image=cim, anchor=tk.NW)
    canvas.itemconfig(im_img, image=cim)
    canvas.image = cim
    canvas.grid(row=0, column=0, sticky='w')

    if sat_image is not None:
        sim = Image.fromarray(sat_image.astype(np.uint8), 'RGB')
        sim.thumbnail(preview_size, PIL.Image.LANCZOS)
        scim = ImageTk.PhotoImage(image=sim)
        sat_canvas = tk.Canvas(image_frame, width=preview_size[0], height=preview_size[1])
        sat_img = sat_canvas.create_image(0, 0, image=scim, anchor=tk.NW)
        sat_canvas.itemconfig(sat_img, image=scim)
        sat_canvas.image = scim
        sat_canvas.grid(row=0, column=preview_size[0] + 10, sticky='e')

    # Reset rectangle state for this popup.
    rect = None
    rectx0 = 0; recty0 = 0
    rectx1 = im.size[0]; recty1 = im.size[1]
    createCanvasBinding()
    popup.protocol("WM_DELETE_WINDOW", cancel)
    popup.transient()
    popup.grab_set()
    popup.wait_window()

    return result["crop"] if result["accepted"] else None


def generate_lidar_previews(lidar_dir_path, sample_scale, output_dir_path, force_epsg=None, force_unit=None, printf=print, local_osm_file=None, auto_red_mask_enabled=False, auto_red_mask_buffer_m=5.0):
    """Legacy synchronous wrapper; GUI uses prepare/show worker split."""
    prepared = prepare_lidar_previews(
        lidar_dir_path,
        sample_scale,
        output_dir_path,
        force_epsg=force_epsg,
        force_unit=force_unit,
        printf=printf,
        local_osm_file=local_osm_file,
        auto_red_mask_enabled=auto_red_mask_enabled,
        auto_red_mask_buffer_m=auto_red_mask_buffer_m,
    )
    if prepared is None:
        return
    crop = show_prepared_lidar_preview(prepared, printf=printf)
    if crop is None:
        printf("LiDAR boundary selection cancelled.")
        return
    generate_lidar_heightmap(
        prepared["pc"],
        prepared["img_points"],
        prepared["sample_scale"],
        prepared["output_dir_path"],
        prepared["osm_result"],
        prepared["auto_red_mask_enabled"],
        prepared["auto_red_mask_buffer_m"],
        crop_bounds=crop,
        printf=printf,
    )

def generate_lidar_heightmap(pc, img_points, sample_scale, output_dir_path, osm_results=None, auto_red_mask_enabled=False, auto_red_mask_buffer_m=5.0, crop_bounds=None, printf=print):
    global lower_x, lower_y, upper_x, upper_y

    image_width = math.ceil(pc.width / sample_scale) + 1
    image_height = math.ceil(pc.height / sample_scale) + 1

    if crop_bounds is not None:
        lower_x, lower_y, upper_x, upper_y = [int(v) for v in crop_bounds]

    lower_x = max(0, lower_x)
    lower_y = max(0, lower_y)
    upper_x = min(image_width, upper_x)
    upper_y = min(image_height, upper_y)

    printf("Selecting only needed data from lidar (single-pass mask)")
    llenu = pc.cv2ToENU(upper_y, lower_x, sample_scale)
    urenu = pc.cv2ToENU(lower_y, upper_x, sample_scale)

    rows = img_points[:, 0]
    cols = img_points[:, 1]
    selection_mask = (
        (rows >= lower_y) & (rows < upper_y) &
        (cols >= lower_x) & (cols < upper_x)
    )
    selected_points = img_points[selection_mask]

    ground_mask = np.isin(selected_points[:, 4], wanted_classifications)
    ground_points = selected_points[ground_mask]

    if len(ground_points) == 0:
        printf("\n\n\nSorry, this lidar data is not classified and I can't support it right now. Ask for help on the forum or your lidar provider if they have a classified version.")
        printf("Classification is where they determine which points are the ground and which are trees, buildings, etc. I can't make a nice looking course without clean input.")
        return

    visualization_axis = 3
    if pc.imin == pc.imax:
        printf("No lidar intensity found, using elevation instead")
        visualization_axis = 2

    printf(
        "Generating heightmap with LiDAR Fast exact rasterizer: " +
        ("native C" if lidar_fast_native.native_available() else "Python fallback")
    )
    work_points = ground_points[0::lidar_sample]
    om, high_res_visual = lidar_fast_native.accumulate_height_and_visual(
        work_points,
        image_height,
        image_width,
        visualization_axis,
        printf=printf,
    )
    printf("Finished generating heightmap")

    printf("Starting tree detection (vectorized maximum map)")
    trees = []
    tree_ratio = 2 ** (math.ceil(math.log2(1.0 / sample_scale)))
    tree_scale = sample_scale * tree_ratio
    printf("Tree ratio is: " + str(tree_ratio))

    tree_h = int(image_height / tree_ratio)
    tree_w = int(image_width / tree_ratio)
    tree_flat = np.full(tree_h * tree_w, -np.inf, dtype=np.float32)

    tree_points = selected_points[0::lidar_sample]
    tr = (tree_points[:, 0] / tree_ratio).astype(np.int64, copy=False)
    tc = (tree_points[:, 1] / tree_ratio).astype(np.int64, copy=False)
    valid_tree = (
        (tr >= 0) & (tr < tree_h) &
        (tc >= 0) & (tc < tree_w)
    )
    tr = tr[valid_tree]
    tc = tc[valid_tree]
    tz = tree_points[valid_tree, 2].astype(np.float32, copy=False)
    if len(tr):
        np.maximum.at(tree_flat, tr * tree_w + tc, tz)
    tree_flat[np.isneginf(tree_flat)] = np.nan
    treemap = tree_flat.reshape(tree_h, tree_w, 1)

    groundmap = np.copy(om[lower_y:upper_y, lower_x:upper_x])
    groundmap = numpy.array(
        Image.fromarray(groundmap[:, :, 0], mode='F').resize(
            (
                int(groundmap.shape[1] / tree_ratio),
                int(groundmap.shape[0] / tree_ratio),
            ),
            resample=Image.NEAREST,
        )
    )
    groundmap = np.expand_dims(groundmap, axis=2)
    img_trees = tree_mapper.getTreeCoordinates(
        groundmap,
        treemap[
            int(lower_y / tree_ratio):int(upper_y / tree_ratio),
            int(lower_x / tree_ratio):int(upper_x / tree_ratio),
        ],
        printf=printf,
    )
    trees = []
    for t in img_trees:
        proj = pc.cv2ToProj(
            int(lower_y / tree_ratio) + t[1],
            int(lower_x / tree_ratio) + t[0],
            tree_scale,
        )
        trees.append((proj[0], proj[1], t[2], t[3]))

    buildings = lidar_feature_filter.detect_lidar_building_footprints(
        selected_points,
        pc,
        sample_scale,
        (image_height, image_width),
        printf=printf,
    )
    printf("LiDAR building footprint candidates stored: " + str(len(buildings)))

    printf("Writing files to disk")
    # Preserve historical output semantics. The raw point cloud is not written
    # unless lidar_to_disk is explicitly enabled (that path remains unsupported).
    output_points = []
    if lidar_to_disk:
        printf("Writing the original points to disk not yet supported")

    # Preserve the historical mask/preview base image exactly: the high-res
    # ground visual is normalized first, then OSM/mask colors are painted over it.
    imc = np.copy(high_res_visual)
    imc = normalize_image(imc)
    imc = cv2.cvtColor(imc, cv2.COLOR_GRAY2RGB)
    if osm_results is not None:
        imc = OSMTGC.addOSMToImage(osm_results.ways, imc, pc, sample_scale)
        if auto_red_mask_enabled:
            imc = auto_red_mask.apply_auto_red_mask(
                osm_results,
                imc,
                pc,
                sample_scale,
                buffer_m=auto_red_mask_buffer_m,
                printf=printf,
            )
    elif auto_red_mask_enabled:
        printf("Auto Red Mask requested, but no OSM result is available; leaving mask unchanged.")
    imc = imc[lower_y:upper_y, lower_x:upper_x]
    imc = np.flip(imc, 0)
    printf("Saving mask as: " + str(output_dir_path) + '/mask.png')
    cv2.imwrite(
        output_dir_path + '/mask.png',
        cv2.cvtColor(255.0 * imc, cv2.COLOR_RGB2BGR),
    )

    high_res_visual = high_res_visual[lower_y:upper_y, lower_x:upper_x]
    high_res_visual = normalize_image(high_res_visual)
    high_res_visual = cv2.cvtColor(high_res_visual, cv2.COLOR_GRAY2RGB)

    omc = om[lower_y:upper_y, lower_x:upper_x]
    output_data = {'heightmap': omc}
    output_data['visual'] = high_res_visual
    output_data['pointcloud'] = output_points
    output_data['image_scale'] = sample_scale

    master_grid = cfs_georef.make_master_grid_from_crop(
        pc,
        lower_x,
        lower_y,
        upper_x,
        upper_y,
        sample_scale,
        source="LiDAR",
    )
    output_data['origin'] = cfs_georef.master_grid_origin_latlon(master_grid)
    output_data['projection'] = pc.proj
    output_data['master_grid'] = master_grid
    output_data['trees'] = trees
    output_data['buildings'] = buildings

    cfs_georef.describe_master_grid(master_grid, printf=printf)
    cfs_georef.write_master_grid_json(output_dir_path, master_grid)
    printf("Saving data as: " + str(output_dir_path) + '/heightmap.npy')
    np.save(output_dir_path + '/heightmap', output_data)

    printf("Done! Now go edit your mask.png to remove uneeded areas")


def _projection_to_crs(projection):
    if projection is None:
        return None
    for candidate in (
        getattr(projection, "crs", None),
        getattr(projection, "srs", None),
        projection,
    ):
        if candidate is None:
            continue
        try:
            return pyproj.CRS.from_user_input(candidate)
        except Exception:
            pass
    return None



def fill_missing_terrain_from_lidar(
    lidar_dir_path,
    heightmap_path,
    force_epsg=None,
    source_metadata=None,
    printf=print,
):
    """Fill only missing cells in an existing terrain from a fallback LiDAR set.

    The existing heightmap/master grid is authoritative. Valid primary terrain
    is never replaced. Fallback Class-2/Class-8 ground is rasterized directly
    onto the primary master grid and is used only where the primary elevation
    is NaN/non-finite.

    A robust median overlap delta is used to remove small vertical acquisition
    bias. Large (>2 m) apparent offsets are not applied automatically because
    they are more likely to indicate an incompatible vertical datum.
    """
    terrain_path = Path(heightmap_path)
    if terrain_path.is_dir():
        terrain_path = terrain_path / "heightmap.npy"
    if not terrain_path.is_file():
        raise FileNotFoundError(
            "Existing heightmap.npy was not found: " + str(terrain_path)
        )

    primary = np.load(
        str(terrain_path),
        allow_pickle=True,
    ).item()

    if "heightmap" not in primary:
        raise ValueError("Existing heightmap.npy contains no heightmap array")

    heightmap = np.asarray(primary["heightmap"])
    if heightmap.ndim == 3 and heightmap.shape[2] >= 1:
        primary_elevation = np.array(
            heightmap[:, :, 0],
            dtype=np.float32,
            copy=True,
        )
        heightmap_is_3d = True
    elif heightmap.ndim == 2:
        primary_elevation = np.array(
            heightmap,
            dtype=np.float32,
            copy=True,
        )
        heightmap_is_3d = False
    else:
        raise ValueError(
            "Unsupported existing heightmap shape: " + str(heightmap.shape)
        )

    grid = cfs_georef.get_master_grid(
        primary,
        heightmap,
        printf=printf,
    )
    resolution = float(grid["resolution"])
    rows = int(primary_elevation.shape[0])
    cols = int(primary_elevation.shape[1])

    if int(grid.get("rows", rows)) != rows or int(grid.get("cols", cols)) != cols:
        raise ValueError(
            "Stored master grid dimensions do not match heightmap.npy"
        )

    target_crs = _projection_to_crs(primary.get("projection"))
    if target_crs is None:
        wkt = grid.get("crs_wkt")
        if wkt:
            try:
                target_crs = pyproj.CRS.from_user_input(wkt)
            except Exception:
                target_crs = None
    if target_crs is None:
        raise RuntimeError(
            "Could not resolve the primary terrain horizontal CRS"
        )

    missing_before = ~np.isfinite(primary_elevation)
    missing_count_before = int(np.count_nonzero(missing_before))
    if missing_count_before == 0:
        printf(
            "Terrain Gap Fill: primary terrain has no missing elevation cells; "
            "nothing to fill."
        )
        return {
            "filled_cells": 0,
            "missing_before": 0,
            "missing_after": 0,
            "vertical_offset_m": 0.0,
            "overlap_cells": 0,
        }

    printf(
        "Terrain Gap Fill: primary grid " +
        str(cols) + " x " + str(rows) +
        " at " + str(resolution) + " m."
    )
    printf(
        "Terrain Gap Fill: missing primary cells before fill = " +
        str(missing_count_before)
    )
    printf(
        "Loading fallback LiDAR. Primary valid terrain will never be overwritten."
    )

    fallback_pc = load_usgs_directory(
        str(lidar_dir_path),
        force_epsg=force_epsg,
        printf=printf,
    )
    if fallback_pc is None or not fallback_pc.count:
        raise RuntimeError("Fallback LAS/LAZ directory contained no usable LiDAR")

    points = np.asarray(fallback_pc.point_matrix)
    if points.ndim != 2 or points.shape[1] < 5:
        raise RuntimeError("Fallback LiDAR point matrix is invalid")

    ground_mask = np.isin(
        points[:, 4].astype(np.int32, copy=False),
        wanted_classifications,
    )
    ground = points[ground_mask]
    if len(ground) == 0:
        raise RuntimeError(
            "Fallback LiDAR contains no Class-2/Class-8 ground points"
        )

    source_crs = _projection_to_crs(fallback_pc.proj)
    if source_crs is None:
        raise RuntimeError("Could not resolve fallback LiDAR horizontal CRS")

    # load_usgs_directory() stores XY in metre-normalized ENU coordinates
    # relative to fallback_pc.origin. Reconstruct projected XY before mapping
    # onto the primary terrain's authoritative master grid.
    source_x = (
        ground[:, 0].astype(np.float64, copy=False) +
        float(fallback_pc.origin[0])
    )
    source_y = (
        ground[:, 1].astype(np.float64, copy=False) +
        float(fallback_pc.origin[1])
    )
    z = ground[:, 2].astype(np.float64, copy=False)

    if source_crs != target_crs:
        printf(
            "Terrain Gap Fill: reprojecting fallback LiDAR from " +
            str(source_crs.to_string()) + " to " +
            str(target_crs.to_string()) + "."
        )
        transformer = pyproj.Transformer.from_crs(
            source_crs,
            target_crs,
            always_xy=True,
        )
        target_x, target_y = transformer.transform(source_x, source_y)
        target_x = np.asarray(target_x, dtype=np.float64)
        target_y = np.asarray(target_y, dtype=np.float64)
    else:
        target_x = source_x
        target_y = source_y

    min_x = float(grid["min_x"])
    min_y = float(grid["min_y"])

    mapped_cols = np.floor(
        (target_x - min_x) / resolution
    ).astype(np.int64)
    mapped_rows = np.floor(
        (target_y - min_y) / resolution
    ).astype(np.int64)

    in_bounds = (
        np.isfinite(target_x) &
        np.isfinite(target_y) &
        np.isfinite(z) &
        (mapped_rows >= 0) & (mapped_rows < rows) &
        (mapped_cols >= 0) & (mapped_cols < cols)
    )

    if not np.any(in_bounds):
        raise RuntimeError(
            "Fallback LiDAR does not overlap the existing terrain master grid"
        )

    mapped_rows = mapped_rows[in_bounds]
    mapped_cols = mapped_cols[in_bounds]
    mapped_z = z[in_bounds]

    # Reuse the normal exact LiDAR rasterizer so fallback cells are calculated
    # with the same elevation accumulation behavior as primary LiDAR terrain.
    raster_points = np.empty(
        (len(mapped_rows), 5),
        dtype=np.float64,
    )
    raster_points[:, 0] = mapped_rows
    raster_points[:, 1] = mapped_cols
    raster_points[:, 2] = mapped_z
    raster_points[:, 3] = 0.0
    raster_points[:, 4] = 2.0

    fallback_raster, _unused_visual = (
        lidar_fast_native.accumulate_height_and_visual(
            raster_points,
            rows,
            cols,
            3,
            printf=printf,
        )
    )
    fallback_elevation = fallback_raster[:, :, 0].astype(
        np.float32,
        copy=False,
    )

    primary_valid = np.isfinite(primary_elevation)
    fallback_valid = np.isfinite(fallback_elevation)
    overlap_mask = primary_valid & fallback_valid
    overlap_count = int(np.count_nonzero(overlap_mask))

    vertical_offset = 0.0
    offset_applied = False

    if overlap_count >= 50:
        differences = (
            primary_elevation[overlap_mask].astype(np.float64) -
            fallback_elevation[overlap_mask].astype(np.float64)
        )
        differences = differences[np.isfinite(differences)]

        if differences.size:
            median_delta = float(np.median(differences))
            absolute_deviation = np.abs(differences - median_delta)
            mad = float(np.median(absolute_deviation))

            if math.isfinite(mad) and mad > 1.0e-6:
                robust_sigma = 1.4826 * mad
                tolerance = max(0.20, 4.0 * robust_sigma)
                keep = absolute_deviation <= tolerance
                if int(np.count_nonzero(keep)) >= 25:
                    median_delta = float(
                        np.median(differences[keep])
                    )

            if math.isfinite(median_delta):
                if abs(median_delta) <= 2.0:
                    vertical_offset = median_delta
                    offset_applied = True
                    printf(
                        "Terrain Gap Fill: robust overlap vertical offset = " +
                        str(round(vertical_offset, 4)) +
                        " m from " + str(overlap_count) +
                        " overlapping cells; applying to fallback terrain."
                    )
                else:
                    printf(
                        "WARNING: Terrain Gap Fill measured a " +
                        str(round(median_delta, 3)) +
                        " m primary/fallback vertical offset. This exceeds "
                        "the 2 m automatic-safety limit, so no vertical "
                        "correction was applied. Verify the vertical datum/geoid."
                    )
    else:
        printf(
            "Terrain Gap Fill: only " + str(overlap_count) +
            " overlapping valid cells; not enough for automatic vertical "
            "offset correction."
        )

    adjusted_fallback = fallback_elevation
    if offset_applied and vertical_offset != 0.0:
        adjusted_fallback = (
            fallback_elevation.astype(np.float64) +
            vertical_offset
        ).astype(np.float32)

    fill_mask = missing_before & np.isfinite(adjusted_fallback)
    filled_cells = int(np.count_nonzero(fill_mask))

    if filled_cells == 0:
        printf(
            "Terrain Gap Fill: fallback LiDAR contains no valid ground in "
            "the primary terrain's missing cells."
        )
        return {
            "filled_cells": 0,
            "missing_before": missing_count_before,
            "missing_after": missing_count_before,
            "vertical_offset_m": vertical_offset,
            "overlap_cells": overlap_count,
        }

    backup_path = (
        terrain_path.parent /
        "heightmap_before_lidar_gap_fill.npy"
    )
    if not backup_path.exists():
        shutil.copy2(terrain_path, backup_path)
        printf(
            "Saved primary-terrain backup: " + str(backup_path)
        )

    primary_elevation[fill_mask] = adjusted_fallback[fill_mask]

    if heightmap_is_3d:
        updated_heightmap = np.array(heightmap, copy=True)
        updated_heightmap[:, :, 0] = primary_elevation
    else:
        updated_heightmap = primary_elevation

    primary["heightmap"] = updated_heightmap

    gap_history = primary.get("terrain_gap_fill_history")
    if not isinstance(gap_history, list):
        gap_history = []

    safe_metadata = {}
    if isinstance(source_metadata, dict):
        for key, value in source_metadata.items():
            if key == "ept_resources":
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_metadata[key] = value
            elif isinstance(value, (list, tuple)):
                safe_metadata[key] = [str(item) for item in value]
            else:
                safe_metadata[key] = str(value)

    missing_after = int(
        np.count_nonzero(~np.isfinite(primary_elevation))
    )

    gap_record = {
        "source": "LiDAR terrain gap fill",
        "fallback_directory": str(lidar_dir_path),
        "force_epsg": (
            int(force_epsg) if force_epsg is not None else None
        ),
        "filled_cells": filled_cells,
        "missing_before": missing_count_before,
        "missing_after": missing_after,
        "overlap_cells": overlap_count,
        "vertical_offset_m": float(vertical_offset),
        "vertical_offset_applied": bool(offset_applied),
        "fallback_crs": source_crs.to_string(),
        "primary_crs": target_crs.to_string(),
        "metadata": safe_metadata,
    }
    gap_history.append(gap_record)
    primary["terrain_gap_fill_history"] = gap_history
    primary["terrain_gap_fill_last"] = gap_record

    np.save(str(terrain_path), primary)

    # Diagnostic mask: white pixels are cells supplied by fallback LiDAR.
    diagnostic = np.zeros((rows, cols), dtype=np.uint8)
    diagnostic[fill_mask] = 255
    diagnostic_path = (
        terrain_path.parent / "lidar_gap_fill_mask.png"
    )
    cv2.imwrite(
        str(diagnostic_path),
        np.flip(diagnostic, 0),
    )

    report_path = (
        terrain_path.parent / "lidar_gap_fill_report.json"
    )
    try:
        report_path.write_text(
            json.dumps(gap_record, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    printf(
        "Terrain Gap Fill complete: filled " +
        str(filled_cells) + " missing cell(s); remaining missing cells=" +
        str(missing_after) + "."
    )
    printf(
        "Valid primary terrain cells overwritten: 0."
    )
    printf(
        "Gap-fill diagnostic mask: " + str(diagnostic_path)
    )
    return gap_record



def attach_lidar_trees_to_existing_dem(
    lidar_dir_path,
    dem_heightmap_path,
    sample_scale=1.0,
    local_osm_file=None,
    force_epsg=None,
    source_metadata=None,
    printf=print,
):
    """Detect trees from LiDAR and inject them into an existing DEM heightmap.

    Terrain, mask, DEM resolution and DEM master grid are preserved exactly.
    Only the projected LiDAR tree candidate list and tree-source metadata are
    replaced.
    """
    sample_scale = float(sample_scale)
    if sample_scale <= 0.0:
        raise ValueError("Tree extraction sample scale must be greater than zero")

    dem_path = Path(dem_heightmap_path)
    if dem_path.is_dir():
        dem_path = dem_path / "heightmap.npy"
    if not dem_path.is_file():
        raise FileNotFoundError(
            "DEM heightmap.npy was not found: " + str(dem_path)
        )

    dem_data = np.load(
        str(dem_path),
        allow_pickle=True,
    ).item()

    source_kind = str(dem_data.get("source", "") or "")
    if "DEM" not in source_kind.upper():
        raise ValueError(
            "Trees Only requires an existing DEM-generated heightmap.npy. "
            "Current source is: " + (source_kind or "unknown")
        )

    temp_dir = dem_path.parent / "_TGC_LIDAR_TREE_EXTRACT"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    printf(
        "Tree-only LiDAR extraction: terrain will remain from the existing DEM."
    )
    printf(
        "LiDAR is being rasterized only to reproduce the normal Beta 5 "
        "tree-detection logic."
    )

    try:
        prepared = prepare_lidar_previews(
            lidar_dir_path,
            sample_scale,
            str(temp_dir),
            force_epsg=force_epsg,
            printf=printf,
            local_osm_file=local_osm_file,
            auto_red_mask_enabled=False,
            auto_red_mask_buffer_m=5.0,
        )
        if prepared is None:
            raise RuntimeError("LiDAR preparation returned no point cloud")

        pc = prepared["pc"]
        image_width = math.ceil(pc.width / sample_scale) + 1
        image_height = math.ceil(pc.height / sample_scale) + 1

        generate_lidar_heightmap(
            pc,
            prepared["img_points"],
            sample_scale,
            str(temp_dir),
            prepared.get("osm_result"),
            False,
            5.0,
            crop_bounds=(0, 0, image_width, image_height),
            printf=printf,
        )

        extracted_path = temp_dir / "heightmap.npy"
        if not extracted_path.is_file():
            raise RuntimeError(
                "Tree-only LiDAR extraction did not create its temporary heightmap"
            )

        lidar_data = np.load(
            str(extracted_path),
            allow_pickle=True,
        ).item()
        lidar_trees = list(lidar_data.get("trees") or [])

        if not lidar_trees:
            raise RuntimeError(
                "Selected LiDAR dataset produced no tree candidates"
            )

        source_crs = _projection_to_crs(lidar_data.get("projection"))
        target_crs = _projection_to_crs(dem_data.get("projection"))
        if source_crs is None or target_crs is None:
            raise RuntimeError(
                "Could not resolve LiDAR and DEM coordinate reference systems "
                "for tree reprojection"
            )

        transformed_trees = []
        if source_crs == target_crs:
            transformed_trees = [
                (
                    float(tree[0]),
                    float(tree[1]),
                    float(tree[2]),
                    float(tree[3]),
                )
                for tree in lidar_trees
            ]
        else:
            transformer = pyproj.Transformer.from_crs(
                source_crs,
                target_crs,
                always_xy=True,
            )
            xs = np.asarray(
                [float(tree[0]) for tree in lidar_trees],
                dtype=np.float64,
            )
            ys = np.asarray(
                [float(tree[1]) for tree in lidar_trees],
                dtype=np.float64,
            )
            out_x, out_y = transformer.transform(xs, ys)
            transformed_trees = [
                (
                    float(out_x[index]),
                    float(out_y[index]),
                    float(tree[2]),
                    float(tree[3]),
                )
                for index, tree in enumerate(lidar_trees)
            ]

        backup_path = dem_path.parent / "heightmap_before_lidar_trees.npy"
        if not backup_path.exists():
            shutil.copy2(dem_path, backup_path)
            printf(
                "Saved DEM-only backup: " + str(backup_path)
            )

        dem_data["trees"] = transformed_trees
        dem_data["tree_source"] = "LiDAR"
        dem_data["tree_source_count"] = len(transformed_trees)
        dem_data["tree_source_projection"] = source_crs.to_string()
        dem_data["tree_source_sample_scale"] = float(sample_scale)
        dem_data["tree_source_force_epsg"] = (
            int(force_epsg) if force_epsg is not None else None
        )

        if isinstance(source_metadata, dict):
            safe_metadata = {}
            for key, value in source_metadata.items():
                if key == "ept_resources":
                    continue
                if isinstance(value, (str, int, float, bool)) or value is None:
                    safe_metadata[key] = value
                elif isinstance(value, (list, tuple)):
                    safe_metadata[key] = [
                        str(item) for item in value
                    ]
                else:
                    safe_metadata[key] = str(value)
            dem_data["tree_source_metadata"] = safe_metadata

        np.save(str(dem_path), dem_data)

        printf(
            "Trees Only complete: injected " +
            str(len(transformed_trees)) +
            " LiDAR tree candidate(s) into the DEM heightmap."
        )
        printf(
            "DEM terrain array, DEM mask, image scale and master grid were preserved."
        )
        return len(transformed_trees)

    finally:
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python program.py LAS_DIRECTORY OUTPUT_DIRECTORY METERS_PER_PIXEL [FORCE_EPSG] [FORCE_UNIT]")
        sys.exit(0)
    else:
        lidar_dir_path = sys.argv[1]
        output_dir = sys.argv[2]
        meters_per_pixel = float(sys.argv[3])
        try:
            force_epsg = int(sys.argv[4])
        except:
            force_epsg = None
        try:
            force_unit = float(sys.argv[5])
        except:
            force_unit = None

    running_as_main = True
    generate_lidar_previews(lidar_dir_path, meters_per_pixel, output_dir, force_epsg=force_epsg, force_unit=force_unit)
