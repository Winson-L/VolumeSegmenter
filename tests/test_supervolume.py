import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from pipeline.supervolume import analyze, region_graph, select_groups, export_bricks, reconstruct_sparse, extract_selected


def analysis_for(volume, labels):
    hist, edges = region_graph(volume, labels)
    return dict(regions=[dict(id=i, histogram=h.tolist()) for i,h in enumerate(hist) if i], edges=edges)


class SupervolumeTests(unittest.TestCase):
    def test_seed_graph_does_not_jump_disconnected_or_drift(self):
        v=np.array([100,110,120,130,140,0,110],dtype=np.uint8).reshape(1,1,7)
        labels=np.arange(1,8,dtype=np.uint32).reshape(v.shape)
        config={'groups':[dict(name='target',mode='seeded',seeds_xyz=[[0,0,0]],intensity_range=[95,125],min_fraction=1,max_boundary_delta=15)]}
        owner,groups=select_groups(v,labels,analysis_for(v,labels),config)
        np.testing.assert_array_equal(owner.ravel(),[1,1,1,0,0,0,0])
        self.assertEqual(groups[0]['selected_region_ids'],[1,2,3])

    def test_histogram_anchor_and_boundary(self):
        v=np.array([100,110,100],dtype=np.uint8).reshape(1,1,3)
        labels=np.array([1,2,3],dtype=np.uint32).reshape(v.shape)
        config={'groups':[dict(mode='seeded',region_ids=[1],intensity_range=[90,120],max_seed_histogram_distance=.1)]}
        owner,_=select_groups(v,labels,analysis_for(v,labels),config)
        np.testing.assert_array_equal(owner.ravel(),[1,0,0])
        del config['groups'][0]['max_seed_histogram_distance'];config['groups'][0]['max_boundary_delta']=5
        owner,_=select_groups(v,labels,analysis_for(v,labels),config)
        np.testing.assert_array_equal(owner.ravel(),[1,0,0])

    def test_overlap_has_unique_ownership_and_explicit_clipping(self):
        v=np.array([80,100,120,150],dtype=np.uint8).reshape(1,1,4);labels=np.ones(v.shape,dtype=np.uint32)
        groups=[dict(mode='all_candidates',intensity_range=[90,130],min_fraction=.2),dict(mode='all_candidates',intensity_range=[100,160],min_fraction=.2)]
        owner,stats=select_groups(v,labels,analysis_for(v,labels),dict(groups=groups))
        np.testing.assert_array_equal(owner.ravel(),[0,1,1,2])
        self.assertEqual(stats[1]['overlap_voxels_assigned_to_earlier_groups'],2)
        groups[0]['clip_to_range']=False
        owner,_=select_groups(v,labels,analysis_for(v,labels),dict(groups=groups))
        np.testing.assert_array_equal(owner,np.ones_like(v))

    def test_invalid_seed_and_missing_seed_rejected(self):
        v=np.full((2,3,4),100,dtype=np.uint8);labels=np.ones(v.shape,dtype=np.uint32);a=analysis_for(v,labels)
        for g in [dict(mode='seeded',intensity_range=[90,120]),dict(mode='seeded',seeds_xyz=[[4,0,0]],intensity_range=[90,120]),dict(mode='seeded',region_ids=[1],intensity_range=[150,200])]:
            with self.assertRaises(ValueError):select_groups(v,labels,a,dict(groups=[g]))

    def test_thin_boundary_and_partial_bricks_exact(self):
        v=np.zeros((19,21,35),dtype=np.uint8);v[0,0,:]=180;v[-1,-1,-1]=220;v[8:17,5:13,16]=90
        owner=np.zeros_like(v);owner[v==180]=1;owner[v==90]=2;owner[v==220]=1
        with tempfile.TemporaryDirectory() as tmp:
            for size in [8,16,32]:
                out=Path(tmp)/str(size);groups=[dict(id=1,name='a'),dict(id=2,name='b')]
                meta=export_bricks(v,owner,groups,out,size)
                restored,ownership=reconstruct_sparse(out)
                np.testing.assert_array_equal(restored,v);np.testing.assert_array_equal(ownership,owner)
                boxes=np.zeros_like(v)
                for b in meta['bricks']:
                    o=b['origin_xyz'][::-1];d=b['dimensions_xyz'][::-1]
                    boxes[tuple(slice(a,a+n) for a,n in zip(o,d))]+=1
                    self.assertLessEqual(max(d),size)
                self.assertLessEqual(boxes.max(),1)
                self.assertLess(meta['density_bytes'],v.nbytes)

    def test_empty_full_and_tree_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            for full in [False,True]:
                v=np.full((17,19,33),100 if full else 0,dtype=np.uint8);owner=(v>0).astype(np.uint8)
                m=export_bricks(v,owner,[dict(id=1,name='all')],Path(tmp)/str(full),8)
                r,o=reconstruct_sparse(Path(tmp)/str(full));np.testing.assert_array_equal(r,v)
                def leaves(node):
                    if node is None:return []
                    return node.get('brick_ids',[])+[i for c in node.get('children',[]) for i in leaves(c)]
                self.assertEqual(sorted(leaves(m['groups'][0]['tree'])),list(range(len(m['bricks']))))
                self.assertEqual(m['density_bytes'],v.nbytes if full else 0)

    def test_slic_constant_empty_and_non_cubic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i, value in enumerate([0, 190]):
                v=np.full((3,5,7),value,dtype=np.uint8);source=root/f'{i}.raw';v.tofile(source)
                a=analyze(source,[7,5,3],root/str(i),region_size=4,spacing=[1,1,2])
                self.assertEqual(sum(r['voxels'] for r in a['regions']),v.size)
                self.assertTrue(all(r['histogram'][value]==r['voxels'] for r in a['regions']))

    def test_slic_export_repeatability_and_cache_binding(self):
        v=np.zeros((13,17,21),dtype=np.uint8);v[1:12,2:10,3:12]=160;v[5:8,9:15,10:20]=100
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'v.raw';v.tofile(source)
            a=analyze(source,list(v.shape[::-1]),root/'a',region_size=4)
            b=analyze(source,list(v.shape[::-1]),root/'b',region_size=4)
            self.assertEqual((root/'a/labels.u32').read_bytes(),(root/'b/labels.u32').read_bytes())
            self.assertEqual(a['regions'],b['regions'])
            config=root/'config.json';config.write_text(json.dumps(dict(groups=[dict(mode='all_candidates',intensity_range=[1,255],min_fraction=0)])))
            extract_selected(source,root/'a',config,root/'out')
            r,_=reconstruct_sparse(root/'out');np.testing.assert_array_equal(r,v)
            v[0,0,0]=255;v.tofile(source)
            with self.assertRaises(ValueError):extract_selected(source,root/'a',config,root/'bad')


if __name__=='__main__':unittest.main()
