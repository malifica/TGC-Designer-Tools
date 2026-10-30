"""Validate IGN numeric WMS rasters without accepting an arbitrary CRS mismatch.

ROK4's documented GeoTIFF encoder can write an EPSG:2154 citation and the
Lambert-93 parameters but user-defined/unnamed geodetic keys. This handler only
reconstructs that missing identification for an exact, allowlisted IGN WMS
request with matching bounds, dimensions, units, projection and numeric data.
The downloaded source is never changed; the crop records the original WKT.
"""
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import datetime
import json
import math
import struct

VERSION = 'TGC_BETA7_IGN_LAMBERT93_CONTRACT_V1'
LAYERS = {
    'IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93': 0.5,
    'ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES': 5.0,
}


def _error(message):
    # Imported only during acquisition, avoiding a module-initialisation cycle.
    from uk_lidar_downloader import AcquisitionError
    raise AcquisitionError(message)


def _geotiff_keys(path):
    """Read bounded GeoTIFF keys from the first Classic/BigTIFF IFD, stdlib only."""
    with Path(path).open('rb') as f:
        size = f.seek(0, 2)
        def read_at(offset, length):
            if not (0 <= offset <= size and 0 <= length <= 1024*1024 and offset+length <= size):
                _error('IGN GeoTIFF metadata has invalid offsets or excessive lengths.')
            f.seek(offset)
            value = f.read(length)
            if len(value) != length:
                _error('IGN GeoTIFF metadata is truncated.')
            return value
        header = read_at(0, min(16, size))
        if header[:2] not in (b'II', b'MM') or len(header) < 8:
            _error('IGN response is not a TIFF file.')
        endian = '<' if header[:2] == b'II' else '>'
        version = struct.unpack(endian+'H', header[2:4])[0]
        if version == 42:
            offset = struct.unpack(endian+'I', header[4:8])[0]
            count = struct.unpack(endian+'H', read_at(offset, 2))[0]
            start, entry_size, inline = offset+2, 12, 4
            fmt, pointer_fmt = 'HHI4s', 'I'
        elif version == 43 and len(header) == 16 and header[4:8] == struct.pack(endian+'HH', 8, 0):
            offset = struct.unpack(endian+'Q', header[8:16])[0]
            count = struct.unpack(endian+'Q', read_at(offset, 8))[0]
            start, entry_size, inline = offset+8, 20, 8
            fmt, pointer_fmt = 'HHQ8s', 'Q'
        else:
            _error('Unsupported TIFF header for IGN metadata validation.')
        if count > 4096:
            _error('Too many TIFF directory entries.')
        arrays = {}
        for i in range(count):
            tag, typ, n, value = struct.unpack(endian+fmt, read_at(start+i*entry_size, entry_size))
            if tag not in (34735, 34736, 34737):
                continue
            if tag in arrays or typ != {34735:3, 34736:12, 34737:2}[tag] or n > 65536:
                _error('Invalid or duplicate IGN GeoTIFF coordinate tags.')
            length = n*{3:2, 12:8, 2:1}[typ]
            data = value[:length] if length <= inline else read_at(struct.unpack(endian+pointer_fmt, value)[0], length)
            arrays[tag] = (data.decode('ascii', errors='strict') if typ == 2
                           else struct.unpack(endian+str(n)+('H' if typ == 3 else 'd'), data))
        directory = arrays.get(34735, ())
        # GeoKeyDirectory may also store SHORT parameter values after its entries.
        # Parse the declared entries, not every trailing parameter as a new key.
        if (len(directory) < 4 or directory[0] != 1 or directory[3] < 1
                or 4+4*directory[3] > len(directory)):
            _error('Missing or invalid GeoTIFF coordinate-key directory.')
        result = {}
        for i in range(4, 4+4*directory[3], 4):
            key, location, n, offset = directory[i:i+4]
            if key in result:
                _error('Duplicate GeoTIFF coordinate key.')
            if location == 0 and n == 1:
                result[key] = offset
            elif location in arrays:
                arr = arrays[location]
                if offset+n > len(arr):
                    _error('Invalid GeoTIFF coordinate-key range.')
                val = arr[offset:offset+n]
                result[key] = val.rstrip('\0|') if isinstance(val, str) else val[0] if n == 1 else list(val)
            else:
                _error('Unsupported GeoTIFF coordinate-key storage.')
        return result


def _close(a, b, tolerance):
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b)) <= tolerance


def _ign_contract(src, metadata):
    """Reconcile request and response grid. Return None for non-IGN acquisitions."""
    url = metadata.get('ign_wms_request_url')
    if not url:
        return None
    parsed = urlparse(str(url))
    if (parsed.scheme != 'https' or parsed.hostname != 'data.geopf.fr'
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ('/wms-r', '/wms-r/wms') or parsed.fragment):
        _error('IGN CRS compatibility is restricted to the official IGN WMS endpoint.')
    raw = parse_qs(parsed.query, keep_blank_values=True)
    query = {}
    for key, values in raw.items():
        k = key.upper()
        if len(values) != 1 or k in query:
            _error('Ambiguous IGN request parameters.')
        query[k] = values[0]
    checks = {'SERVICE':'WMS', 'VERSION':'1.3.0', 'REQUEST':'GetMap',
              'FORMAT':'image/geotiff', 'CRS':'EPSG:2154', 'STYLES':''}
    if any(query.get(k) != v for k, v in checks.items()) or query.get('LAYERS') not in LAYERS:
        _error('IGN raster request does not match a supported numeric Lambert-93 terrain product.')
    try:
        bounds = tuple(float(v) for v in query['BBOX'].split(','))
        width, height = int(query['WIDTH']), int(query['HEIGHT'])
        source_epsg = int(metadata.get('source_epsg', 0))
    except (KeyError, ValueError, TypeError):
        _error('IGN request grid is missing or malformed.')
    if (len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
            or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]
            or not (0 < width <= 5010 and 0 < height <= 5010) or source_epsg != 2154):
        _error('Invalid IGN Lambert-93 request grid.')
    native = LAYERS[query['LAYERS']]
    expected = metadata.get('requested_native_bounds', ())
    if len(expected) != 4 or any(not _close(a,b,1e-5) for a,b in zip(bounds,expected)):
        _error('IGN request extent and acquisition metadata disagree.')
    if src.width != width or src.height != height:
        _error('IGN response dimensions differ from WIDTH/HEIGHT in the request.')
    if src.count != 1 or src.dtypes[0] not in ('float32', 'float64'):
        _error('IGN response must contain one raw floating-point elevation band.')
    t = src.transform
    if not (t.a > 0 and t.e < 0 and t.b == 0 and t.d == 0):
        _error('IGN raster orientation is not a north-up native grid.')
    if (not _close((bounds[2]-bounds[0])/width,native,1e-6)
            or not _close((bounds[3]-bounds[1])/height,native,1e-6)
            or not _close(t.a,native,1e-6) or not _close(-t.e,native,1e-6)):
        _error('IGN source spacing differs from its selected native product; no coarse substitution is accepted.')
    if any(not _close(a,b,1e-4) for a,b in zip(src.bounds,bounds)):
        _error('IGN response extent differs from the native BBOX (possible axis-order or origin error).')
    return {'layer':query['LAYERS'], 'native_spacing_m':native,
            'requested_bounds':list(bounds), 'width':width, 'height':height,
            'request_url':url}


def _documented_lambert93(keys):
    """Accept only the documented custom-key signature, never a conflicting CRS."""
    required = {1024:1, 1025:1, 2048:32767, 2050:32767, 2051:32767,
                2052:9001, 2054:9102, 2056:32767, 3072:32767,
                3074:32767, 3075:8, 3076:9001}
    if any(keys.get(k) != v for k,v in required.items()):
        return False
    if str(keys.get(1026, '')).strip().upper() != 'EPSG:2154':
        return False
    params = {3078:49.0, 3079:44.0, 3084:3.0, 3085:46.5,
              3086:700000.0, 3087:6600000.0}
    for key,value in params.items():
        if key not in keys or not _close(keys[key],value,1e-8 if key < 3086 else 1e-4):
            return False
    # Missing ellipsoid keys are the documented writer omission. If supplied,
    # they MUST describe GRS80, not a different explicitly specified ellipsoid.
    optional = {2057:6378137.0, 2058:6356752.314140356, 2059:298.257222101, 2061:0.0}
    for key,value in optional.items():
        if key in keys and not _close(keys[key],value,1e-5 if key in (2057,2058) else 1e-10):
            return False
    if 2062 in keys:
        values = keys[2062] if isinstance(keys[2062], list) else [keys[2062]]
        if len(values) not in (3,7) or any(not _close(v,0.,1e-12) for v in values):
            return False
    permitted = set(required)|set(params)|set(optional)|{1026,2062}
    # Extra geodetic/projection keys require review rather than being ignored.
    if set(keys)-permitted:
        return False
    return True


def _diagnostic(src, metadata, reason, printf):
    """Persist a small report outside disposable acquisition staging, never a TIFF edit."""
    record = {'version':VERSION, 'reason':str(reason), 'source':str(src.name),
              'expected_epsg':metadata.get('source_epsg'), 'actual_crs_wkt':src.crs.to_wkt() if src.crs else None,
              'bounds':list(src.bounds), 'transform':list(src.transform),
              'width':src.width, 'height':src.height, 'dtypes':list(src.dtypes),
              'request':metadata}
    try:
        record['geotiff_keys'] = _geotiff_keys(src.name)
    except Exception as exc:
        record['geotiff_key_note'] = str(exc)
    try:
        source = Path(src.name).resolve()
        stage = next((p for p in source.parents if p.name.startswith('.partial_')), None)
        folder = (stage.parent if stage else source.parent)/'Diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder/('IGN_CRS_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        target.write_text(json.dumps(record,indent=2),encoding='utf-8')
        printf('IGN CRS details saved: '+str(target))
    except Exception as exc:
        printf('NOTICE: could not save IGN CRS details: '+str(exc))


def resolve_raster_crs(src, metadata, printf=print):
    """Return (effective Rasterio CRS, audit record). Never change the open source."""
    import rasterio
    import pyproj
    metadata = metadata or {}
    expected_epsg = metadata.get('source_epsg')
    if not expected_epsg:
        return src.crs, {}
    expected = rasterio.crs.CRS.from_epsg(int(expected_epsg))
    try:
        contract = _ign_contract(src, metadata)
        if src.crs == expected:
            return src.crs, {}
        if contract is not None:
            # Compare horizontal CRS identity while allowing a compound vertical
            # description or different axis presentation. Preserve the source WKT.
            actual_h = pyproj.CRS.from_wkt(src.crs.to_wkt()).to_2d()
            expected_h = pyproj.CRS.from_wkt(expected.to_wkt()).to_2d()
            if actual_h.equals(expected_h, ignore_axis_order=True):
                printf('IGN terrain CRS: equivalent horizontal Lambert-93 metadata accepted; no coordinate shift.')
                return src.crs, {'crs_validation':'equivalent horizontal CRS', 'original_crs_wkt':src.crs.to_wkt()}
            raw_note = None
            try:
                keys = _geotiff_keys(src.name)
                verified = _documented_lambert93(keys)
            except Exception as key_error:
                # GDAL has already opened/georeferenced the raster. Its parsed
                # signature plus the exact public-service request/grid contract
                # may establish missing metadata when our raw-key reader cannot.
                # This never converts a conflicting, successfully parsed key set.
                raw_note = str(key_error)
                keys = {}
                verified = _parsed_lambert93(src.crs)
            if verified:
                printf('IGN terrain CRS: custom Lambert-93 GeoTIFF verified against EPSG:2154 request, projection parameters, dimensions and extent.')
                printf('Restoring missing CRS identification in the crop only. Source pixels, grid coordinates and elevations are unchanged.')
                return expected, {'crs_validation':VERSION, 'original_crs_wkt':src.crs.to_wkt(),
                                  'original_geotiff_keys':keys, 'raw_geokey_note':raw_note,
                                  'parsed_crs_contract_checked':raw_note is not None,
                                  'effective_source_crs':'EPSG:2154',
                                  'request_contract':contract, 'metadata_repaired':True,
                                  'vertical_datum_conversion':False}
        actual = src.crs.to_string() if src.crs else 'missing'
        _error('Downloaded coverage CRS differs from the requested native CRS. Requested EPSG:%s; received %s. No unverified CRS override applied.' % (expected_epsg,actual))
    except Exception as exc:
        if metadata.get('ign_wms_request_url'):
            _diagnostic(src,metadata,exc,printf)
        from uk_lidar_downloader import AcquisitionError
        if isinstance(exc,AcquisitionError):
            raise
        raise AcquisitionError('IGN CRS validation failed: '+str(exc)) from exc


def _parsed_lambert93(crs):
    """Recognize the user's GDAL-parsed incomplete IGN header, not arbitrary CRS."""
    import pyproj
    if crs is None:
        return False
    try:
        c = pyproj.CRS.from_wkt(crs.to_wkt())
        if not c.is_projected or c.is_bound or c.is_compound or c.name.upper() != 'EPSG:2154':
            return False
        if len(c.axis_info) != 2 or [a.direction for a in c.axis_info] != ['east', 'north']:
            return False
        if any(not _close(a.unit_conversion_factor, 1., 1e-12) for a in c.axis_info):
            return False
        if c.datum.name.lower() not in ('unnamed', 'unknown', 'unknown based on wgs 84 ellipsoid'):
            return False
        # This is the precise missing-ellipsoid fallback reported by GDAL in the
        # uploaded diagnostic. Explicit alternate datums/ellipsoids are NOT allowed.
        if c.ellipsoid.name.lower() != 'unretrievable - using wgs84':
            return False
        if not _close(c.ellipsoid.semi_major_metre, 6378137., 1e-6):
            return False
        if not _close(c.ellipsoid.inverse_flattening, 298.257223563, 1e-10):
            return False
        if not _close(c.prime_meridian.longitude, 0., 1e-12):
            return False
        op = c.coordinate_operation
        if op is None or str(op.method_code) != '9802':
            return False
        expected = {'8821':46.5, '8822':3., '8823':49., '8824':44.,
                    '8826':700000., '8827':6600000.}
        params = {str(p.code):p for p in op.params}
        if set(params) != set(expected):
            return False
        for key,value in expected.items():
            param = params[key]
            tol = 1e-4 if key in ('8826','8827') else 1e-8
            if not _close(param.value, value, tol):
                return False
            factor = 1. if key in ('8826','8827') else math.pi/180.
            if not _close(param.unit_conversion_factor, factor, 1e-12):
                return False
        return True
    except Exception:
        return False
