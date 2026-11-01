"""Pixel checks for native same-surface openings, independent of game rendering."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import OSMTGC
from auto_red_mask import apply_auto_red_mask


class Grid:
    def latlonToCV2(self, lat, lon, scale, x_offset=0., y_offset=0.):
        return ((float(lat)+y_offset)/scale, (float(lon)+x_offset)/scale)


def fixture(kind, mode, xml=False):
    root = ET.Element('osm', version='0.6')
    def way(i, lo, hi, tags):
        ns = []
        for k,(x,y) in enumerate([(lo,lo),(hi,lo),(hi,hi),(lo,hi)]):
            n = str(i*10+k); ET.SubElement(root, 'node', id=n, lat=str(y), lon=str(x)); ns.append(n)
        w=ET.SubElement(root,'way',id=str(i))
        for n in ns+[ns[0]]: ET.SubElement(w,'nd',ref=n)
        for k,v in tags.items(): ET.SubElement(w,'tag',k=k,v=v)
    def rel(i,tags,members):
        r=ET.SubElement(root,'relation',id=str(i))
        for t,ref,role in members: ET.SubElement(r,'member',type=t,ref=str(ref),role=role)
        for k,v in dict(type='multipolygon',**tags).items(): ET.SubElement(r,'tag',k=k,v=v)
    parent = {'golf':kind}
    inner = {'natural':'water'} if kind=='water_hazard' else {'golf':'rough'}
    way(1,10,85,{}); way(2,22,75,inner if mode=='direct' else {}); way(3,45,55,{'golf':'bunker'})
    if mode!='direct':
        rel(22,inner,[('way',2,'outer'),('way',3,'inner')])
    member=('relation',22,'inner') if mode=='nested' else ('way',2,'inner')
    rel(10,parent,[('way',1,'outer'),member])
    data = ET.tostring(root,encoding='unicode')
    return data if xml else OSMTGC.parseOSMData(data)


class OpenIslandMask(unittest.TestCase):
    def test_legacy_mask_detection_only_for_affected_map(self):
        from osm_mask_alignment import _has_open_island_geometry, _sha256_file
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'selected.osm'
            path.write_text(fixture('rough','shared',xml=True),encoding='utf-8')
            self.assertTrue(_has_open_island_geometry(str(path),_sha256_file(path)))
            # Same local filename, edited map: no stale result from the cache.
            path.write_text('<osm version="0.6"></osm>',encoding='utf-8')
            self.assertFalse(_has_open_island_geometry(str(path),_sha256_file(path)))

    def test_open_floor_and_independent_bunker_with_red_on_and_off(self):
        terrain=np.full((100,100,3),.42,np.float32); grid=Grid()
        for kind in ('rough','water_hazard'):
            for mode in ('direct','shared','nested'):
                with self.subTest(kind=kind,mode=mode):
                    r=fixture(kind,mode)
                    preview=OSMTGC.addOSMToImage(r,terrain.copy(),grid,1.,printf=lambda _:None)
                    masked=apply_auto_red_mask(r,preview.copy(),grid,1.,buffer_m=0.,printf=lambda _:None)
                    np.testing.assert_allclose(masked[0,0], [1,0,0])
                    for image in [preview, masked]:
                        np.testing.assert_allclose(image[30,30],terrain[30,30])  # no rough, blue or red
                        np.testing.assert_allclose(image[15,15],[0,0,1] if kind=='water_hazard' else [0,.55,.15])
                        np.testing.assert_allclose(image[50,50],[.85,.85,.7])


if __name__ == '__main__':
    unittest.main(verbosity=2)
