"""Bounded-memory OME-Zarr v3 -> cropped bricks. Intensity baseline, NOT SLIC.

Supports the public Open SciVis bytes+zstd, unsharded ZYX uint8/uint16
arrays. Raw precision and full resolution are retained. Only values <= cutoff
are discarded. Files are streamed; no full volume or full label array exists.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import hashlib
import itertools
import json
import resource
from pathlib import Path
import time
import urllib.request
import urllib.error

import numpy as np
import zstandard

BASE = 'https://ome-zarr-scivis.s3.us-east-1.amazonaws.com/v0.5/96x2'


def fetch(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code == 404: raise
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


class Source:
    def __init__(self, name, scale=0):
        self.name, self.scale = name, scale
        # The public 96x2 Kingsnake mirror has stale chunk metadata (96^3 payloads
        # declared as 100x128x128). The alternative mirror also needs per-chunk
        # validation; use the original RAW for the full-resolution Kingsnake run.
        base = BASE.replace('/96x2','/64x2') if name == 'kingsnake' else BASE
        self.base = f'{base}/{name}.ome.zarr'
        self.root = json.loads(fetch(self.base+'/zarr.json'))
        self.path = f'scale{scale}/{name}'
        self.meta = self.root['consolidated_metadata']['metadata'][self.path]
        m = self.meta
        if m['data_type'] not in ('uint8', 'uint16') or [c['name'] for c in m['codecs']] != ['bytes', 'zstd']:
            raise ValueError('Only unsharded uint8/16 bytes+zstd sources are supported')
        if m['codecs'][0].get('configuration', {}).get('endian', 'little') != 'little':
            raise ValueError('Require little endian')
        self.dtype = np.dtype('u1' if m['data_type'] == 'uint8' else '<u2')
        self.shape = tuple(m['shape'])
        self.chunks = tuple(m['chunk_grid']['configuration']['chunk_shape'])
        transforms = self.root['attributes']['ome']['multiscales'][0]['datasets'][scale]['coordinateTransformations']
        self.spacing = next(t['scale'] for t in transforms if t['type'] == 'scale')
        self.grid = tuple((n+c-1)//c for n,c in zip(self.shape,self.chunks))

    def chunk(self, index):
        url = self.base+'/'+self.path+'/c/'+'/'.join(map(str,index))
        # Zarr specifies missing chunk keys as fill_value; only HTTP 404 qualifies.
        try:
            compressed = fetch(url)
            raw = zstandard.ZstdDecompressor().decompress(compressed, max_output_size=int(np.prod(self.chunks))*self.dtype.itemsize)
        except urllib.error.HTTPError as error:
            if error.code != 404: raise
            compressed = b''
            raw = np.full(self.chunks, self.meta['fill_value'], dtype=self.dtype).tobytes()
        if len(raw) != int(np.prod(self.chunks))*self.dtype.itemsize:
            raise ValueError('Invalid decompressed chunk size')
        array = np.frombuffer(raw, self.dtype).reshape(self.chunks)
        origin = tuple(i*c for i,c in zip(index,self.chunks))
        valid = tuple(slice(0,min(c,n-o)) for c,n,o in zip(self.chunks,self.shape,origin))
        return origin, array[valid], len(compressed), hashlib.sha256(raw).hexdigest()

    def blocks(self, workers=4):
        # Bound futures/results to one batch; executor.map can retain the whole dataset.
        indices = iter(itertools.product(*(range(n) for n in self.grid)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while batch := list(itertools.islice(indices, workers)):
                yield from pool.map(self.chunk, batch)


class RawSource:
    """Sequential slab reads: no full input mmap or full-sized working arrays."""
    def __init__(self,path,shape,dtype,spacing,name):
        self.file=Path(path);self.name=name;self.scale=0;self.shape=tuple(shape);self.dtype=np.dtype(dtype)
        self.spacing=list(spacing);self.chunks=(16,self.shape[1],self.shape[2]);self.grid=((self.shape[0]+15)//16,1,1)
        if self.file.stat().st_size!=int(np.prod(shape))*self.dtype.itemsize:raise ValueError('RAW byte length mismatch')
        self.base='http://klacansky.com/open-scivis-datasets/'+name+'/'
        self.root=dict(raw_file=self.file.name,shape_zyx=shape,dtype=dtype,spacing_zyx=spacing,source_url=self.base)
    def blocks(self,workers=1):
        with self.file.open('rb') as f:
            for z in range(0,self.shape[0],16):
                shape=(min(16,self.shape[0]-z),*self.shape[1:]);raw=f.read(int(np.prod(shape))*self.dtype.itemsize)
                yield (z,0,0),np.frombuffer(raw,self.dtype).reshape(shape),0,hashlib.sha256(raw).hexdigest()


def crop_bricks(array, origin, brick, cutoff):
    """Disjoint, globally aligned rectangular cells; partial boundary cells valid."""
    if any(o % b for o,b in zip(origin,brick)):
        raise ValueError('Source chunk origins must align with brick grid')
    mask = array > cutoff
    padded_shape = tuple(((n+b-1)//b)*b for n,b in zip(array.shape,brick))
    padded = np.zeros(padded_shape, bool)
    padded[tuple(slice(0,n) for n in array.shape)] = mask
    nz,ny,nx = (n//b for n,b in zip(padded_shape,brick)); bz,by,bx = brick
    occupied = padded.reshape(nz,bz,ny,by,nx,bx).any(axis=(1,3,5))
    for iz,iy,ix in np.argwhere(occupied):
        local = (int(iz)*bz,int(iy)*by,int(ix)*bx)
        sl = tuple(slice(o,o+b) for o,b in zip(local,brick))
        submask = mask[sl]
        coords = np.where(submask)
        lo = tuple(int(c.min()) for c in coords); hi = tuple(int(c.max())+1 for c in coords)
        crop = tuple(slice(a,b) for a,b in zip(lo,hi))
        data = np.where(submask[crop],array[sl][crop],0).astype(array.dtype)
        cell = tuple((o+l)//b for o,l,b in zip(origin,local,brick))
        yield cell, lo, data, int(submask.sum())


def profile(source):
    hist = np.zeros(65536 if source.dtype.itemsize == 2 else 256, np.int64)
    for _,a,_,_ in source.blocks():
        hist += np.bincount(a.ravel(),minlength=len(hist))
    from skimage.filters import threshold_otsu
    threshold = int(threshold_otsu(hist=(hist,np.arange(len(hist)))))
    cdf = hist.cumsum()
    return dict(shape_zyx=source.shape,dtype=str(source.dtype),scale=source.scale,
                otsu=threshold, nonzero=int(hist[1:].sum()), voxels=int(hist.sum()),
                quantiles={str(p):int(np.searchsorted(cdf,cdf[-1]*p)) for p in [.5,.9,.95,.98,.99,.995]},
                histogram=hist.tolist())


def export(source, output, cutoff, brick=None, workers=4, save_original=False):
    start=time.perf_counter(); out=Path(output)
    if out.exists() and any(out.iterdir()):raise ValueError('Choose an empty export directory')
    out.mkdir(parents=True,exist_ok=True)
    # Largest divisor <=16: Kingsnake source chunks are 100×128×128.
    brick = tuple(brick or [max(b for b in range(4,17) if c%b==0) for c in source.chunks])
    if any(b>32 or b<1 for b in brick) or not 0<=cutoff<np.iinfo(source.dtype).max:
        raise ValueError('Invalid brick or cutoff')
    grid=tuple((n+b-1)//b for n,b in zip(source.shape,brick))
    pages=np.zeros((*grid,4),dtype='<u4')
    hist=np.zeros(1<<(8*source.dtype.itemsize),np.int64)
    offset=0; selected=0; bricks=0; compressed_bytes=0; full_brick_voxels=0
    payload_hash=hashlib.sha256(); input_chunks_hash=hashlib.sha256()
    bounds_lo=np.array(source.shape);bounds_hi=np.zeros(3,dtype=int)
    mips=[np.zeros(tuple(n for j,n in enumerate(source.shape) if j!=axis),source.dtype) for axis in range(3)]
    total=int(np.prod(source.grid))
    original=(out/'original.raw').open('wb') if save_original else None
    if original: original.truncate(int(np.prod(source.shape))*source.dtype.itemsize)
    with (original if original else nullcontext()), (out/'density.raw').open('wb') as target:
        for index,(origin,array,received,chunk_hash) in enumerate(source.blocks(workers)):
            if original:
                oz,oy,ox=origin; nz,ny,nx=array.shape; _,height,width=source.shape
                for z in range(nz):
                    for y in range(ny):
                        original.seek(((oz+z)*height*width+(oy+y)*width+ox)*source.dtype.itemsize)
                        original.write(array[z,y].tobytes())
            compressed_bytes+=received; input_chunks_hash.update(bytes.fromhex(chunk_hash))
            hist+=np.bincount(array.ravel(),minlength=len(hist))
            for axis in range(3):
                sl=tuple(slice(o,o+n) for j,(o,n) in enumerate(zip(origin,array.shape)) if j!=axis)
                np.maximum(mips[axis][sl],array.max(axis=axis),out=mips[axis][sl])
            for cell,lo,data,count in crop_bricks(array,origin,brick,cutoff):
                if offset+data.size>=2**32:raise ValueError('Packed element address exceeds uint32')
                # Packed metadata: base+1, local XYZ origin (5 bits/axis), XYZ size (6 bits/axis).
                xyz=lo[::-1]; dims=data.shape[::-1]
                pages[cell]=(offset+1,xyz[0]|xyz[1]<<5|xyz[2]<<10,dims[0]|dims[1]<<6|dims[2]<<12,0)
                raw=data.tobytes();target.write(raw);payload_hash.update(raw)
                p=np.array(cell)*brick+lo; bounds_lo=np.minimum(bounds_lo,p);bounds_hi=np.maximum(bounds_hi,p+data.shape)
                offset+=data.size;selected+=count;bricks+=1;full_brick_voxels+=int(np.prod(brick))
            if index%32==0 or index+1==total:
                print(json.dumps(dict(chunks=index+1,total=total,selected_voxels=selected,packed_MiB=round(offset*source.dtype.itemsize/2**20,2),seconds=round(time.perf_counter()-start,1))),flush=True)
    if original: original.close()
    for axis,mip in enumerate(mips):
        np.save(out/f'original-mip-{axis}.npy',mip)
        np.save(out/f'threshold-mip-{axis}.npy',np.where(mip>cutoff,mip,0).astype(source.dtype))
    pages.tofile(out/'pages.raw')
    meta=dict(schema_version=4,format='compact-cropped-bricks',name=source.name,source_url=source.base,
              source_scale=source.scale,original_file='original.raw' if save_original else None,dimensions_xyz=list(source.shape[::-1]),spacing_xyz=source.spacing[::-1],
              dtype=source.dtype.name,bytes_per_voxel=source.dtype.itemsize,brick_xyz=list(brick[::-1]),grid_xyz=list(grid[::-1]),
              cutoff=cutoff,value_max=int(np.flatnonzero(hist)[-1]),selected_voxels=selected,bricks=bricks,
              density_file='density.raw',pages_file='pages.raw',density_bytes=offset*source.dtype.itemsize,page_bytes=pages.nbytes,
              density_sha256=payload_hash.hexdigest(),pages_sha256=hashlib.sha256(pages.tobytes()).hexdigest(),
              source_chunk_hash_chain=input_chunks_hash.hexdigest(),source_bytes=int(np.prod(source.shape))*source.dtype.itemsize,
              transfer_bytes=compressed_bytes,fixed_brick_bytes=full_brick_voxels*source.dtype.itemsize,
              bounds_xyz=dict(lo=bounds_lo[::-1].tolist() if selected else [0,0,0],hi=bounds_hi[::-1].tolist()),
              method='Strict raw intensity > cutoff; no SLIC, component deletion, quantization or downsampling',
              processing_seconds=time.perf_counter()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              histogram=hist.tolist())
    # macOS ru_maxrss is bytes; Linux is KiB.
    import sys
    if sys.platform!='darwin':meta['peak_rss_bytes']*=1024
    (out/'metadata.json').write_text(json.dumps(meta,separators=(',',':'))+'\n')
    (out/'source.json').write_text(json.dumps(source.root,indent=2)+'\n')
    return meta


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['profile','export']);p.add_argument('--name',required=True)
    p.add_argument('--scale',type=int,default=0);p.add_argument('--output',required=True);p.add_argument('--cutoff',type=int);p.add_argument('--workers',type=int,default=4);p.add_argument('--save-original',action='store_true');p.add_argument('--raw',help='Verified Kingsnake RAW fallback')
    a=p.parse_args()
    if a.raw and (a.name!='kingsnake' or a.scale!=0):p.error('--raw currently describes the full Kingsnake dataset only')
    source=RawSource(a.raw,(795,1024,1024),'uint8',(.0688,.03174,.03174),a.name) if a.raw else Source(a.name,a.scale)
    if a.action=='profile':
        result=profile(source);Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(result)+'\n');print({k:v for k,v in result.items() if k!='histogram'})
    else:
        if a.cutoff is None:p.error('--cutoff required')
        result=export(source,a.output,a.cutoff,workers=a.workers,save_original=a.save_original);print({k:v for k,v in result.items() if k!='histogram'})
