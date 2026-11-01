"""Native rough and water openings: coverage, exact ownership and safe fallback."""
import unittest

from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from VERIFY_BETA8_2_PARKING import fixture, native
import OSMTGC as osm
from osm_open_surface_islands import plan_open_surfaces, lollipop_paths
from osm_water_mulch_lock import LOCK_KEY


def rect(x0,y0,x1,y1):
    return [(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]


def poly(s):
    return Polygon([(w['waypoint']['x'],w['waypoint']['z']) for w in s['waypoints']])


class IslandTests(unittest.TestCase):
    def assert_open(self, spline, outer, holes):
        intended = Polygon(outer, holes)
        result = poly(spline)
        self.assertTrue(spline["isClosed"] and spline["isFilled"] and result.is_valid)
        self.assertEqual(spline['secondaryWidth'], 0.)
        self.assertEqual(spline['width'], .01)
        for w in spline['waypoints']:
            self.assertEqual(w['waypoint'],w['pointOne']);self.assertEqual(w['waypoint'],w['pointTwo'])
        self.assertTrue(result.difference(intended).area < 1e-6)
        removed = intended.difference(result).area
        self.assertGreater(removed,0)
        self.assertLess(removed,intended.area*.02)
        for inner in holes:
            self.assertLess(result.intersection(Polygon(inner)).area,1e-6)
        return result

    def test_direct_rough_and_rough_owned_child_holes(self):
        outer,a,b,trap=rect(3,3,95,90),rect(15,30,29,48),rect(66,12,83,34),rect(70,16,76,22)
        rough={'golf':'rough'}
        data=fixture([(1,outer,rough),(2,a,rough),(3,b,{}),(4,trap,{'golf':'bunker'})],
                     [(20,[(3,'outer'),(4,'inner')],rough),(10,[(1,'outer'),(2,'inner'),(3,'inner')],rough)])
        own=plan_open_surfaces(data)
        self.assertEqual(own.open_inner[10],{2,3});self.assertIn(20,own.drop_relations)
        c,_=native(data,{'rough':True})
        self.assertEqual(len(c['surfaceSplines2']),2)
        rough_spline=next(s for s in c['surfaceSplines2'] if s['surface']==osm.tgc_definitions.featuresToSurfaces['rough'])
        self.assert_open(rough_spline,outer,[a,b])
        self.assertEqual(sum(s['surface']==osm.tgc_definitions.featuresToSurfaces['bunker'] for s in c['surfaceSplines2']),1)
        self.assertEqual(len(native(data,{'rough':False})[0]['surfaceSplines2']),1)

    def test_water_aliases_and_nested_ownership(self):
        outer,a,b=rect(5,5,95,95),rect(30,12,42,24),rect(58,71,75,86)
        for wet in ({'golf':'water_hazard'},{'golf':'lateral_water_hazard'},{'natural':'water'}):
            with self.subTest(wet=wet):
                data=fixture([(1,outer,wet),(2,a,{'natural':'water'}),(3,b,{})],
                             [(10,[(1,'outer'),(2,'inner'),(3,'inner')],wet),
                              (20,[(3,'outer')],{'golf':'water_hazard'})])
                c,_=native(data,{'water':True})
                self.assertEqual(len(c['surfaceSplines2']),1)
                s=c['surfaceSplines2'][0]
                self.assert_open(s,outer,[a,b]);self.assertEqual(s['surface'],10)
                self.assertEqual(osm.last_imported_water_splines,[s]);self.assertIn(LOCK_KEY,c)
                self.assertEqual(native(data,{'water':False})[0]['surfaceSplines2'],[])

    def test_partial_child_does_not_hide_its_other_outer(self):
        rough={'golf':'rough'}
        outer,inner,other=rect(2,2,60,65),rect(25,25,41,43),rect(75,75,90,89)
        r=fixture([(1,outer,{}),(2,inner,{}),(3,other,rough)],
                  [(10,[(1,'outer'),(2,'inner')],rough),(20,[(2,'outer'),(3,'outer')],rough)])
        c,_=native(r);ss=c['surfaceSplines2'];self.assertEqual(len(ss),2)
        self.assert_open(ss[0],outer,[inner]);self.assertTrue(poly(ss[1]).covers(Point(82,82)))

    def test_complete_fragmented_boundaries_and_no_spatial_guess(self):
        rough={'golf':'rough'}
        big,inner=rect(2,2,95,95),rect(11,16,30,37)
        r=fixture([(1,big[:3],{}),(2,big[2:][::-1],{}),(3,inner[:3],rough),
                   (4,inner[2:][::-1],{}),(5,rect(55,65,74,82),rough)],
                  [(10,[(1,''),(2,'outer'),(3,'inner'),(4,'inner')],rough)])
        c,_=native(r);ss=c['surfaceSplines2'];self.assertEqual(len(ss),2)
        self.assert_open(ss[-1],big,[inner])
        self.assertTrue(poly(ss[-1]).covers(Point(60,73)))

    def test_invalid_or_incomplete_selected_hole_is_never_fill_closed(self):
        rough={'golf':'rough'}
        outer=rect(1,1,89,89)
        for hole in (rect(20,20,50,50)[:-1], rect(75,30,92,51),
                     [(10,10),(30,30),(30,10),(10,30),(10,10)]):
            c,log=native(fixture([(1,outer,rough),(2,hole,rough)],
                                  [(10,[(1,'outer'),(2,'inner')],rough)]))
            self.assertEqual(c['surfaceSplines2'],[])
            self.assertTrue(any('skipped' in line for line in log))

    def test_unrelated_bunker_inner_does_not_open_plain_rough(self):
        c,_=native(fixture([(1,rect(2,2,90,90),{}),(2,rect(25,25,42,42),{'golf':'bunker'})],
                            [(10,[(1,'outer'),(2,'inner')],{'golf':'rough'})]))
        self.assertEqual(len(c['surfaceSplines2']),2)
        rough=next(s for s in c['surfaceSplines2'] if s['surface']==osm.tgc_definitions.featuresToSurfaces['rough'])
        self.assertTrue(poly(rough).covers(Point(32,32)))

    def test_concave_shell_with_neighboring_holes(self):
        shell=[(0,0),(90,0),(90,90),(60,90),(60,40),(30,40),(30,90),(0,90)]
        holes=[rect(39,9,51,21),rect(40,24,50,34),rect(69,50,82,63)]
        path,=lollipop_paths([shell],holes);p=Polygon(path)
        self.assertTrue(p.is_valid);self.assertFalse(p.interiors)
        for h in holes:self.assertLess(p.intersection(Polygon(h)).area,1e-6)
        self.assertAlmostEqual(p.difference(Polygon(shell)).area,0.)

if __name__=='__main__': unittest.main(verbosity=2)
