const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
const base=new URL(params.get('analysis')||'../experiments/supervolume/analysis/',location.href),source=new URL(params.get('input')||'../data/skull_256x256x256_uint8.raw',location.href);
const seeds=new Set();let analysis,values,labels,regions,adjacency,chosen,dimensions,last=null;
async function read(url){const r=await fetch(url);if(!r.ok)throw Error(`${r.status}: ${url}`);return r;}
function rule(){const low=+$('low').value,high=+$('high').value,fraction=+$('fraction').value,boundary=+$('boundary').value;
 if(!Number.isInteger(low)||!Number.isInteger(high)||low<0||low>high||high>255||fraction<0||fraction>1||boundary<0||boundary>255)throw Error('Check intensity, fraction and boundary ranges');
 return {name:$('name').value||'Selected candidate',mode:$('mode').value,intensity_range:[low,high],min_fraction:fraction,max_boundary_delta:boundary,clip_to_range:$('clip').checked,region_ids:[...seeds].sort((a,b)=>a-b)};
}
function update(){try{
 const g=rule(),[low,high]=g.intensity_range;const eligible=new Set();
 for(const r of analysis.regions){let support=0;for(let i=low;i<=high;i++)support+=r.histogram[i];if(support>0&&support>=g.min_fraction*r.voxels)eligible.add(r.id);}
 const rejected=[...seeds].filter(id=>!eligible.has(id));chosen=new Set();
 if(g.mode==='all_candidates')chosen=eligible;
 else{const queue=[...seeds].filter(id=>eligible.has(id));chosen=new Set(queue);for(let k=0;k<queue.length;k++)for(const e of adjacency.get(queue[k])||[]){if(eligible.has(e.id)&&!chosen.has(e.id)&&e.delta<=g.max_boundary_delta){chosen.add(e.id);queue.push(e.id);}}}
 $('status').textContent=`${chosen.size} regions selected; ${seeds.size} seeds. ${rejected.length?'Some seeds fail the target rule: adjust the rule or clear them.':''}`;
 $('download').disabled=rejected.length>0||(g.mode==='seeded'&&!seeds.size);
 paint(g);$('command').textContent='python -m pipeline.supervolume export --input data/skull_256x256x256_uint8.raw --analysis experiments/supervolume/analysis --config selection.json --output experiments/supervolume/my-selection';
 }catch(e){$('status').textContent=e.message;$('download').disabled=true;}}
function paint(g){const [nx,ny]=dimensions,z=+$('slice').value,c=$('sliceCanvas'),ctx=c.getContext('2d');c.width=nx;c.height=ny;const image=ctx.createImageData(nx,ny),offset=z*nx*ny;
 for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){const j=y*nx+x,i=offset+j,v=values[i],label=labels[i],on=chosen.has(label)&&v>0&&(!g.clip_to_range||(v>=g.intensity_range[0]&&v<=g.intensity_range[1]));let r=v,green=v,b=v;
  if(on){r=Math.round(v*.4);green=Math.max(v,170);b=Math.max(v,170);}if(seeds.has(label)){r=255;green=210;b=40;}
  if((x&&labels[i-1]!==label)||(y&&labels[i-nx]!==label)){r=Math.round(r*.55);green=Math.round(green*.55);b=Math.round(b*.55);}
  image.data.set([r,green,b,255],j*4);
 }ctx.putImageData(image,0,0);
 $('detail').textContent=`Z=${z}. ${last?`Last click XYZ=${last.xyz.join(', ')}; intensity=${last.value}; region=${last.id}\nMedian=${regions.get(last.id).median}; p10–p90=${regions.get(last.id).p10}–${regions.get(last.id).p90}; region voxels=${regions.get(last.id).voxels}`:'Click a structure to inspect its region and add a seed.'}`;
}
$('sliceCanvas').onclick=e=>{if(!labels)return;const box=e.currentTarget.getBoundingClientRect(),x=Math.min(dimensions[0]-1,Math.floor((e.clientX-box.left)/box.width*dimensions[0])),y=Math.min(dimensions[1]-1,Math.floor((e.clientY-box.top)/box.height*dimensions[1])),z=+$('slice').value;
 const i=(z*dimensions[1]+y)*dimensions[0]+x;last={xyz:[x,y,z],id:labels[i],value:values[i]};seeds.add(last.id);update();};
for(const id of ['slice','low','high','fraction','boundary','clip','mode'])$(id).oninput=()=>{if(analysis)update();};
$('clear').onclick=()=>{seeds.clear();last=null;update();};
$('download').onclick=()=>{const blob=new Blob([JSON.stringify({groups:[rule()]},null,2)],{type:'application/json'}),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download='selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
try{
 analysis=await(await read(new URL('analysis.json',base))).json();dimensions=analysis.dimensions_xyz;
 values=new Uint8Array(await(await read(source)).arrayBuffer());const buffer=await(await read(new URL('labels.u32',base))).arrayBuffer();labels=new Uint32Array(buffer);
 const expected=dimensions.reduce((a,b)=>a*b,1);if(values.length!==expected||labels.length!==expected)throw Error('Analysis/input size mismatch');
 const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',values))].map(b=>b.toString(16).padStart(2,'0')).join('');if(hash!==analysis.input_sha256)throw Error('Analysis belongs to a different input');
 regions=new Map(analysis.regions.map(r=>[r.id,r]));adjacency=new Map();
 for(const e of analysis.edges){if(!adjacency.has(e.a))adjacency.set(e.a,[]);if(!adjacency.has(e.b))adjacency.set(e.b,[]);adjacency.get(e.a).push({id:e.b,delta:e.mean_boundary_delta});adjacency.get(e.b).push({id:e.a,delta:e.mean_boundary_delta});}
 $('slice').max=dimensions[2]-1;$('slice').value=Math.floor(dimensions[2]/2);update();
}catch(e){$('status').textContent=e.message;console.error(e);}
