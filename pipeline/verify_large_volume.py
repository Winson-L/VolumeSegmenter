"""Independent bounded-volume verification of schema 4, including three exact MIPs."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024*1024):h.update(b)
    return h.hexdigest()


def verify(path):
    path=Path(path);m=json.loads((path/'metadata.json').read_text());dtype=np.dtype(m['dtype'])
    for key in ['density','pages']:
        if file_hash(path/m[key+'_file'])!=m[key+'_sha256']:raise AssertionError(key+' hash mismatch')
    dims=m['dimensions_xyz'][::-1];brick=m['brick_xyz'][::-1]
    pages=np.fromfile(path/'pages.raw','<u4').reshape(*m['grid_xyz'][::-1],4)
    result_mips=[np.zeros(tuple(n for j,n in enumerate(dims) if j!=axis),dtype) for axis in range(3)]
    hist=np.zeros(len(m['histogram']),np.int64);voxels=0;records=0;intervals=[]
    original=np.memmap(path/m['original_file'],dtype=dtype,mode='r',shape=tuple(dims)) if m.get('original_file') else None
    with (path/'density.raw').open('rb') as f:
        for cell in np.argwhere(pages[...,0]):
            base,origin,shape,_=map(int,pages[tuple(cell)])
            lo=[(origin>>shift)&31 for shift in (10,5,0)];size=[(shape>>shift)&63 for shift in (12,6,0)]
            p=[int(c)*b+l for c,b,l in zip(cell,brick,lo)];n=int(np.prod(size));offset=(base-1)*dtype.itemsize
            assert all(0<s and l+s<=b and a+s<=d for l,s,b,a,d in zip(lo,size,brick,p,dims))
            f.seek(offset);a=np.frombuffer(f.read(n*dtype.itemsize),dtype).reshape(size)
            assert not np.any((a>0)&(a<=m['cutoff']))
            if original is not None:
                src=original[tuple(slice(o,o+n) for o,n in zip(p,size))]
                np.testing.assert_array_equal(a,np.where(src>m['cutoff'],src,0))
            intervals.append((base-1,base-1+n));hist+=np.bincount(a.ravel(),minlength=len(hist))
            voxels+=int(np.count_nonzero(a));records+=1
            for axis in range(3):
                sl=tuple(slice(o,o+n) for j,(o,n) in enumerate(zip(p,size)) if j!=axis)
                np.maximum(result_mips[axis][sl],a.max(axis=axis),out=result_mips[axis][sl])
    cursor=0
    for start,end in sorted(intervals):assert start==cursor;cursor=end
    assert cursor*dtype.itemsize==m['density_bytes']
    assert voxels==m['selected_voxels'] and records==m['bricks']
    np.testing.assert_array_equal(hist[m['cutoff']+1:],np.array(m['histogram'])[m['cutoff']+1:])
    checks=[]
    for axis,a in enumerate(result_mips):
        reference=np.load(path/f'threshold-mip-{axis}.npy')
        different=int(np.count_nonzero(a!=reference));checks.append(dict(axis=axis,different_pixels=different,pixels=a.size));assert not different
        np.save(path/f'export-mip-{axis}.npy',a)
    result=dict(name=m['name'],source_scale=m['source_scale'],dtype=m['dtype'],selected_voxels=voxels,bricks=records,
                exact_selected_intensity_histogram=True,stored_voxels_checked_against_raw=original is not None,
                orthogonal_mip_checks=checks,limitations='MIP equality is not a DVR framebuffer comparison. Threshold preservation is not anatomical validation.')
    (path/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();verify(a.directory)
