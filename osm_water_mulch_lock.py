"""Pin only imported OSM water to native 2K25 mulch, after theme application.

Native 2K25 water-placeholder/Mulch spline category is 10, NOT legacy surface2
(alias 8). Its material entry is surfaces2[2]. Roads use category 8 and cart
paths use 7. The ordered material list is not indexed by spline category ID.
"""
import copy
import json

LOCK_KEY = '_tgcOsmWaterMulchV1'
MULCH_SURFACE = 10
MULCH_MATERIAL_SLOT = 2
MULCH_MATERIAL = 'Mulch05'


def _pin_slot(obj):
    entries = obj.get('surfaces2')
    if not isinstance(entries, list):
        raise ValueError('Cannot lock OSM water mulch: course has no surfaces2 material table')
    if len(entries) <= MULCH_MATERIAL_SLOT:
        raise ValueError('Cannot lock OSM water mulch: material slot 2 is missing')
    slot = entries[MULCH_MATERIAL_SLOT]
    if slot is None:
        slot = {'blend': .6, 'maskWater': True}
    if not isinstance(slot, dict):
        raise ValueError('Cannot lock OSM water mulch: material slot 2 is invalid')
    # Do not replace the palette or adjust other settings, even within this slot.
    updated = dict(slot)
    updated['name'] = MULCH_MATERIAL
    entries[MULCH_MATERIAL_SLOT] = updated


def mark_import(course, imported_splines, course_version, printf=print):
    if course_version != 25:
        return
    identities = {id(s) for s in imported_splines}
    count = sum(id(s) in identities for s in course.get('surfaceSplines2', ()))
    if not count:
        course.pop(LOCK_KEY, None)
        return
    course[LOCK_KEY] = {'surface': MULCH_SURFACE, 'materialSlot': MULCH_MATERIAL_SLOT,
                        'material': MULCH_MATERIAL, 'importedCount': count}
    enforce(course)
    printf('OSM water material LOCK: %d spline(s), native category 10, surfaces2[2]=Mulch05; applied again at final export.' % count)


def enforce(course, metadata=None):
    lock = course.get(LOCK_KEY)
    if not isinstance(lock, dict) or lock.get('material') != MULCH_MATERIAL:
        return False
    if not any(s.get('surface') == MULCH_SURFACE for s in course.get('surfaceSplines2', ())):
        return False
    _pin_slot(course)
    if metadata is not None:
        if not isinstance(metadata.get('surfaces2'), list):
            # Metadata without a palette is uncommon. Mirror the existing
            # description palette rather than inventing new material entries.
            metadata['surfaces2'] = copy.deepcopy(course['surfaces2'])
        _pin_slot(metadata)
    return True


def finalize_serialized(desc_text, metadata_text, course_version):
    """Last export gate: profile changes cannot silently replace water mulch.

    Untagged courses are returned byte-for-byte unchanged. The guard is scoped
    to water imported by this fix; arbitrary existing category-10 shapes are
    not reclassified as water.
    """
    if course_version != 25 or ('"' + LOCK_KEY + '"') not in desc_text:
        return desc_text, metadata_text
    course = json.loads(desc_text)
    meta = json.loads(metadata_text)
    if not enforce(course, meta):
        return desc_text, metadata_text
    return (json.dumps(course, ensure_ascii=True, separators=(',', ':')),
            json.dumps(meta, ensure_ascii=True, separators=(',', ':')))
