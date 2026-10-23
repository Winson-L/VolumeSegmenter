const $=id=>document.getElementById(id);
const params=new URLSearchParams(location.search),dataset=params.get('dataset')||'skull',large=['kingsnake','woodbranch','bonsai','foot','engine'].includes(dataset),staticReference=large&&(dataset==='woodbranch'||(dataset==='kingsnake'&&params.get('reference')==='image'));
$('dataset').value=dataset;
$('dataset').onchange=()=>{location.href='compare_volumes.html?dataset='+$('dataset').value;};
$('reference').onchange=()=>{location.href='compare_volumes.html?dataset='+dataset+'&reference='+$('reference').value;};

const frames=[$('leftFrame'),$('rightFrame')],ready=[false,false];
// Unit quaternions rotate the shared camera from view space to volume space.
const multiply=(a,b)=>[
 a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],
 a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],
 a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],
 a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2]];
const normalized=q=>{const n=Math.hypot(...q);return q.map(v=>v/n);};
const axisAngle=(axis,a)=>[...axis.map(v=>v*Math.sin(a/2)),Math.cos(a/2)];
const initial=()=>axisAngle([1,0,0],dataset==='bonsai'?-Math.PI/2:Math.PI/2);
let rotation=initial(),zoom=1.8,queued=false,drag=null;
function matrix([x,y,z,w]){return [1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)];}
function sync(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;const message={type:'volume-camera',rotation:matrix(rotation),zoom,live:$('live').checked,step:+$('step').value,cutoff:+$('cutoff').value,window:large?+$('window').value:undefined,transfer:large?transferSettings():undefined};frames.forEach((f,i)=>{if(ready[i])f.contentWindow.postMessage(message,location.origin);});});}
function point(event,element){const r=element.getBoundingClientRect(),scale=Math.min(r.width,r.height);let x=(2*(event.clientX-r.left)-r.width)/scale,y=(r.height-2*(event.clientY-r.top))/scale;const d=x*x+y*y;
 if(d<=1)return [x,y,Math.sqrt(1-d)];const s=1/Math.sqrt(d);return [x*s,y*s,0];}
function between(a,b){const dot=Math.max(-1,Math.min(1,a.reduce((s,v,i)=>s+v*b[i],0)));let cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
 if(dot<-.999999){const ref=Math.abs(a[0])<.8?[1,0,0]:[0,1,0];cross=[a[1]*ref[2]-a[2]*ref[1],a[2]*ref[0]-a[0]*ref[2],a[0]*ref[1]-a[1]*ref[0]];return normalized([...cross,0]);}return normalized([...cross,1+dot]);}
for(const element of [$('leftDrag'),$('rightDrag')]){
 element.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();element.focus();element.setPointerCapture(e.pointerId);drag={id:e.pointerId,start:point(e,element),rotation:[...rotation],element};};
 element.onpointermove=e=>{if(!drag||e.pointerId!==drag.id||element!==drag.element)return;const delta=between(drag.start,point(e,element));rotation=normalized(multiply(drag.rotation,[-delta[0],-delta[1],-delta[2],delta[3]]));sync();};
 const finish=e=>{if(drag?.id===e.pointerId)drag=null;};element.onpointerup=finish;element.onpointercancel=finish;element.onlostpointercapture=finish;
 element.addEventListener('wheel',e=>{e.preventDefault();const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?element.clientHeight:1);zoom=Math.max(.8,Math.min(4,zoom*Math.exp(delta*.001)));sync();},{passive:false});
 element.onkeydown=e=>{const direction={ArrowLeft:[0,-.08],ArrowRight:[0,.08],ArrowUp:[1,-.08],ArrowDown:[1,.08]}[e.key];if(direction){e.preventDefault();rotation=normalized(multiply(rotation,axisAngle(direction[0]?[1,0,0]:[0,1,0],direction[1])));sync();}else if(e.key==='+'||e.key==='-'){e.preventDefault();zoom=Math.max(.8,Math.min(4,zoom*(e.key==='+'?.9:1.1)));sync();}};
}
for(const id of ['step','cutoff','window'])$(id).oninput=()=>{$(id+'Value').textContent=$(id).value;sync();};
$('live').onchange=()=>{for(const side of ['left','right']){if(side==='left'&&staticReference)continue;$(side+'FPS').textContent=$('live').checked?'FPS 测量中…':'FPS 已暂停';}sync();};
$('reset').onclick=()=>{rotation=initial();zoom=1.8;sync();};
$('front').onclick=()=>{rotation=initial();sync();};
$('side').onclick=()=>{rotation=multiply(axisAngle([0,1,0],Math.PI/2),initial());sync();};
$('groups').onchange=()=>{const value=$('groups').value;frames[1].contentWindow.postMessage({type:'volume-selection',ids:value==='all'?groupIDs:[+value]},location.origin);};
let groupIDs=[];
window.addEventListener('message',e=>{
 if(e.origin!==location.origin)return;const index=frames.findIndex(f=>f.contentWindow===e.source);if(index<0)return;
 const m=e.data;if(m?.type==='volume-performance'){if($('live').checked)$(index?'rightFPS':'leftFPS').textContent=`${m.fps.toFixed(1)} FPS · GPU ${m.gpu_ms===null?'不可用':m.gpu_ms.toFixed(2)+' ms'} · ${m.width}×${m.height}`;return;}if(m?.type==='volume-error'){setGroupBusy(false);$('status').textContent=m.message;$('status').classList.add('error');return;}
 if(m?.type!=='volume-ready')return;ready[index]=true;
 if(large&&index===1)updateGroups(m);
 $(index?'rightMemory':'leftMemory').textContent=(m.payload_bytes/1048576).toFixed(2)+' MiB';
 if(index===0)$('leftCaption').textContent=`${m.dimensions.join(' × ')} 原始体素 · 显示阈值仅控制可见性`;
 else{
  $('rightCaption').textContent=`${m.bricks.toLocaleString()} 个活动小块 · 筛选后共 ${m.selected_voxels.toLocaleString()} 个体素`;
  if(!large&&!groupIDs.length){groupIDs=m.groups.map(g=>g.id);for(const g of m.groups){const option=document.createElement('option');option.value=g.id;option.textContent=g.name;$('groups').append(option);}$('groups').disabled=false;}
 }
 if(ready.every(Boolean))$('status').textContent=staticReference?'右侧可旋转 · 左侧为静态外观参考，视角、阈值与传递函数不同':'已同步 · 相同视角、缩放、显示阈值和采样步长';sync();
});

const manifest=large?'./experiments/large-volumes/'+(dataset+'-groups')+'/metadata.json':params.get('manifest')||'./experiments/supervolume/selected8/metadata.json';
if(large){
 $('transferPanel').hidden=false;$('groupPanel').hidden=false;$('groups').closest('label').hidden=true;$('referenceControl').hidden=false;$('windowControl').hidden=false;
 const cutoff=dataset==='woodbranch'?5000:dataset==='kingsnake'?40:32,max=dataset==='woodbranch'?57147:255;
 $('cutoff').max=max-1;$('cutoff').value=cutoff;$('cutoffValue').textContent=cutoff;
 $('window').max=max;$('window').value=dataset==='woodbranch'?12000:max;$('windowValue').textContent=$('window').value;
 document.querySelector('h1').textContent=dataset+' · reference / pipeline';
 document.querySelector('.help').textContent='右侧保持全分辨率与原始位深；Kingsnake 提取阈值 >40，Woodbranch >5000，其余新样例 >32。降低显示阈值不会恢复右侧已删除的体素。FPS 受刷新率及共享 GPU 影响；纹理用量不是总显存。';
 document.querySelectorAll('.panel-head h2')[0].textContent=staticReference?'网上渲染 reference':'完整原始 reference';
 document.querySelectorAll('.panel-head p')[0].textContent=staticReference?'Kiln Gallery · '+(dataset==='kingsnake'?'MIP':'DVR')+' · 静态截图':'原始分辨率 · 未做提取过滤';
 $('reference').value=staticReference?'image':'original';if(!['kingsnake','woodbranch'].includes(dataset))$('referenceControl').hidden=true;
 if(dataset==='woodbranch')$('reference').querySelector('[value="original"]').disabled=true;
 if(staticReference){
  ready[0]=true;frames[0].hidden=true;$('leftDrag').hidden=true;
  $('referenceImage').hidden=false;$('referenceImage').src='https://kilnrender.com/gallery/'+dataset+'.webp';
  $('referenceImage').onerror=()=>{$('leftCaption').textContent='参考图加载失败；请打开下方来源链接查看。';};
  $('leftMemory').textContent='静态图片';$('leftFPS').textContent='FPS 不适用';
  $('leftCaption').replaceChildren(document.createTextNode('外观参考，非逐像素验证 · '));
  const link=document.createElement('a');link.href='https://kilnrender.com/gallery';link.textContent='来源：Kiln Gallery';link.target='_blank';link.rel='noopener';$('leftCaption').append(link);
  document.querySelector('.badge').textContent='右侧 Arcball';
  document.querySelector('header p').textContent='右侧拖动旋转、滚轮缩放 · 左侧为网上参考截图';
 }
}
for(let i=0;i<2;i++){
 if(i===0&&staticReference)continue;
 const url=new URL(large?'large_volume.html':'sparse_volume.html',location.href);url.searchParams.set('embed','1');url.searchParams.set('v','compare-5');url.searchParams.set('manifest',manifest);
 if(!i){url.searchParams.set('original','1');if(params.has('input'))url.searchParams.set('input',params.get('input'));}
 frames[i].src=url.href;
}

function transferSettings(){
 const colors=['Low','Mid','High'].map(s=>{const v=$('color'+s).value;return [1,3,5].map(i=>parseInt(v.slice(i,i+2),16)/255);});
 const opacity=['Low','Mid','High'].map(s=>Math.max(0,Math.min(1,Number($('alpha'+s).value)||0)));
 return {colors,opacity};
}
for(const s of ['Low','Mid','High'])for(const prefix of ['color','alpha'])$(prefix+s).oninput=sync;
$('tfPreset').onchange=()=>{const a=$('tfPreset').value==='surface'?[.002,.04,.15]:[.0001,.003,.06];['Low','Mid','High'].forEach((s,i)=>$('alpha'+s).value=a[i]);sync();};
let groupTableBuilt=false;
const mib=n=>n===0?'0 B':n<1048576?(n/1024).toFixed(2)+' KiB':(n/1048576).toFixed(2)+' MiB';
function setGroupBusy(value){for(const e of document.querySelectorAll('#groupPanel button,#groupRows input'))e.disabled=value;}
function sendGroups(){const ids=[...document.querySelectorAll('#groupRows input:checked')].map(e=>+e.value);setGroupBusy(true);$('groupSelection').textContent='正在重建所选组纹理…';frames[1].contentWindow.postMessage({type:'volume-selection',ids},location.origin);}
$('selectAll').onclick=()=>{document.querySelectorAll('#groupRows input').forEach(e=>e.checked=true);sendGroups();};
$('selectNone').onclick=()=>{document.querySelectorAll('#groupRows input').forEach(e=>e.checked=false);sendGroups();};
function updateGroups(m){
 setGroupBusy(false);
 if(!groupTableBuilt&&m.groups?.length){
  for(const g of m.groups){
   const tr=document.createElement('tr'),td=document.createElement('td'),box=document.createElement('input');
   box.type='checkbox';box.value=g.id;box.checked=true;box.setAttribute('aria-label',g.name);box.onchange=sendGroups;td.append(box);tr.append(td);
   for(const text of [g.name+' ('+g.components+' 个连通区域)',g.bricks.toLocaleString(),mib(g.selected_voxels*m.bytes_per_voxel),mib(g.density_bytes+(g.mask_bytes||0)+g.index_bytes)]){const cell=document.createElement('td');cell.textContent=text;tr.append(cell);}
   $('groupRows').append(tr);
  }groupTableBuilt=true;
 }
 const total=m.total_density_bytes+(m.total_mask_bytes||0)+(m.group_index_bytes||0);
 $('groupTotals').textContent='原始 '+mib(m.source_bytes)+' → 全部分组存储 '+mib(total)+'（减少 '+(100*(1-total/m.source_bytes)).toFixed(1)+'%）；其中体素载荷 '+mib(m.total_density_bytes)+'，位图 '+mib(m.total_mask_bytes||0)+'，组索引 '+mib(m.group_index_bytes||0);
 $('groupSelection').textContent='当前选中载荷 '+mib(m.selected_density_bytes+(m.selected_mask_bytes||0))+' · 实际驻留 GPU '+mib(m.payload_bytes)+'（含页表 '+mib(m.page_bytes)+'、纹理对齐；不含驱动/浏览器）';
 if(m.selected_ids!==null)for(const box of document.querySelectorAll('#groupRows input'))box.checked=m.selected_ids.includes(+box.value);
}
