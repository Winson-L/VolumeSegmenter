"""Independently decode each group and compare every brick to the dense export."""
import argparse,json
from pathlib import Path
import numpy as np
from verify_large_volume import file_hash

def verify_groups(grouped, original):
    path=Path(grouped);root=Path(original)
    m=json.loads((path/'metadata.json').read_text());old=json.loads((root/'metadata.json').read_text())
    dtype=np.dtype(m['dtype']);pages=np.fromfile(root/'pages.raw','<u4').reshape(-1,4)
    source=np.memmap(root/'density.raw',dtype=dtype,mode='r')
    seen=set();total=0
    for g in m['groups']:
        for kind in ['density','index']+(['mask'] if m['storage_encoding']=='masked32' else []):
            assert file_hash(path/g[kind+'_file'])==g[kind+'_sha256']
        values=np.memmap(path/g['density_file'],dtype=dtype,mode='r')
        entries=np.fromfile(path/g['index_file'],'<u4').reshape(-1,4)
        masks=np.fromfile(path/g['mask_file'],'<u4').reshape(-1,2) if m['storage_encoding']=='masked32' else None
        count=0
        for cell,base,origin,shape in entries:
            cell=int(cell);base=int(base);shape=int(shape);assert cell not in seen;seen.add(cell)
            assert int(origin)==int(pages[cell,1]) and shape==int(pages[cell,2])
            n=int(np.prod([(shape>>s)&63 for s in [0,6,12]]))
            expected=source[int(pages[cell,0])-1:int(pages[cell,0])-1+n]
            if masks is None:actual=values[base-1:base-1+n]
            else:
                actual=np.zeros(n,dtype)
                for i in range((n+31)//32):
                    offset,bits=map(int,masks[base-1+i]);positions=[j for j in range(32) if bits&(1<<j)]
                    assert all(i*32+j<n for j in positions)
                    actual[np.array(positions,dtype=int)+i*32]=values[offset:offset+len(positions)]
            np.testing.assert_array_equal(actual,expected);count+=int(np.count_nonzero(actual))
        assert count==g['selected_voxels'];total+=count
    assert seen==set(np.flatnonzero(pages[:,0]).tolist())
    assert total==old['selected_voxels']
    result=dict(dataset=m['name'],groups=len(m['groups']),bricks=len(seen),selected_voxels=total,
        every_stored_voxel_exact=True,unique_brick_ownership=True,density_bytes=m['density_bytes'],
        mask_bytes=m['mask_bytes'],index_bytes=m['group_index_bytes'],source_bytes=m['source_bytes'])
    (path/'group-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('grouped');p.add_argument('original');a=p.parse_args();verify_groups(a.grouped,a.original)
