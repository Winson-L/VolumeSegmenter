"""Reproduce SLIC selection, brick-size accounting and selection sensitivity."""
import argparse
import copy
import json
from pathlib import Path
import platform
import time

import numpy as np
import skimage
from pipeline.extractVolume import read_volume
from pipeline.supervolume import analyze, select_groups, export_bricks, fresh


def run(source, shape, config_path, output):
    root=fresh(output)
    analysis=analyze(source,shape,root/'analysis')
    volume=read_volume(source,shape)
    labels=np.fromfile(root/'analysis/labels.u32',dtype='<u4').reshape(volume.shape)
    config=json.loads(Path(config_path).read_text())
    start=time.perf_counter();owner,groups=select_groups(volume,labels,analysis,config)
    selection_seconds=time.perf_counter()-start
    rows=[]
    for b in (8,16,32):
        out=root/f'selected{b}';start=time.perf_counter()
        m=export_bricks(volume,owner,copy.deepcopy(groups),out,b,dict(analysis_parameters=analysis['parameters'],selection=config))
        rows.append(dict(brick_size=b,bricks=len(m['bricks']),density_bytes=m['density_bytes'],owner_bytes=m['owner_bytes'],
                         metadata_bytes=(out/'metadata.json').stat().st_size,
                         export_and_verify_seconds=time.perf_counter()-start,selected_sha256=m['selected_sha256'],
                         intensity_survival=m['intensity_survival'],reconstruction_exact=True))
    sweep=[]
    for fraction in (0,.01,.05,.1,.2):
        rule=dict(groups=[dict(mode='all_candidates',intensity_range=[61,255],min_fraction=fraction,clip_to_range=True)])
        owners,stats=select_groups(volume,labels,analysis,rule)
        sweep.append(dict(min_fraction=fraction,selected_regions=len(stats[0]['selected_region_ids']),selected_voxels=int(np.count_nonzero(owners)),
                          removed_above60=int(np.count_nonzero((volume>60)&(owners==0))),removed_above120=int(np.count_nonzero((volume>120)&(owners==0)))))
    report=dict(input_sha256=analysis['input_sha256'],shape_xyz=shape,environment=dict(python=platform.python_version(),numpy=np.__version__,skimage=skimage.__version__),
                analysis_parameters=analysis['parameters'],regions=len(analysis['regions']),edges=len(analysis['edges']),
                analyze_seconds=analysis['processing_seconds'],selection_seconds=selection_seconds,config=config,variants=rows,sensitivity=sweep)
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',default='data/skull_256x256x256_uint8.raw');p.add_argument('--shape',nargs=3,type=int,default=[256]*3)
    p.add_argument('--config',default='configs/skull-candidates.json');p.add_argument('--output',required=True)
    a=p.parse_args();run(a.input,a.shape,a.config,a.output)
