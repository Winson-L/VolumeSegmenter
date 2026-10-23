"""Reproduce three public, checksum-verified reference/pipeline examples."""
import argparse,hashlib,json
from pathlib import Path
import urllib.request
from pipeline.large_volume import RawSource,export
from pipeline.group_large_volume import group_volume
from pipeline.verify_large_volume import verify
from pipeline.verify_large_groups import verify_groups

DATASETS={
 'bonsai':(256,'b34156a0ffc80ffaf84d069f3d05a40fdd999a35f05492829a2b0c13403a3147e73712b1d10c2cc34da66a59540a1632dae6adc96f3ebf3efa5d4d6c10598997','volvis.org; S. Roettger, VIS, University of Stuttgart'),
 'foot':(256,'56a73bd1f694a09809688f5b0bbf0dfff0ef3e853a34c60c4d51bef02dd96fbfe5191f47c7762bdf7caab6f9a22f1d0e830652779f87c70cc519f345221edd0e','volvis.org; Philips Research, Hamburg'),
 'engine':(128,'f17228483b1b5edb90146eac90ba979531629a2880d9e7a0493a98290da8af6ac2cf80f2c567a3d08695dc7dd854916c861dad8856b2d5721501954e913de13f','volvis.org; General Electric')}
def prepare(name,base):
 depth,sha,credit=DATASETS[name];base=Path(base);base.mkdir(parents=True,exist_ok=True)
 raw=base/(name+'-original.raw')
 url=f'http://klacansky.com/open-scivis-datasets/{name}/{name}_256x256x{depth}_uint8.raw'
 if not raw.exists():
  with urllib.request.urlopen(url,timeout=60) as response,raw.open('wb') as target:
   while chunk:=response.read(1024*1024):target.write(chunk)
 h=hashlib.sha512()
 with raw.open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 if h.hexdigest()!=sha:raise ValueError('Source SHA-512 mismatch: '+name)
 source=RawSource(raw,(depth,256,256),'uint8',(1,1,1),name)
 source.root.update(source_url=url,sha512=sha,credits=credit)
 dense=base/(name+'32');grouped=base/(name+'-groups')
 export(source,dense,32,save_original=True)
 verify(dense)
 group_volume(dense,grouped,[96,160],masked=None)
 result=verify_groups(grouped,dense)
 (grouped/'provenance.json').write_text(json.dumps(dict(source_url=url,catalog='http://klacansky.com/open-scivis-datasets/',sha512=sha,credits=credit,selection='Fixed intensity >32; exploratory foreground target, not semantic classification.'),indent=2)+'\n')
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--names',nargs='+',choices=list(DATASETS),default=list(DATASETS));p.add_argument('--output',default='experiments/large-volumes')
 a=p.parse_args()
 for name in a.names:prepare(name,a.output)
