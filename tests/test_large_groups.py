import tempfile,unittest
from pathlib import Path
import numpy as np
from test_large_volume import LocalSource
from pipeline.large_volume import export
from pipeline.group_large_volume import group_volume
from pipeline.verify_large_groups import verify_groups

class GroupTests(unittest.TestCase):
    def test_exact_ownership_masks_and_partial_words(self):
        for dtype in [np.uint8,np.uint16]:
            for masked in [False,True]:
                with tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp)/'source';out=Path(tmp)/'groups'
                    a=np.zeros((17,19,35),dtype)
                    a[::2,::2,::3]=90
                    a[5:13,4:15,7:29]=180
                    a[-1,-1,-1]=np.iinfo(dtype).max
                    export(LocalSource(a,(16,16,16)),root,40,brick=(8,8,8),save_original=True)
                    m=group_volume(root,out,[100,200],keep=2,masked=masked)
                    result=verify_groups(out,root)
                    self.assertTrue(result['unique_brick_ownership'])
                    self.assertEqual(sum(g['selected_voxels'] for g in m['groups']),np.count_nonzero(a))
                    self.assertTrue((out/m['original_file']).exists())
                    if masked:self.assertEqual(m['density_bytes'],np.count_nonzero(a)*a.dtype.itemsize)
