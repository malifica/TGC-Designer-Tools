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
import overpy
import scipy
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
