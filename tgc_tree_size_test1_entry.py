"""Separate test-build entry point; normal launch runs the main GUI."""
import sys


def verify_frozen_tree_sizes():
    import random
    import math
    import copy
    from unittest.mock import patch
    import tgc_image_terrain as terrain
    import tree_profile_manager as profiles
    trees=[(10.,20.,1.,3.),(20.,20.,2.,4.),(30.,20.,5.,10.),(40.,20.,10.,30.)]
    def scales(groups):
        result={}
        for g in groups:
            for i in g['Value']['items']:
                key=(i['position']['x'],i['position']['z'])
                assert key not in result
                result[key]=tuple(i['scale'][a] for a in 'xyz')
        return result
    modes=(profiles.STANDARD_SCALE_MODE,profiles.HEROIC_SCALE_MODE,profiles.EPIC_SCALE_MODE,profiles.MYTHIC_SCALE_MODE)
    checked=0
    baselines={}
    for mode in modes:
        random.seed(20261020)
        base=scales(terrain.get_trees(12,True,trees,25,tree_scale_mode=mode))
        baselines[mode]=base
        for name,profile in profiles.load_profiles(force=True).items():
            random.seed(20261020)
            result=scales(terrain.get_trees(12,True,trees,25,tree_profile=name,tree_scale_mode=mode))
            expected={} if profile.get('tree_generation')=='none' else base
            if result!=expected:
                raise RuntimeError('Profile/size mismatch: '+name+' / '+mode)
            checked+=1
        for huge in (.001,10000.):
            stats={'p10':huge,'p50':huge*2,'p90':huge*5}
            p={'assets':[{'path':'TEST_TREE','shape':'normal','weight':1,'uniform_scale':stats,'scale':{a:stats for a in 'xyz'}}], 'scale_defaults':{a:stats for a in 'xyz'}}
            before=copy.deepcopy(p)
            with patch.object(profiles,'get_profile',return_value=p), patch.object(profiles,'scale_for_asset',side_effect=AssertionError('Old profile sizing called')):
                got=scales(terrain.get_trees(12,True,trees,25,tree_profile='TEST',tree_scale_mode=mode))
            assert got==base and p==before
        mid=base[(20.,20.)]
        if mode==profiles.HEROIC_SCALE_MODE:
            assert math.isclose(mid[0],.70+1./9.*.95,abs_tol=1e-14)
            assert math.isclose(mid[1],.85+1./27.*.70,abs_tol=1e-14)
    if not checked:
        raise RuntimeError('No bundled profiles found')
    heroic=baselines[profiles.HEROIC_SCALE_MODE]
    for mode,factor in ((profiles.EPIC_SCALE_MODE,1.20),(profiles.MYTHIC_SCALE_MODE,1.80)):
        for pos,vals in baselines[mode].items():
            assert all(math.isclose(a,b*factor,rel_tol=1e-14,abs_tol=1e-14) for a,b in zip(vals,heroic[pos]))
    for mode,expected in zip(modes,((1.,1.,1.),(1.10,1.15,1.10),(1.32,1.38,1.32),(1.98,2.07,1.98))):
        got=terrain._tree_scales_from_lidar([(0.,0.,4.,15.)],mode)[0]
        assert all(math.isclose(a,b,abs_tol=1e-14) for a,b in zip(got,expected))
        assert terrain.get_trees(12,True,[],25,tree_scale_mode=mode)==[]
    print('LIDAR TREE SIZE TEST 1 PASSED: %d shipped profile/mode combinations; extreme scales, actual-value spacing, preset ratios and single-tree defaults verified' % checked)

if '--verify-lidar-trees' in sys.argv:
    verify_frozen_tree_sizes()
else:
    import tgc_gui
