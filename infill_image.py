import cv2
import math
import numpy as np

from scipy.interpolate import griddata

def apply_mask(np_array, mask, invalid_value=math.nan):
    np_array[ mask < 1 ] = invalid_value
    return np_array

def get_binary_mask(cv2_mask):
    if cv2_mask is None:
        return None, None

    # The two reds in MS Paint are
    # Bright Red: 236, 28, 36
    # Dark Red: 136, 0, 27
    # Try to support both here
    red_pixels = np.logical_and(np.logical_and(cv2_mask[:,:,0] < 40, cv2_mask[:,:,1] < 40), cv2_mask[:,:,2] > 130)

    # The blues in Paint3d are:
    # Indigo: 62, 73, 204
    # Turquoise: 0, 168, 243
    blue_pixels = np.logical_and(np.logical_and(cv2_mask[:,:,0] > 200, cv2_mask[:,:,1] < 180), cv2_mask[:,:,2] < 70)

    # Don't infill areas painted in Red
    # Red turns to black, otherwise, white.  Black will not be infilled or sent in the output image
    remove_mask = (255.0*np.ones((cv2_mask.shape[0], cv2_mask.shape[1], 1))).astype('uint8')
    remove_mask[red_pixels] = 0

    # Preserve original terrain for areas marked in Blue
    preserve_mask = (np.zeros((cv2_mask.shape[0], cv2_mask.shape[1], 1))).astype('uint8')
    preserve_mask[blue_pixels] = 255

    return remove_mask, preserve_mask

# Uses scipy griddata to interpolate and "recompute" the terrain data based on only the valid image points
# Seems to produce a smoother and more natural result
# Also allows us to sample in arbitrary sizes
def infill_image_scipy(np_array, cv2_mask, background_ratio=16.0, fill_water=False, purge_water=False, printf=print):
    remove_mask, preserve_mask = get_binary_mask(cv2_mask)

    values_2d = np.asarray(np_array[:, :, 0])
    rows, cols = values_2d.shape

    printf("Finding valid masked points (vectorized)")

    finite = np.isfinite(values_2d)
    full_points = np.argwhere(finite)
    full_values = values_2d[finite]

    if remove_mask is None:
        keep = np.ones((rows, cols), dtype=bool)
    else:
        keep = remove_mask[:, :, 0] > 0

    detail_valid = finite & keep
    points = np.argwhere(detail_valid)
    values = values_2d[detail_valid]

    # Row-major ordering matches the historical nested loops exactly.
    grid_rows, grid_cols = np.indices((rows, cols), dtype=np.int32)
    outs = np.column_stack((grid_rows.ravel(), grid_cols.ravel()))

    background_map = None
    background_preserve_mask = None
    if background_ratio is not None:
        printf("Generating low detail background")
        starts = np.array([0, 0], dtype=float)
        ends = np.array([rows - 1, cols - 1], dtype=float)
        background_row_count = math.ceil((ends[0] - starts[0]) / background_ratio)
        background_col_count = math.ceil((ends[1] - starts[1]) / background_ratio)
        background_outs = np.mgrid[
            starts[0]:ends[0]:background_ratio,
            starts[1]:ends[1]:background_ratio,
        ].reshape(2, -1).T
        background_grid_z = griddata(
            full_points,
            full_values,
            background_outs,
            method='linear',
            fill_value=-1.0,
        )
        background_map = background_grid_z.reshape(
            (background_row_count, background_col_count)
        )

        if preserve_mask is not None:
            background_preserve_mask = cv2.resize(
                preserve_mask,
                (background_col_count, background_row_count),
                interpolation=cv2.INTER_AREA,
            )

    printf("Filling missing data in heightmap")
    detail_grid_z = griddata(
        points,
        values,
        outs,
        method='linear',
        fill_value=math.nan,
    )

    if remove_mask is not None:
        red_masked = apply_mask(
            detail_grid_z.reshape(np_array.shape),
            remove_mask,
        )
        blue_indices = preserve_mask > 0
        if not fill_water:
            red_masked[blue_indices] = np_array[blue_indices]
        if purge_water:
            red_masked[blue_indices] = math.nan

        if background_map is not None and background_preserve_mask is not None:
            background_blue_indices = background_preserve_mask > 0
            background_map[background_blue_indices] = math.nan
        return red_masked, background_map, remove_mask

    return detail_grid_z.reshape(np_array.shape), background_map, remove_mask
