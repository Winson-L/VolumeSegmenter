"""SLIC candidates -> constrained graph selection -> cropped sparse bricks.

XYZ externally, ZYX arrays; uint8 scalar values, not calibrated tissue classes.
The analysis cache is optional working data. Export contains selected data only.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from skimage.segmentation import slic
from threadpoolctl import threadpool_limits
from pipeline.extractVolume import read_volume


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fresh(path):
    p = Path(path)
    if p.exists() and any(p.iterdir()):
        raise ValueError(f'Choose an empty output directory: {p}')
    p.mkdir(parents=True, exist_ok=True)
    return p


def region_graph(volume, labels):
    """Exact uint8 histograms and face-adjacent contact/contrast statistics."""
    n = int(labels.max()) + 1
    hist = np.zeros((n, 256), dtype=np.int64)
    # Bound temporary indexing arrays instead of building an Nx256 one-hot array.
    for z in range(volume.shape[0]):
        key = labels[z].ravel().astype(np.int64) * 256 + volume[z].ravel()
        hist += np.bincount(key, minlength=n*256).reshape(n, 256)
    edges = {}
    for axis in range(3):
        a, b = [slice(None)]*3, [slice(None)]*3
        a[axis], b[axis] = slice(None, -1), slice(1, None)
        left, right = labels[tuple(a)], labels[tuple(b)]
        different = left != right
        lo, hi = np.minimum(left[different], right[different]), np.maximum(left[different], right[different])
        key = lo.astype(np.int64)*n + hi
        unique, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
        delta = np.abs(volume[tuple(a)][different].astype(np.int16)-volume[tuple(b)][different])
        sums = np.bincount(inverse, weights=delta, minlength=len(unique))
        for k, count, total in zip(unique, counts, sums):
            pair = (int(k//n), int(k % n))
            c, s = edges.get(pair, (0, 0.0))
            edges[pair] = (c+int(count), s+float(total))
    return hist, [dict(a=a, b=b, contacts=c, mean_boundary_delta=s/c)
                  for (a, b), (c, s) in sorted(edges.items())]


@threadpool_limits.wrap(limits=1)
def analyze(source, shape, output, region_size=16, compactness=0.08, spacing=(1, 1, 1)):
    if not isinstance(region_size, int) or region_size < 2 or not np.isfinite(compactness) or compactness <= 0:
        raise ValueError('Require region_size >=2 and finite compactness >0')
    if len(spacing) != 3 or any(not np.isfinite(x) or x <= 0 for x in spacing):
        raise ValueError('Spacing must contain three positive finite values')
    volume = read_volume(source, shape)
    out = fresh(output); start = time.perf_counter()
    labels = slic(volume.astype(np.float32)/255, n_segments=max(1, round(volume.size/region_size**3)),
                  compactness=compactness, sigma=0, spacing=spacing[::-1], channel_axis=None,
                  convert2lab=False, enforce_connectivity=True, min_size_factor=0.1,
                  max_size_factor=3, start_label=1).astype(np.uint32)
    hist, edges = region_graph(volume, labels)
    counts = hist.sum(axis=1)
    cdf = hist.cumsum(axis=1)
    regions = []
    for i in range(1, len(hist)):
        if not counts[i]:
            continue
        regions.append(dict(id=i, voxels=int(counts[i]), mean=float(hist[i]@np.arange(256)/counts[i]),
                            p10=int(np.searchsorted(cdf[i], counts[i]*.1)),
                            median=int(np.searchsorted(cdf[i], counts[i]*.5)),
                            p90=int(np.searchsorted(cdf[i], counts[i]*.9)),
                            histogram=hist[i].tolist()))
    labels.astype('<u4').tofile(out/'labels.u32')
    report = dict(schema_version=1, dimensions_xyz=list(shape), input_sha256=digest(volume.tobytes()),
                  parameters=dict(method='3D SLIC', region_size=region_size, compactness=compactness,
                                  spacing_xyz=list(spacing), smoothing=0, connectivity='face'),
                  regions=regions, edges=edges, processing_seconds=time.perf_counter()-start)
    (out/'analysis.json').write_text(json.dumps(report, separators=(',', ':'))+'\n')
    return report


def select_groups(volume, labels, analysis, config):
    """Fixed target distributions prevent transitive intensity drift.

    Seeded graph growth never enters an ineligible region. Histogram support and
    boundary contrast operate at region level; final range clipping is explicit.
    Groups own disjoint voxels: earlier config entries have priority on overlap.
    """
    groups = config.get('groups', [])
    if not 1 <= len(groups) <= 255:
        raise ValueError('Require 1–255 groups')
    regions = analysis['regions']; n = int(labels.max())+1
    h = np.zeros((n, 256), dtype=np.float64)
    for r in regions:
        h[r['id']] = r['histogram']
    counts = h.sum(axis=1)
    adjacency = [[] for _ in range(n)]
    for e in analysis['edges']:
        adjacency[e['a']].append((e['b'], e['mean_boundary_delta']))
        adjacency[e['b']].append((e['a'], e['mean_boundary_delta']))
    owner = np.zeros(volume.shape, dtype=np.uint8)
    summaries = []
    for gid, g in enumerate(groups, 1):
        low, high = g['intensity_range']
        fraction = g.get('min_fraction', .1)
        boundary = g.get('max_boundary_delta', 255)
        if not (0 <= low <= high <= 255 and int(low)==low and int(high)==high):
            raise ValueError('Intensity ranges must be integer inclusive bounds in [0,255]')
        if not 0 <= fraction <= 1 or not 0 <= boundary <= 255:
            raise ValueError('Invalid support fraction or boundary contrast')
        low, high = int(low), int(high)
        support = h[:, low:high+1].sum(axis=1)
        eligible = (counts > 0) & (support > 0) & (support >= fraction*counts)
        seeds = set(g.get('region_ids', []))
        for xyz in g.get('seeds_xyz', []):
            if len(xyz)!=3 or any(int(x)!=x or x<0 or x>=s for x, s in zip(xyz, volume.shape[::-1])):
                raise ValueError('Seed outside original XYZ volume')
            seeds.add(int(labels[tuple(int(v) for v in xyz[::-1])]))
        mode = g.get('mode', 'seeded')
        if mode not in ('seeded', 'all_candidates'):
            raise ValueError('mode must be seeded or all_candidates')
        if mode == 'seeded' and not seeds:
            raise ValueError('Seeded selection requires seeds_xyz or region_ids')
        if any(not isinstance(i, int) or i<=0 or i>=n or not eligible[i] for i in seeds):
            raise ValueError('Seed region fails the fixed target range/support rule')
        distance = g.get('max_seed_histogram_distance')
        if distance is not None:
            if not seeds or not 0 <= distance <= 1:
                raise ValueError('Histogram distance requires seeds and a value in [0,1]')
            # Total variation distance to the fixed pooled SEED histogram.
            reference = h[sorted(seeds)].sum(axis=0); reference /= reference.sum()
            distributions = h / np.maximum(counts[:, None], 1)
            eligible &= .5*np.abs(distributions-reference).sum(axis=1) <= distance
            eligible[list(seeds)] = True
        chosen = np.zeros(n, dtype=bool)
        if mode == 'all_candidates':
            chosen = eligible.copy()
        else:
            queue = deque(sorted(seeds)); chosen[list(seeds)] = True
            while queue:
                i = queue.popleft()
                for j, delta in adjacency[i]:
                    if eligible[j] and not chosen[j] and delta <= boundary:
                        chosen[j] = True; queue.append(j)
        mask = chosen[labels]
        if g.get('clip_to_range', True):
            mask &= (volume >= low) & (volume <= high)
        # Zero intensity is the sparse background; zero-valued semantic labels are not exported.
        mask &= volume > 0
        overlap = int(np.count_nonzero(mask & (owner > 0)))
        owner[mask & (owner == 0)] = gid
        summaries.append(dict(id=gid, name=g.get('name', f'Group {gid}'), rule=g,
                              eligible_regions=int(eligible.sum()), selected_region_ids=np.flatnonzero(chosen).tolist(),
                              overlap_voxels_assigned_to_earlier_groups=overlap,
                              selected_voxels=int(np.count_nonzero(owner == gid))))
    return owner, summaries


def tight(mask):
    coords = np.where(mask)
    if not coords[0].size:
        return None
    lo = [int(c.min()) for c in coords]; hi = [int(c.max())+1 for c in coords]
    return lo, hi


def build_tree(bricks, ids):
    """Spatial BVH over leaf references. Internal nodes allocate NO voxel array."""
    if not ids:
        return None
    lo = np.min([bricks[i]['origin_xyz'] for i in ids], axis=0)
    hi = np.max([np.array(bricks[i]['origin_xyz'])+bricks[i]['dimensions_xyz'] for i in ids], axis=0)
    node = dict(origin_xyz=lo.tolist(), extent_xyz=(hi-lo).tolist())
    if len(ids) <= 8:
        node['brick_ids'] = ids
    else:
        axis = int(np.argmax(hi-lo))
        ids = sorted(ids, key=lambda i: bricks[i]['origin_xyz'][axis]+bricks[i]['dimensions_xyz'][axis]/2)
        middle = len(ids)//2
        node['children'] = [build_tree(bricks, ids[:middle]), build_tree(bricks, ids[middle:])]
    return node


def export_bricks(volume, owner, groups, output, brick_size=16, provenance=None):
    if brick_size not in (8, 16, 32):
        raise ValueError('brick_size must be 8,16,32')
    if owner.shape != volume.shape or owner.dtype != np.uint8:
        raise ValueError('Owner map must match volume as uint8')
    out = fresh(output); records = []; offset = 0
    with (out/'density.raw').open('wb') as density, (out/'owners.raw').open('wb') as owners:
        for z in range(0, volume.shape[0], brick_size):
            for y in range(0, volume.shape[1], brick_size):
                for x in range(0, volume.shape[2], brick_size):
                    cell = (slice(z,z+brick_size),slice(y,y+brick_size),slice(x,x+brick_size))
                    bounds = tight(owner[cell]>0)
                    if bounds is None:
                        continue
                    lo, hi = bounds; local = tuple(slice(a,b) for a,b in zip(lo,hi))
                    labels = owner[cell][local].copy()
                    values = np.where(labels, volume[cell][local], 0).astype(np.uint8)
                    raw = values.tobytes(); density.write(raw); owners.write(labels.tobytes())
                    origin = (np.array([z,y,x])+lo)[::-1].tolist()
                    records.append(dict(id=len(records), cell_xyz=[x//brick_size,y//brick_size,z//brick_size],
                                        origin_xyz=origin, dimensions_xyz=list(values.shape[::-1]),
                                        offset=offset, bytes=len(raw), groups=np.unique(labels[labels>0]).tolist()))
                    offset += len(raw)
    for g in groups:
        ids = [b['id'] for b in records if g['id'] in b['groups']]
        g['tree'] = build_tree(records, ids)
        bounds = tight(owner == g['id'])
        g['aabb'] = None if bounds is None else dict(origin_xyz=bounds[0][::-1], extent_xyz=(np.array(bounds[1])-bounds[0])[::-1].tolist())
    selected = np.where(owner, volume, 0).astype(np.uint8)
    metrics = {}
    for level in (0, 60, 120):
        reference = volume > level
        metrics[str(level)] = dict(original_voxels=int(reference.sum()),
                                  removed_voxels=int(np.count_nonzero(reference & (owner==0))))
    meta = dict(schema_version=3, format='cropped-grid-bricks', dimensions_xyz=list(volume.shape[::-1]),
                dtype='uint8', brick_size=brick_size, density_file='density.raw', owners_file='owners.raw',
                density_sha256=digest((out/'density.raw').read_bytes()),
                owners_sha256=digest((out/'owners.raw').read_bytes()),
                input_sha256=digest(volume.tobytes()), selected_sha256=digest(selected.tobytes()),
                density_bytes=offset, owner_bytes=offset, selected_voxels=int(np.count_nonzero(owner)),
                intensity_survival=metrics, bricks=records, groups=groups, provenance=provenance,
                ownership='Config order wins overlapping selections; every stored voxel has one group',
                rendering='Nearest original voxel grid; parent AABBs are metadata only')
    (out/'metadata.json').write_text(json.dumps(meta, separators=(',', ':'))+'\n')
    restored, owners = reconstruct_sparse(out)
    if not np.array_equal(selected, restored) or not np.array_equal(owner, owners):
        raise AssertionError('Sparse export reconstruction failed')
    return meta


def reconstruct_sparse(directory):
    p=Path(directory); m=json.loads((p/'metadata.json').read_text())
    result=np.zeros(m['dimensions_xyz'][::-1],dtype=np.uint8); owner=np.zeros_like(result)
    data=np.fromfile(p/m['density_file'],dtype=np.uint8); labels=np.fromfile(p/m['owners_file'],dtype=np.uint8)
    for b in m['bricks']:
        o=b['origin_xyz'][::-1]; d=b['dimensions_xyz'][::-1]
        region=tuple(slice(a,a+n) for a,n in zip(o,d)); start=b['offset']; end=start+b['bytes']
        result[region]=data[start:end].reshape(d); owner[region]=labels[start:end].reshape(d)
    return result,owner


def extract_selected(source, cache, config_path, output, brick_size=16):
    cache=Path(cache); report=json.loads((cache/'analysis.json').read_text())
    volume=read_volume(source,report['dimensions_xyz'])
    if digest(volume.tobytes()) != report['input_sha256']:
        raise ValueError('Analysis cache belongs to a different input')
    labels=np.fromfile(cache/'labels.u32',dtype='<u4').reshape(volume.shape)
    config=json.loads(Path(config_path).read_text())
    owner,groups=select_groups(volume,labels,report,config)
    return export_bricks(volume,owner,groups,output,brick_size,
                         dict(analysis_parameters=report['parameters'],selection=config))


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    a=sub.add_parser('analyze'); a.add_argument('--input',required=True); a.add_argument('--shape',nargs=3,type=int,required=True)
    a.add_argument('--output',required=True); a.add_argument('--region-size',type=int,default=16)
    a.add_argument('--compactness',type=float,default=.08); a.add_argument('--spacing',nargs=3,type=float,default=[1,1,1])
    i=sub.add_parser('inspect'); i.add_argument('--analysis',required=True); i.add_argument('--xyz',nargs=3,type=int,required=True)
    e=sub.add_parser('export'); e.add_argument('--input',required=True); e.add_argument('--analysis',required=True)
    e.add_argument('--config',required=True); e.add_argument('--output',required=True); e.add_argument('--brick-size',type=int,default=16)
    args=parser.parse_args()
    if args.command=='analyze':
        r=analyze(args.input,args.shape,args.output,args.region_size,args.compactness,args.spacing)
        print(json.dumps(dict(regions=len(r['regions']),edges=len(r['edges']),seconds=r['processing_seconds'])))
    elif args.command=='inspect':
        cache=Path(args.analysis); a=json.loads((cache/'analysis.json').read_text())
        if any(x<0 or x>=s for x,s in zip(args.xyz,a['dimensions_xyz'])):
            raise ValueError('Coordinate outside volume')
        labels=np.memmap(cache/'labels.u32',dtype='<u4',mode='r',shape=tuple(a['dimensions_xyz'][::-1]))
        rid=int(labels[tuple(args.xyz[::-1])]); region=next(r for r in a['regions'] if r['id']==rid)
        print(json.dumps(dict(xyz=args.xyz,region=region),indent=2))
    else:
        r=extract_selected(args.input,args.analysis,args.config,args.output,args.brick_size)
        print(json.dumps(dict(bricks=len(r['bricks']),density_bytes=r['density_bytes'],owner_bytes=r['owner_bytes'],groups=[(g['name'],g['selected_voxels']) for g in r['groups']])))


if __name__=='__main__':
    main()
