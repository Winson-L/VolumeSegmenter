import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from large_volume import crop_bricks, export


class LocalSource:
    def __init__(self,array,chunks):
        self.array=array;self.chunks=chunks;self.shape=array.shape;self.dtype=array.dtype
        self.name='fixture';self.scale=0;self.base='local-test';self.spacing=[2,1,1]
        self.grid=tuple((n+c-1)//c for n,c in zip(self.shape,chunks));self.root={}
    def blocks(self,workers):
        for index in np.ndindex(self.grid):
            origin=tuple(i*c for i,c in zip(index,self.chunks))
            a=self.array[tuple(slice(o,o+c) for o,c in zip(origin,self.chunks))]
            yield origin,a,0,hashlib.sha256(a.tobytes()).hexdigest()


def decode(meta,path):
    dims=meta['dimensions_xyz'][::-1];brick=meta['brick_xyz'][::-1]
    pages=np.fromfile(path/'pages.raw','<u4').reshape(*meta['grid_xyz'][::-1],4)
    raw=np.fromfile(path/'density.raw',meta['dtype']);result=np.zeros(dims,meta['dtype'])
    for cell in np.ndindex(pages.shape[:3]):
        base,origin,shape,_=map(int,pages[cell])
        if not base:continue
        lo=[(origin>>shift)&31 for shift in (10,5,0)]
        size=[(shape>>shift)&63 for shift in (12,6,0)]
        p=[c*b+l for c,b,l in zip(cell,brick,lo)]
        result[tuple(slice(a,a+n) for a,n in zip(p,size))]=raw[base-1:base-1+int(np.prod(size))].reshape(size)
    return result


class LargeVolumeTests(unittest.TestCase):
    def test_rectangular_partial_cells_raw_precision_and_saved_original(self):
        for dtype in [np.uint8,np.uint16]:
            rng=np.random.default_rng(41);a=rng.integers(0,np.iinfo(dtype).max+1,(23,35,39),dtype=dtype)
            cutoff=130 if dtype==np.uint8 else 34000
            a[:,:,:4]=0;a[9:12,15:18,15:18]=np.iinfo(dtype).max
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'export';m=export(LocalSource(a,(20,32,32)),path,cutoff,brick=(10,16,16),save_original=True)
                restored=decode(m,path)
                np.testing.assert_array_equal(restored,np.where(a>cutoff,a,0))
                np.testing.assert_array_equal(np.fromfile(path/'original.raw',dtype).reshape(a.shape),a)
                self.assertEqual(m['selected_voxels'],int((a>cutoff).sum()))
                for axis in range(3):
                    np.testing.assert_array_equal(np.load(path/f'original-mip-{axis}.npy'),a.max(axis=axis))
                    np.testing.assert_array_equal(restored.max(axis=axis),np.load(path/f'threshold-mip-{axis}.npy'))
                self.assertEqual(hashlib.sha256((path/'density.raw').read_bytes()).hexdigest(),m['density_sha256'])

    def test_empty_thin_and_cutoff_boundary(self):
        a=np.zeros((17,19,33),np.uint16);a[0,0,:]=1001;a[-1,-1,-1]=65535;a[8,8,8]=1000
        for cutoff in [1000,65534]:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'out';m=export(LocalSource(a,(16,16,32)),path,cutoff,brick=(8,8,8))
                np.testing.assert_array_equal(decode(m,path),np.where(a>cutoff,a,0))
                self.assertLess(m['density_bytes'],a.nbytes)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'out';m=export(LocalSource(np.zeros_like(a),(16,16,32)),path,1000,brick=(8,8,8))
            self.assertEqual(m['density_bytes'],0);self.assertEqual(m['bricks'],0)
            np.testing.assert_array_equal(decode(m,path),np.zeros_like(a))

    def test_misaligned_source_rejected(self):
        with self.assertRaises(ValueError):list(crop_bricks(np.ones((10,16,16),np.uint8),(9,0,0),(10,16,16),0))

if __name__=='__main__':unittest.main()
