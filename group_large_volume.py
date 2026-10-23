"""Group compact bricks by median-intensity bands and six-neighbor connectivity.

Bricks are owned exactly once. This is a bounded brick graph, not voxel SLIC.
Small disconnected regions are explicitly pooled by band for manageable UI.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

def group_volume(directory, output, edges, keep=9, masked=None):
    root=Path(directory).resolve();out=Path(output).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Choose an empty directory')
    out.mkdir(parents=True,exist_ok=True)
    m=json.loads((root/'metadata.json').read_text());dtype=np.dtype(m['dtype'])
    if keep<1 or edges!=sorted(set(edges)) or any(e<=m['cutoff'] or e>m['value_max'] for e in edges):raise ValueError('Require sorted distinct in-range band edges and keep >=1')
    grid=tuple(m['grid_xyz'][::-1]);pages=np.fromfile(root/m['pages_file'],'<u4').reshape(-1,4)
    source=np.memmap(root/m['density_file'],dtype=dtype,mode='r') if m['density_bytes'] else np.array([],dtype=dtype)
    cells=np.flatnonzero(pages[:,0]);n=len(cells)
    bands=np.empty(n,np.int32);counts=np.empty(n,np.int64);sizes=np.empty(n,np.int64)
    medians=np.empty(n,np.float64)
    for i,cell in enumerate(cells):
        base,_,packed,_=map(int,pages[cell]);shape=[(packed>>s)&63 for s in (0,6,12)]
        a=source[base-1:base-1+int(np.prod(shape))];values=a[a>m['cutoff']]
        medians[i]=np.median(values);bands[i]=np.searchsorted(edges,medians[i],side='right')
        counts[i]=values.size;sizes[i]=a.size
    if masked is None:masked=bool((counts.sum()*dtype.itemsize+((sizes+31)//32).sum()*8)<m['density_bytes'])
    parent=np.arange(n);rank=np.zeros(n,np.uint8)
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a==b:return
        if rank[a]<rank[b]:a,b=b,a
        parent[b]=a
        if rank[a]==rank[b]:rank[a]+=1
    lookup=np.full(len(pages),-1,np.int32);lookup[cells]=np.arange(n)
    zyx=np.column_stack(np.unravel_index(cells,grid))
    for axis,stride in enumerate((grid[1]*grid[2],grid[2],1)):
        valid=zyx[:,axis]>0
        for i in np.flatnonzero(valid):
            j=lookup[cells[i]-stride]
            if j>=0 and bands[i]==bands[j]:union(i,j)
    roots=np.array([find(i) for i in range(n)])
    components={}
    for i,r in enumerate(roots):components.setdefault(int(r),[]).append(i)
    ordered=sorted(components.values(),key=lambda v:int(counts[v].sum()),reverse=True)
    buckets=[(v,False) for v in ordered[:keep]]
    for band in range(len(edges)+1):
        v=[i for component in ordered[keep:] for i in component if bands[i]==band]
        if v:buckets.append((v,True))
    groups=[]
    for gid,(indices,residual) in enumerate(buckets,1):
        label=int(bands[indices[0]]);lo=m['cutoff']+1 if label==0 else edges[label-1]
        hi=m['value_max'] if label==len(edges) else edges[label]-1
        entries=[];offset=0;maskoffset=0;masks=[];h=hashlib.sha256();voxels=0
        lower=np.array(m['dimensions_xyz']);upper=np.zeros(3,int)
        with (out/f'group-{gid}.raw').open('wb') as f:
            for i in indices:
                cell=int(cells[i]);base,origin,shape,_=map(int,pages[cell]);a=source[base-1:base-1+sizes[i]]
                if masked:
                    valid=a>m['cutoff'];padded=np.zeros(((a.size+31)//32)*32,np.uint8);padded[:a.size]=valid
                    bits=np.packbits(padded.reshape(-1,32),axis=1,bitorder='little').copy().view('<u4').reshape(-1)
                    numbers=padded.reshape(-1,32).sum(axis=1,dtype=np.uint32)
                    prefix=np.r_[np.uint32(0),np.cumsum(numbers[:-1],dtype=np.uint32)]+offset
                    masks.append(np.column_stack((prefix,bits)).astype('<u4'))
                    entries.append([cell,maskoffset+1,origin,shape]);maskoffset+=len(bits)
                    a=a[valid]
                else:entries.append([cell,offset+1,origin,shape])
                raw=a.tobytes();f.write(raw);h.update(raw)
                offset+=a.size;voxels+=int(counts[i])
                xyz=zyx[i][::-1]*m['brick_xyz']+np.array([(origin>>s)&31 for s in (0,5,10)])
                size=np.array([(shape>>s)&63 for s in (0,6,12)])
                lower=np.minimum(lower,xyz);upper=np.maximum(upper,xyz+size)
        entry_bytes=np.array(entries,dtype='<u4').tobytes();(out/f'group-{gid}-index.raw').write_bytes(entry_bytes)
        maskbytes=b''.join(v.tobytes() for v in masks)
        if masked:(out/f'group-{gid}-mask.raw').write_bytes(maskbytes)
        groups.append(dict(mask_bytes=len(maskbytes),mask_file=f'group-{gid}-mask.raw',mask_sha256=hashlib.sha256(maskbytes).hexdigest(),id=gid,name=f'中位强度 {lo}–{hi} · '+('零散区域合集' if residual else f'连通区域 {gid}'),
            band=label,median_range=[lo,hi],bricks=len(indices),selected_voxels=voxels,
            components=len(set(roots[indices].tolist())),pooled=residual,
            density_bytes=offset*dtype.itemsize,index_bytes=len(entry_bytes),
            density_file=f'group-{gid}.raw',density_sha256=h.hexdigest(),
            index_file=f'group-{gid}-index.raw',index_sha256=hashlib.sha256(entry_bytes).hexdigest(),
            bounds_xyz=dict(lo=lower.tolist(),hi=upper.tolist())))
    assert sum(g['density_bytes'] for g in groups)==(m['selected_voxels']*dtype.itemsize if masked else m['density_bytes'])
    assert sum(g['selected_voxels'] for g in groups)==m['selected_voxels']
    m.update(storage_encoding='masked32' if masked else 'dense-crops',pre_mask_density_bytes=m['density_bytes'],density_bytes=sum(g['density_bytes'] for g in groups),mask_bytes=sum(g['mask_bytes'] for g in groups),groups=groups,group_edges=edges,group_components=len(components),
             grouping='Six-neighbor brick components with same selected-voxel median intensity band. Largest components separate; remainder explicitly pooled per band. Not anatomical labels or voxel SLIC.',
             group_ownership='disjoint bricks; each payload stored once',group_index_bytes=sum(g['index_bytes'] for g in groups),
             original_file=str((root/m['original_file']).resolve()) if m.get('original_file') else None)
    # URLs resolve from the grouped manifest, not the HTTP root.
    import os
    if m['original_file']:m['original_file']=os.path.relpath(Path.cwd()/m['original_file'],out)
    m['density_file']=os.path.relpath(root/'density.raw',out);m['pages_file']=os.path.relpath(root/'pages.raw',out)
    (out/'metadata.json').write_text(json.dumps(m,separators=(',',':'))+'\n')
    print(json.dumps({k:m[k] for k in ['name','bricks','density_bytes','group_components','group_index_bytes']}))
    for g in groups:print(g['name'],g['density_bytes']/2**20,g['components'])
    return m

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('output');p.add_argument('--edges',type=int,nargs='+',required=True);p.add_argument('--keep',type=int,default=9)
    p.add_argument('--masked',action='store_true');p.add_argument('--encoding',choices=['auto','dense','masked'],default='auto');a=p.parse_args();group_volume(a.directory,a.output,a.edges,a.keep,True if a.masked or a.encoding=='masked' else False if a.encoding=='dense' else None)
