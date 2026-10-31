"""Offline native import checks for Beta 8.2 surface parking lots."""
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

import OSMTGC as osm
import auto_red_mask
from osm_water_mulch_lock import DRY_LOCK_KEY, LOCK_KEY


class Grid:
    def ulENU(self): return 0., 100.
    def lrENU(self): return 100., 0.
    def enuToTGC(self, x, y, z): return x, z, y
    def latlonToTGC(self, lat, lon, x_offset=0., y_offset=0.):
        return float(lon) + x_offset, 0., float(lat) + y_offset
    def latlonToCV2(self, lat, lon, scale, x_offset=0., y_offset=0.):
        return (float(lat)+y_offset)/scale, (float(lon)+x_offset)/scale


LOT = {'amenity':'parking', 'parking':'surface'}
OUTER = [(10,10), (75,10), (75,70), (10,70), (10,10)]
INNER = [(34,30), (48,30), (48,42), (34,42), (34,30)]
AISLE = [(10,17),(75,17)]


def fixture(ways, relations=(), node_tags=None):
    root = ET.Element('osm', version='0.6')
    coords = {}
    def tag(obj, tags):
        for k,v in tags.items(): ET.SubElement(obj, 'tag', k=k, v=v)
    def node(pt):
        if pt not in coords:
            n = len(coords)+1
            coords[pt] = n
            item = ET.SubElement(root,'node',id=str(n),lon=str(pt[0]),lat=str(pt[1]))
            if node_tags: tag(item,node_tags)
        return coords[pt]
    for wid, pts, tags in ways:
        ids = [node(pt) for pt in pts]
        w = ET.SubElement(root,'way',id=str(wid))
        for n in ids: ET.SubElement(w,'nd',ref=str(n))
        tag(w,tags)
    for rid, members, tags in relations:
        rel = ET.SubElement(root,'relation',id=str(rid))
        for ref,role in members: ET.SubElement(rel,'member',type='way',ref=str(ref),role=role)
        tag(rel,{'type':'multipolygon',**tags})
    return osm.parseOSMData(ET.tostring(root, encoding='unicode'))


def native(data, options=None, config=None):
    c = dict(surfaceSplines2=[], holes3=[], surfaces2=[{}, {}, {}])
    log = []
    # Other unrelated features should not obscure what parking/road selected.
    opts = {'water':False, 'building':False, 'optimize_osm_spline_points':False, **(options or {})}
    osm.addOSMToTGC(c, Grid(), data, options_dict=opts, spline_configuration_json=config,
                    printf=log.append, course_version=25, resolve_missing_nodes=False)
    return c, log


class Parking(unittest.TestCase):
    def test_alignment_outline_is_an_area(self):
        from osm_alignment_viewer import _feature_style, FEATURE_COLORS
        from tgc_local_alignment_topology import surface_kind, LINE_KINDS
        self.assertEqual(_feature_style(LOT), ('parking_lot', FEATURE_COLORS['road']))
        self.assertEqual(surface_kind(LOT), 'parking_lot')
        self.assertNotIn('parking_lot', LINE_KINDS)
        self.assertNotEqual(surface_kind(dict(LOT, parking='underground')), 'parking_lot')

    @unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Tk display not available')
    def test_real_checkbox_defaults_and_independence(self):
        import tkinter as tk
        gui = Path(__file__).with_name('tgc_gui.py').read_text(encoding='utf-8')
        start = gui.index('options_entries_dict["road"] = tk.BooleanVar')
        end = gui.index('options_entries_dict["path"] = tk.BooleanVar', start)
        root = tk.Tk()
        root.withdraw()
        try:
            ns = dict(tk=tk, Checkbutton=tk.Checkbutton, osmSubFrame=tk.Frame(root),
                      options_entries_dict={}, check_fg='black', check_bg='white')
            exec(gui[start:end], ns)
            options = ns['options_entries_dict']
            self.assertFalse(options['parking_lot'].get())
            self.assertFalse(options['road'].get())
            self.assertEqual(ns['parkingLotCheck'].cget('text'), 'Import Surface Parking Lots (Road Surface)')
            ns['parkingLotCheck'].invoke()
            self.assertTrue(options['parking_lot'].get())
            self.assertFalse(options['road'].get())
            ns['roadCheck'].invoke()
            ns['parkingLotCheck'].invoke()
            self.assertFalse(options['parking_lot'].get())
            self.assertTrue(options['road'].get())
        finally:
            root.destroy()

    def test_independent_lot_and_road_options(self):
        data = fixture([(100,OUTER,LOT),(101,AISLE,{'highway':'service','service':'parking_aisle'})])
        for flags, closed in [({},[]),({'parking_lot':True},[True]),
                              ({'road':True},[False]),({'road':True,'parking_lot':True},[True,False])]:
            with self.subTest(flags=flags):
                c,_ = native(data,flags)
                splines = c['surfaceSplines2']
                self.assertEqual([s['isFilled'] for s in splines],closed)
                for s in splines: self.assertEqual(s['surface'],8)
                self.assertEqual(osm.last_imported_road_spline_indices,set(range(len(splines))))
                self.assertNotIn(LOCK_KEY,c)
                self.assertNotIn(DRY_LOCK_KEY,c)

    def test_only_share_road_material(self):
        data = fixture([(100,OUTER,{'amenity':'parking'}),(101,AISLE,{'highway':'service'})])
        cfg = {'road':{'primarySurface':7,'pathWidth':13.,'handleLength':6.,'secondaryWidth':3.}}
        c,_ = native(data,{'parking_lot':True,'road':True},cfg)
        lot,road = c['surfaceSplines2']
        self.assertEqual((lot['surface'],road['surface']),(7,7))
        self.assertEqual((lot['state'],lot['isClosed'],lot['width'],lot['secondaryWidth']),(3,True,.01,0.))
        self.assertEqual((road['width'],road['secondaryWidth']),(13.,3.))
        self.assertEqual([(w['waypoint']['x'],w['waypoint']['z']) for w in lot['waypoints']],OUTER[:-1])
        for wp in lot['waypoints']: self.assertEqual(wp['pointOne'],wp['pointTwo'])

    def test_not_stalls_garages_roofs_or_aisles(self):
        for tags in ({'amenity':'parking_space'},{'amenity':'parking_entrance'},{'surface':'asphalt'},
                     {'parking':'surface'},dict(LOT,area='no'),dict(LOT,building='yes'),
                     dict(LOT,location='underground'),dict(LOT,level='-1'),dict(LOT,indoor='yes'),
                     dict(LOT,covered='yes'),dict(LOT,parking='multi-storey'),dict(LOT,parking='rooftop'),
                     dict(LOT,parking='street_side'),dict(LOT,parking='underground')):
            with self.subTest(tags=tags):
                c,_ = native(fixture([(100,OUTER,tags)],node_tags=LOT),{'parking_lot':True})
                self.assertFalse(c['surfaceSplines2'])
        self.assertFalse(native(fixture([(100,OUTER,{'highway':'service','service':'parking_aisle'})]),
                                {'parking_lot':True})[0]['surfaceSplines2'])

    def test_complete_multipolygon_and_independent_inner_feature(self):
        data = fixture([(100,OUTER[:3],{}),(101,list(reversed(OUTER[2:])),{}),(102,INNER,{'golf':'green'})],
                       [(200,[(101,'outer'),(102,'inner'),(100,'outer')],LOT)])
        c,_ = native(data,{'parking_lot':True})
        lots = [s for s in c['surfaceSplines2'] if s['surface']==8]
        self.assertTrue(lots)
        parts = [Polygon([(w['waypoint']['x'],w['waypoint']['z']) for w in s['waypoints']]) for s in lots]
        self.assertTrue(all(g.is_valid for g in parts))
        intended = Polygon(OUTER,[INNER])
        self.assertAlmostEqual(unary_union(parts).symmetric_difference(intended).area,0.)
        self.assertAlmostEqual(sum(g.area for g in parts),intended.area)
        self.assertEqual([s['surface'] for s in c['surfaceSplines2']].count(1),1)

    def test_relation_owns_tagged_outer_even_if_incomplete(self):
        offered = [(100,OUTER,{'amenity':'parking'})]
        for members,parent,count in [([(100,'outer')],LOT,1),
                                     ([(100,'outer'),(999,'inner')],LOT,0),
                                     ([(100,'outer')],dict(LOT,parking='underground'),0)]:
            with self.subTest(members=members,parent=parent):
                c,log = native(fixture(offered,[(200,members,parent)]),{'parking_lot':True})
                self.assertEqual(len(c['surfaceSplines2']),count)
                if members[-1][0]==999: self.assertTrue(any('skipped' in s for s in log))
        structured = [(100,OUTER,{'building':'parking'})]
        c,_ = native(fixture(structured,[(200,[(100,'outer')],LOT)]),{'parking_lot':True})
        self.assertFalse(c['surfaceSplines2'])

    def test_do_not_close_open_invalid_or_out_of_bounds_lots(self):
        for ring in [OUTER[:-1], [(10,10),(30,30),(30,10),(10,30),(10,10)],
                     [(90,90),(110,90),(110,99),(90,90)]]:
            c,_ = native(fixture([(100,ring,LOT)]),{'parking_lot':True})
            self.assertFalse(c['surfaceSplines2'])

    def test_no_parking_mask_footprint_or_buffer(self):
        def masks(with_lots):
            ways = [(10,INNER,{'golf':'green'}),(11,AISLE,{'highway':'service'}),
                    (12,OUTER, LOT if with_lots else {})]
            rels = [(20,[(12,'outer'),(10,'inner')],LOT if with_lots else {})]
            data = fixture(ways,rels)
            im = osm.addOSMToImage(data,np.full((100,100,3),.5,np.float32),Grid(),1.,printf=lambda *_:None)
            red = auto_red_mask.apply_auto_red_mask(data,im.copy(),Grid(),1.,buffer_m=3.,
                                                    include_vehicle_roads=True,printf=lambda *_:None)
            return im,red
        basic,lots = masks(False),masks(True)
        for a,b in zip(basic,lots): np.testing.assert_array_equal(a,b)
        self.assertFalse(np.array_equal(basic[0],basic[1]))


if __name__ == '__main__': unittest.main(verbosity=2)
