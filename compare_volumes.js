const $=id=>document.getElementById(id);
const frames=[$('leftFrame'),$('rightFrame')],ready=[false,false];
// Unit quaternions rotate the shared camera from view space to volume space.
const multiply=(a,b)=>[
 a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],
 a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],
 a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],
 a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2]];
const normalized=q=>{const n=Math.hypot(...q);return q.map(v=>v/n);};
const axisAngle=(axis,a)=>[...axis.map(v=>v*Math.sin(a/2)),Math.cos(a/2)];
const initial=()=>axisAngle([1,0,0],Math.PI/2);
let rotation=initial(),zoom=1.8,queued=false,drag=null;
function matrix([x,y,z,w]){return [1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)];}
function sync(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;const message={type:'volume-camera',rotation:matrix(rotation),zoom,live:$('live').checked,step:+$('step').value,cutoff:+$('cutoff').value};frames.forEach((f,i)=>{if(ready[i])f.contentWindow.postMessage(message,location.origin);});});}
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
for(const id of ['step','cutoff'])$(id).oninput=()=>{$(id+'Value').textContent=$(id).value;sync();};
$('live').onchange=()=>{for(const side of ['left','right'])$(side+'FPS').textContent=$('live').checked?'FPS 测量中…':'FPS 已暂停';sync();};
$('reset').onclick=()=>{rotation=initial();zoom=1.8;sync();};
$('front').onclick=()=>{rotation=initial();sync();};
$('side').onclick=()=>{rotation=multiply(axisAngle([0,1,0],Math.PI/2),initial());sync();};
$('groups').onchange=()=>{const value=$('groups').value;frames[1].contentWindow.postMessage({type:'volume-selection',ids:value==='all'?groupIDs:[+value]},location.origin);};
let groupIDs=[];
window.addEventListener('message',e=>{
 if(e.origin!==location.origin)return;const index=frames.findIndex(f=>f.contentWindow===e.source);if(index<0)return;
 const m=e.data;if(m?.type==='volume-performance'){if($('live').checked)$(index?'rightFPS':'leftFPS').textContent=`${m.fps.toFixed(1)} FPS · GPU ${m.gpu_ms===null?'不可用':m.gpu_ms.toFixed(2)+' ms'} · ${m.width}×${m.height}`;return;}if(m?.type==='volume-error'){$('status').textContent=m.message;$('status').classList.add('error');return;}
 if(m?.type!=='volume-ready')return;ready[index]=true;
 $(index?'rightMemory':'leftMemory').textContent=(m.payload_bytes/1048576).toFixed(2)+' MiB';
 if(index===0)$('leftCaption').textContent=`${m.dimensions.join(' × ')} 原始体素 · 显示阈值仅控制可见性`;
 else{
  $('rightCaption').textContent=`${m.bricks.toLocaleString()} 个活动小块 · 筛选后共 ${m.selected_voxels.toLocaleString()} 个体素`;
  if(!groupIDs.length){groupIDs=m.groups.map(g=>g.id);for(const g of m.groups){const option=document.createElement('option');option.value=g.id;option.textContent=g.name;$('groups').append(option);}$('groups').disabled=false;}
 }
 if(ready.every(Boolean))$('status').textContent='已同步 · 相同视角、缩放、显示阈值和采样步长';sync();
});
const params=new URLSearchParams(location.search),manifest=params.get('manifest')||'./experiments/supervolume/selected8/metadata.json';
for(let i=0;i<2;i++){const url=new URL('sparse_volume.html',location.href);url.searchParams.set('embed','1');url.searchParams.set('v','fps-1');url.searchParams.set('manifest',manifest);if(!i){url.searchParams.set('original','1');if(params.has('input'))url.searchParams.set('input',params.get('input'));}frames[i].src=url.href;}
