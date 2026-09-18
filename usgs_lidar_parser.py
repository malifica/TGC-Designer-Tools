from difflib import SequenceMatcher
import itertools
import json
import laspy
import math
import numpy
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pyproj

from GeoPointCloud import *

def get_unit_multiplier_from_epsg(epsg):
    # Can't find any lightweight way to do this, but I depend heavily on pyproj right now
    # Until there's a better way, get the unit by converting (1,0) from 'unit' to 'meter'
    meter_proj = pyproj.Proj('epsg:'+str(epsg), preserve_units=False) # Forces meter
    unit_proj = pyproj.Proj('epsg:'+str(epsg), preserve_units=True) # Stays in native unit
    try:
        # Due to numerical precision and the requirements for foot vs survey foot
        # Use a larger number for the transform
        scale_value = 1.0e6
        transformer = pyproj.Transformer.from_proj(unit_proj, meter_proj, True)
        x2, y2 = transformer.transform(scale_value, 0.0)
        return x2/scale_value
    except:
        pass
    return 0.0

# Some of the epsgs found in lidar files don't represent projected coordinate systems
# but are instead the datum or other geographic reference systems
def is_epsg_datum(epsg):
    # It looks like these are all in the 4000 to 42NN range.
    # I can't determine which are valid, so I'm going to convert from meters to degrees
    # If it's degrees to degrees, it won't modify the number
    # The coordinate systems we will look for are limited between -180.0 and 180.0 output
    meter_proj = pyproj.Proj('epsg:'+str(epsg), preserve_units=False) # Forces meter
    degree_proj = pyproj.Proj(proj='latlong', datum='WGS84')
    try:
        scale_value = 1.0e6
        transformer = pyproj.Transformer.from_proj(degree_proj, meter_proj, True)
        x2, y2 = transformer.transform(scale_value, 0.0)
        return math.isclose(scale_value, x2, abs_tol=1.0) # Should be very different
    except:
        pass
    return True # Invalidate this EPSG if it can't be determined or used

def proj_from_epsg(epsg, printf=print):
    if is_epsg_datum(epsg):
        # Not the right kind of coordinate reference system
        printf("EPSG is not map projection, skipping: " + str(epsg))
        return None, 0.0
    if epsg is not None:
        printf("Overwriting projection with EPSG:" + str(epsg))
        proj = pyproj.Proj('epsg:'+str(epsg), preserve_units=False)
        unit = get_unit_multiplier_from_epsg(epsg)
        return (proj, unit)
    return None, 0.0

def convert_latlon_to_utm_espg(lat, lon):
    utm_band = str((math.floor((lon + 180) / 6 ) % 60) + 1)
    if len(utm_band) == 1:
        utm_band = '0'+utm_band
    if lat >= 0:
        epsg_code = '326' + utm_band
    else:
        epsg_code = '327' + utm_band
    return int(epsg_code)


def _axis_unit_multiplier(crs):
    """Return native CRS linear-unit -> meter multiplier from pyproj axis metadata."""
    try:
        axis_info = crs.axis_info
        if axis_info:
            factor = float(axis_info[0].unit_conversion_factor)
            if math.isfinite(factor) and factor > 0.0:
                return factor
    except Exception:
        pass
    return 0.0


def _find_las_horizontal_vertical_crs(crs):
    """
    Split a pyproj CRS into the projected horizontal CRS used for XY and,
    when present, the vertical CRS used for Z.

    For compound CRS objects, inspect sub_crs_list FIRST.  pyproj may expose
    aggregate properties on the compound object that make the parent appear
    usable for both horizontal and vertical reporting.
    """
    if crs is None:
        return None, None

    horizontal = None
    vertical = None

    sub_crs_list = list(getattr(crs, "sub_crs_list", []) or [])

    if sub_crs_list:
        pending = list(sub_crs_list)

        while pending:
            sub = pending.pop(0)

            if horizontal is None and getattr(sub, "is_projected", False):
                horizontal = sub

            if vertical is None and getattr(sub, "is_vertical", False):
                vertical = sub

            children = list(getattr(sub, "sub_crs_list", []) or [])
            if children:
                pending.extend(children)

        return horizontal, vertical

    if getattr(crs, "is_projected", False):
        horizontal = crs

    if getattr(crs, "is_vertical", False):
        vertical = crs

    return horizontal, vertical


def proj_from_las_header(header, printf=print):
    """
    Preferred modern CRS parser.

    Returns:
      (horizontal_projection_in_meters, xy_unit_to_meters, z_unit_to_meters)
    """
    try:
        crs = header.parse_crs()
    except Exception as exc:
        printf("Modern LiDAR CRS parse failed: " + str(exc))
        return None, 0.0, 0.0

    if crs is None:
        return None, 0.0, 0.0

    horizontal_crs, vertical_crs = _find_las_horizontal_vertical_crs(crs)

    if horizontal_crs is None:
        printf(
            "LiDAR CRS metadata was found, but no projected horizontal CRS "
            "was present; trying legacy/fallback detection."
        )
        return None, 0.0, 0.0

    horizontal_epsg = None
    vertical_epsg = None

    try:
        horizontal_epsg = horizontal_crs.to_epsg()
    except Exception:
        pass

    if vertical_crs is not None:
        try:
            vertical_epsg = vertical_crs.to_epsg()
        except Exception:
            pass

    xy_unit = _axis_unit_multiplier(horizontal_crs)

    if xy_unit <= 0.0 and horizontal_epsg is not None:
        try:
            xy_unit = get_unit_multiplier_from_epsg(horizontal_epsg)
        except Exception:
            xy_unit = 0.0

    z_unit = 0.0
    if vertical_crs is not None:
        z_unit = _axis_unit_multiplier(vertical_crs)

    if z_unit <= 0.0:
        z_unit = xy_unit

    if xy_unit <= 0.0:
        printf(
            "Modern LiDAR CRS was parsed but its horizontal linear unit "
            "could not be determined; trying legacy/fallback detection."
        )
        return None, 0.0, 0.0

    try:
        proj = pyproj.Proj(horizontal_crs, preserve_units=False)
    except Exception as exc:
        printf(
            "Modern LiDAR horizontal CRS could not be converted to a "
            "projected pyproj definition: " + str(exc)
        )
        return None, 0.0, 0.0

    printf("Automatically detected LiDAR CRS from LAS/LAZ header")

    try:
        printf("  Horizontal CRS: " + str(horizontal_crs.name))
    except Exception:
        pass

    if horizontal_epsg is not None:
        printf("  Horizontal EPSG: " + str(horizontal_epsg))
    else:
        printf("  Horizontal EPSG: not explicitly resolvable")

    try:
        if horizontal_crs.axis_info:
            printf("  Horizontal unit: " + str(horizontal_crs.axis_info[0].unit_name))
    except Exception:
        pass

    printf("  XY conversion to meters: " + str(xy_unit))

    if vertical_crs is not None:
        try:
            printf("  Vertical CRS: " + str(vertical_crs.name))
        except Exception:
            pass

        if vertical_epsg is not None:
            printf("  Vertical EPSG: " + str(vertical_epsg))
        else:
            printf("  Vertical EPSG: not explicitly resolvable")

        try:
            if vertical_crs.axis_info:
                printf("  Vertical unit: " + str(vertical_crs.axis_info[0].unit_name))
        except Exception:
            pass
    else:
        printf(
            "  Vertical CRS: not separately defined; "
            "using horizontal linear unit for Z"
        )

    printf("  Z conversion to meters: " + str(z_unit))

    return proj, xy_unit, z_unit


def print_failure_message(printf=print):
    printf("Could not determine lidar projection, please report an issue and send this lidar and metadata")
    printf("Alternatively, look for something called EPSG Value in Metadata and provide EPSG.")
    return None

def load_usgs_directory(d, force_epsg=None, force_unit=None, printf=print):
    pc = GeoPointCloud()

    # Add current directory to os path to find laszip-cli for laz files
    os.environ["PATH"] += os.pathsep + os.getcwd()
    # Add ./laszip
    os.environ["PATH"] += os.pathsep + "." + os.sep + 'laszip'
    # Add {this_file_location}/laszip for Pyinstaller temp directories
    os.environ["PATH"] += os.pathsep + os.path.dirname(os.path.realpath(__file__)) + os.sep + 'laszip'

    for filename in os.listdir(d):
        # Only parse laz and las files
        if not filename.endswith('.laz') and not filename.endswith('.las'): continue

        printf("Processing: " + filename)

        # Use laspy to load the point data
        try:
            with laspy.open(d+"/"+filename) as f:
                las = f.read()
                # Needed from metadata for all files
                proj = None
                unit = 0.0 # Horizontal XY unit -> meters
                z_unit = 0.0 # Vertical Z unit -> meters

                if force_epsg is not None:
                    proj, unit = proj_from_epsg(force_epsg, printf=printf)
                    z_unit = unit
                    printf("Manual horizontal EPSG override is active.")
                else:
                    proj, unit, z_unit = proj_from_las_header(
                        las.header,
                        printf=printf
                    )

                if proj is None:
                    # Legacy fallback: inspect individual VLRs / GeoTIFF keys.
                    for v in las.header.vlrs:
                        try:
                            proj = v.parse_crs()

                            if proj is not None:
                                epsg = proj.to_dict()
                                if 'units' in epsg:
                                    if epsg['units'] == 'm':
                                        unit = 1.0
                                    else:
                                        unit = 0.3048
                                else:
                                    unit = 0.0

                        except Exception as e:
                            # Do not erase a CRS successfully found by an earlier VLR.
                            print(e)

                        parsed_body = v.record_data_bytes()

                        # Look for GEOTIFF tags or something?  This is a list of values and EPSG codes
                        if proj is None and parsed_body is not None and len(parsed_body) > 3:
                            try:
                                num_records = parsed_body[3]
                                for i in range(0, num_records):
                                    key = parsed_body[4 + 4*i]
                                    value_offset = parsed_body[7 + 4*i]
                                    try:
                                        proj, unit = proj_from_epsg(value_offset, printf=printf)
                                        if proj is not None:
                                            printf("Found EPSG from lidar file: " + str(value_offset))
                                            break
                                    except:
                                        pass
                            except:
                                pass

                        # Projection coordinates list
                        if proj is None and parsed_body and len(parsed_body) == 10:
                            # (0.0, 500000.0, 0.0, -75.0, 0.9996, 1.0, 6378137.0, 298.2572221010042, 0.0, 0.017453292519943278)
                            # pyproj.Proj('+proj=tmerc +datum=NAD83 +ellps=GRS80 +a=6378137.0 +f=298.2572221009999 +k=0.9996 +x_0=500000.0 +y_0=0.0 +lon_0=-75.0 +lat_0=0.0 +units=m +axis=enu ', preserve_units=True)
                            try:
                                sys = 'tmerc' # Don't think any other format is used
                                datum = 'NAD83'
                                ellips = 'GRS80' # Assume this for now, can't find any evidence another is used for lidar
                                proj = pyproj.Proj(proj=sys, datum=datum, ellps=ellips, a=parsed_body[6], f=parsed_body[7], k=parsed_body[4], \
                                                   x_0=parsed_body[1], y_0=parsed_body[0], lon_0=parsed_body[3], lat_0=parsed_body[2], units='m', axis='enu')
                                unit = parsed_body[5]
                                printf("Found Projection parameters from lidar file")
                            except:
                                pass

                # Wasn't in the las files, do the difficult search in metadata xmls
                if proj is None:
                    # Find the XML file with the name closest matching to the las/laz
                    highest_match = 0.0
                    xml = None
                    for x in list(Path(d).glob('*.xml')):
                        score = SequenceMatcher(None, str(filename), str(x)).ratio()
                        if score > highest_match:
                            highest_match = score
                            xml = x

                    if xml is None:
                        printf("Could not find metadata for " + filename + ".")
                    else:
                        printf("Using metadata: " + xml.name)
                        tree = ET.parse(xml)
                        root = tree.getroot()

                        # If unit not in CRS, try to find it in a tag
                        if unit == 0.0:
                            unit_name = "Unknown"
                            for un in itertools.chain(root.iter('plandu'), root.iter('altunits')):
                                try:
                                    unit_name = un.text.strip() # Some xmls have padded whitespace
                                except:
                                    pass

                            if unit_name == 'meters':
                                unit = 1.0
                            elif unit_name == 'Foot_US':
                                unit = 1200.0/3937.0
                            elif unit_name == 'foot': # International Foot
                                unit = 0.3048
                            else:
                                return print_failure_message(printf=printf)

                        # Continue to look for Metadata
                        if proj is None:
                            # Try to find a UTM zone.
                            utm_zone = None
                            for uz in root.iter('utmzone'):
                                utm_zone = float(uz.text)

                            if utm_zone is not None:
                                printf("Found UTM Zone from metadata file")
                                proj = pyproj.Proj(proj='utm', datum='WGS84', ellps='WGS84', zone=utm_zone, units='m')

                        # Continue to look for Metadata
                        # This last method is the least reliable because the metadata could be hand generated and inconsistent
                        if proj is None:
                            sys = 'tmerc' # Don't think this newer metadata format uses another system
                            datum = 'NAD83'
                            ellips = 'GRS80' # Assume this for now, can't find any evidence another is used for lidar
                            semiaxis = None
                            for sa in root.iter('semiaxis'):
                                semiaxis = float(sa.text)
                            denflat = None
                            for df in root.iter('denflat'):
                                denflat = float(df.text)
                            sfctrmer = None
                            for sfc in root.iter('sfctrmer'):
                                sfctrmer = float(sfc.text)
                            feast = None
                            for fe in root.iter('feast'):
                                feast = float(fe.text)*unit # Scale into meters
                            fnorth = None
                            for fn in root.iter('fnorth'):
                                fnorth = float(fn.text)*unit # Scale into meters
                            meridian = None
                            for m in root.iter('longcm'):
                                meridian = float(m.text)
                            latprj = None
                            for l in root.iter('latprjo'):
                                latprj = float(l.text)

                            if not None in [semiaxis, denflat, sfctrmer, feast, fnorth, meridian, latprj]:
                                printf("Found Projection Parameters from metadata file")
                                proj = pyproj.Proj(proj=sys, datum=datum, ellps=ellips, a=semiaxis, f=denflat, k=sfctrmer, x_0=feast, y_0=fnorth, lon_0=meridian, lat_0=latprj, units='m', axis='enu')

                # Rarely the files come in with lat and lon coordinates, need to convert these to UTM
                if proj is None:
                    if las.header.max[0] - las.header.min[0] < 2.0 and las.header.max[1] - las.header.min[1] < 2.0:
                        # Such small difference between units, probably in geographic coordinates
                        printf("File is likely in Geographic Coordinates (Lat/Lon Degrees).  You probably want to find alternate files, but we will try to project this for you.")

                        center = ((las.header.max[1] + las.header.min[1])/2.0, (las.header.max[0] + las.header.min[0])/2.0)
                        epsg = convert_latlon_to_utm_espg(center[0], center[1])
                        printf("For center coordinates: " + str(center) + ":")

                        utm_proj, utm_unit = proj_from_epsg(epsg, printf=printf)

                        # Set the pointcloud's projection to the utm if nothing else is there yet
                        if pc.proj is None:
                            pc.proj = utm_proj

                        # Set this units projection to coordinates and don't scale
                        proj = pyproj.Proj(proj='latlong',datum='WGS84')
                        unit = 1.0

                if proj is None:
                    return print_failure_message(printf=printf)

                # If legacy metadata supplied only one linear unit, preserve the
                # historical assumption that Z uses that same unit.
                if z_unit <= 0.0:
                    z_unit = unit

                # Existing force_unit remains a full XYZ override.
                if force_unit is not None:
                    unit = float(force_unit)
                    z_unit = float(force_unit)

                if unit <= 0.0:
                    return print_failure_message(printf=printf)

                if z_unit <= 0.0:
                    z_unit = unit

                printf("Horizontal XY unit conversion to meters: " + str(unit))
                printf("Vertical Z unit conversion to meters: " + str(z_unit))
                printf("Proj4 : " + str(proj))

                scaled_x = las.x*unit
                scaled_y = las.y*unit
                scaled_z = las.z*z_unit

                converted_x = scaled_x
                converted_y = scaled_y
                converted_z = scaled_z

                # Check if coordinate projection needs converted
                if not pc.proj:
                    # First dataset will set the coordinate system
                    pc.proj = proj
                elif str(pc.proj) != str(proj):
                    printf("Warning: Data has different projection, re-projecting coordinates.  This may take some time.")
                    
                    converted_x = []
                    converted_y = []
                    converted_z = []

                    for x, y, z in zip(scaled_x, scaled_y, scaled_z):
                        x2, y2, z2 = pyproj.transform(proj, pc.proj, x, y, z)
                        converted_x.append(x2)
                        converted_y.append(y2)
                        converted_z.append(z2)

                pc.addDataSet(numpy.array(converted_x), numpy.array(converted_y), numpy.array(converted_z), numpy.array(las.intensity), numpy.array(las.classification).astype(int))
        except Exception as e:
            print(e)
            printf("Could not load " + filename + " Please report this issue.")

    if not pc.count:
        printf("No valid lidar files found, no action taken")
        printf("Directory was: " + d)
        return None

    pc.computeOrigin()
    pc.removeBias()
    return pc