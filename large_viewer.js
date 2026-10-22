const $=id=>document.getElementById(id),canvas=$('canvas'),gl=canvas.getContext('webgl2',{antialias:false,preserveDrawingBuffer:true});
if(!gl)throw Error('需要 WebGL2');
const params=new URLSearchParams(location.search),url=new URL(params.get('manifest')||'./experiments/large-volumes/kingsnake40/metadata.json',location.href);
const ext=gl.getExtension('EXT_disjoint_timer_query_webgl2'),MiB=n=>(n/1048576).toFixed(2)+' MiB';
const fragment=`#version 300 es
precision highp float;precision highp int;precision highp usampler2DArray;precision highp usampler3D;
uniform usampler2DArray packedData;uniform usampler3D pageTable,originalData;
uniform ivec3 dims,brick;uniform int packedWidth,packedHeight,mode;uniform vec2 resolution,angles;
uniform vec3 spacing;uniform float zoom,stepSize,cutoff,windowMax;
out vec4 color;
vec3 rotate(vec3 p){float a=angles.x,b=angles.y; p=vec3(p.x,cos(a)*p.y-sin(a)*p.z,sin(a)*p.y+cos(a)*p.z);return vec3(cos(b)*p.x+sin(b)*p.z,p.y,-sin(b)*p.x+cos(b)*p.z);}
void main(){
 vec2 uv=gl_FragCoord.xy/resolution*2.-1.;uv.x*=resolution.x/resolution.y;
 vec3 size=vec3(dims)*spacing;float scale=max(size.x,max(size.y,size.z));
 vec3 ro=(size*.5+rotate(vec3(0,0,-scale*zoom)))/spacing,rd=rotate(normalize(vec3(uv,1.5)))/spacing;
 vec3 sd=vec3(rd.x<0.?-1.:1.,rd.y<0.?-1.:1.,rd.z<0.?-1.:1.)*max(abs(rd),vec3(1e-9));
 vec3 a=-ro/sd,b=(vec3(dims)-ro)/sd,n=min(a,b),f=max(a,b);
 float start=max(0.,max(n.x,max(n.y,n.z))),end=min(f.x,min(f.y,f.z)),sampleIndex=0.;
 vec3 rgb=vec3(0);float remaining=1.;ivec3 cached=ivec3(-1);uvec4 record=uvec4(0);
 for(int s=0;s<16384;s++){
  float t=start+(sampleIndex+.5)*stepSize;if(t>=end||remaining<.005)break;
  vec3 p=ro+rd*t;ivec3 v=ivec3(floor(p));float value=0.;
  if(all(greaterThanEqual(v,ivec3(0)))&&all(lessThan(v,dims))){
   if(mode==0)value=float(texelFetch(originalData,v,0).r);
   else{
    ivec3 cell=v/brick;
    if(any(notEqual(cell,cached))){cached=cell;record=texelFetch(pageTable,cell,0);}
    if(record.x==0u){
     vec3 edge=vec3((cell+ivec3(step(vec3(0),rd)))*brick),exits=(edge-ro)/sd;
     if(abs(rd.x)<1e-9)exits.x=1e30;if(abs(rd.y)<1e-9)exits.y=1e30;if(abs(rd.z)<1e-9)exits.z=1e30;
     sampleIndex=max(sampleIndex+1.,ceil((min(exits.x,min(exits.y,exits.z))-start)/stepSize-.5));continue;
    }
    ivec3 origin=ivec3(record.y&31u,(record.y>>5u)&31u,(record.y>>10u)&31u);
    ivec3 shape=ivec3(record.z&63u,(record.z>>6u)&63u,(record.z>>12u)&63u),q=v-cell*brick-origin;
    if(all(greaterThanEqual(q,ivec3(0)))&&all(lessThan(q,shape))){
     uint index=record.x-1u+uint((q.z*shape.y+q.y)*shape.x+q.x);
     value=float(texelFetch(packedData,ivec3(index%uint(packedWidth),(index/uint(packedWidth))%uint(packedHeight),index/(uint(packedWidth)*uint(packedHeight))),0).r);
    }
   }
  }
  if(value>cutoff){float d=clamp(value/windowMax,0.,1.),alpha=1.-exp(-d*stepSize*.12);rgb+=remaining*alpha*mix(vec3(.22,.5,.7),vec3(1.,.9,.72),d);remaining*=1.-alpha;}
  sampleIndex+=1.;
 }
 color=vec4(pow(rgb+remaining*vec3(.025,.035,.05),vec3(1./2.2)),1.);
}`;
function compile(type,s){const shader=gl.createShader(type);gl.shaderSource(shader,s);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(shader));return shader;}
const program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,'#version 300 es\nlayout(location=0) in vec2 p;void main(){gl_Position=vec4(p,0,1);}'));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
gl.useProgram(program);const vao=gl.createVertexArray();gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
const loc=n=>gl.getUniformLocation(program,n),frame=()=>new Promise(r=>requestAnimationFrame(r)),median=a=>{if(!a.length)return null;const s=[...a].sort((a,b)=>a-b);return(s[Math.floor((s.length-1)/2)]+s[Math.floor(s.length/2)])/2;};
let meta,packed,pages,original,packedWidth=1,packedHeight=1,payload=0,current='compact',busy=false,rx=Math.PI/2,ry=0,zoom=1.8,report=null;
const budget=1024*1048576;
$('fps').textContent='按需渲染；点击独立对比测 GPU 每帧耗时';
async function data(path){const r=await fetch(new URL(path,url));if(!r.ok)throw Error(`${r.status}: ${path}`);return r.arrayBuffer();}
async function checked(path,sha){const a=await data(path);const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',a))].map(b=>b.toString(16).padStart(2,'0')).join('');if(actual!==sha)throw Error('数据校验失败');return a;}
function texture(target,size,values,internal,format,type,unit){gl.activeTexture(gl.TEXTURE0+unit);const t=gl.createTexture();gl.bindTexture(target,t);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);if(target===gl.TEXTURE_2D)gl.texImage2D(target,0,internal,...size,0,format,type,values);else gl.texImage3D(target,0,internal,...size,0,format,type,values);for(const p of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER])gl.texParameteri(target,p,gl.NEAREST);for(const p of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T])gl.texParameteri(target,p,gl.CLAMP_TO_EDGE);if(target===gl.TEXTURE_3D)gl.texParameteri(target,gl.TEXTURE_WRAP_R,gl.CLAMP_TO_EDGE);if(gl.getError()!==gl.NO_ERROR){gl.deleteTexture(t);throw Error('GPU 纹理分配失败');}return t;}
function release(){for(const t of [packed,pages,original])if(t)gl.deleteTexture(t);packed=pages=original=null;}
async function load(mode){
 if(mode==='original'){
  if(meta.dimensions_xyz.some(n=>n>gl.getParameter(gl.MAX_3D_TEXTURE_SIZE)))throw Error('完整数据超过 MAX_3D_TEXTURE_SIZE');
  if(meta.source_bytes>budget)throw Error(`完整体素 ${MiB(meta.source_bytes)} 超过本实验 1024 MiB 单体预算（未执行分配，不等于实测 OOM）`);
  if(!meta.original_file)throw Error('未保存完整 RAW；可按块生成参考投影');
 }
 release();current=mode;$('status').textContent='加载 '+mode+'…';
 const type=meta.bytes_per_voxel===2?gl.UNSIGNED_SHORT:gl.UNSIGNED_BYTE,internal=meta.bytes_per_voxel===2?gl.R16UI:gl.R8UI,ArrayType=meta.bytes_per_voxel===2?Uint16Array:Uint8Array;
 if(mode==='compact'){
  const max=gl.getParameter(gl.MAX_TEXTURE_SIZE),count=meta.density_bytes/meta.bytes_per_voxel;
  packedWidth=max;const layers=Math.max(1,Math.ceil(count/(max*max)));const height=Math.max(1,Math.ceil(count/(packedWidth*layers)));packedHeight=height;
  if(layers>gl.getParameter(gl.MAX_ARRAY_TEXTURE_LAYERS)||height*packedWidth*layers*meta.bytes_per_voxel+meta.page_bytes>budget)throw Error('紧密纹理超过容量或 1024 MiB 预算');
  const a=new ArrayType(await checked(meta.density_file,meta.density_sha256));const padded=new ArrayType(packedWidth*height*layers);padded.set(a);
  packed=texture(gl.TEXTURE_2D_ARRAY,[packedWidth,height,layers],padded,internal,gl.RED_INTEGER,type,0);
  const table=new Uint32Array(await checked(meta.pages_file,meta.pages_sha256));
  pages=texture(gl.TEXTURE_3D,meta.grid_xyz,table,gl.RGBA32UI,gl.RGBA_INTEGER,gl.UNSIGNED_INT,1);
  original=texture(gl.TEXTURE_3D,[1,1,1],new Uint8Array(1),gl.R8UI,gl.RED_INTEGER,gl.UNSIGNED_BYTE,2);
  payload=padded.byteLength+table.byteLength+1;
 }else{
  const a=new ArrayType(await data(meta.original_file));if(a.byteLength!==meta.source_bytes)throw Error('原始大小不匹配');
  original=texture(gl.TEXTURE_3D,meta.dimensions_xyz,a,internal,gl.RED_INTEGER,type,2);
  packed=texture(gl.TEXTURE_2D_ARRAY,[1,1,1],new Uint8Array(1),gl.R8UI,gl.RED_INTEGER,gl.UNSIGNED_BYTE,0);
  pages=texture(gl.TEXTURE_3D,[1,1,1],new Uint32Array(4),gl.RGBA32UI,gl.RGBA_INTEGER,gl.UNSIGNED_INT,1);payload=a.byteLength+17;
 }
 $('memory').textContent=`${mode==='compact'?'紧密分块':'完整原始'} GPU 纹理：${MiB(payload)}`;$('status').textContent='已加载 · 拖动旋转，滚轮缩放';$('mode').value=mode;draw();
}
function draw(fixed){
 if(!packed||!pages||!original)return;
 const [w,h]=fixed||[Math.round(canvas.clientWidth*Math.min(devicePixelRatio,2)),Math.round(canvas.clientHeight*Math.min(devicePixelRatio,2))];if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.useProgram(program);gl.bindVertexArray(vao);
 for(const [i,t,target] of [[0,packed,gl.TEXTURE_2D_ARRAY],[1,pages,gl.TEXTURE_3D],[2,original,gl.TEXTURE_3D]]){gl.activeTexture(gl.TEXTURE0+i);gl.bindTexture(target,t);}
 gl.uniform1i(loc('packedData'),0);gl.uniform1i(loc('pageTable'),1);gl.uniform1i(loc('originalData'),2);gl.uniform1i(loc('packedWidth'),packedWidth);gl.uniform1i(loc('packedHeight'),packedHeight);gl.uniform1i(loc('mode'),current==='original'?0:1);
 gl.uniform3iv(loc('dims'),meta.dimensions_xyz);gl.uniform3iv(loc('brick'),meta.brick_xyz);const minimum=Math.min(...meta.spacing_xyz);gl.uniform3fv(loc('spacing'),meta.spacing_xyz.map(s=>s/minimum));gl.uniform2f(loc('resolution'),w,h);gl.uniform2f(loc('angles'),rx,ry);gl.uniform1f(loc('zoom'),zoom);gl.uniform1f(loc('stepSize'),+$('step').value);gl.uniform1f(loc('cutoff'),meta.cutoff);gl.uniform1f(loc('windowMax'),+$('window').value);gl.drawArrays(gl.TRIANGLES,0,3);
}
function pixels(){const a=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,a);return a;}
async function timed(){const samples=[];for(let i=0;i<5;i++){await frame();draw([640,480]);}for(let i=0;i<20;i++){await frame();if(!ext){draw([640,480]);continue;}const q=gl.createQuery();try{gl.beginQuery(ext.TIME_ELAPSED_EXT,q);draw([640,480]);gl.endQuery(ext.TIME_ELAPSED_EXT);gl.flush();const deadline=performance.now()+5000;while(!gl.getQueryParameter(q,gl.QUERY_RESULT_AVAILABLE)){if(performance.now()>deadline)throw Error('GPU 计时超时');await frame();}if(!gl.getParameter(ext.GPU_DISJOINT_EXT))samples.push(gl.getQueryParameter(q,gl.QUERY_RESULT)/1e6);}finally{gl.deleteQuery(q);}}
 const ms=median(samples);return {mode:current,gpu_median_ms:ms,gpu_equivalent_fps:ms?1000/ms:null,gpu_samples_ms:samples,texture_bytes:payload};}
async function benchmark(){
 const old=[rx,ry,zoom,current],runs=[],checks=[];let skip=null;
 const angles=[[Math.PI/2,0],[.6,.8],[-.35,1.9]];
 try{
  for(let i=0;i<angles.length;i++){
   [rx,ry]=angles[i];zoom=1.8;let reference;
   // Alternate order to reduce simple warm-up/order bias.
   for(const mode of i%2?['compact','original']:['original','compact']){
    try{await load(mode);}catch(e){if(mode==='original'){skip=e.message;continue;}throw e;}
    $('status').textContent=`测试 ${i+1}/3 · ${mode}`;draw([640,480]);const p=pixels();runs.push({camera:[rx,ry],...await timed()});
    if(reference){let changed=0,max=0;for(let j=0;j<p.length;j++){const d=Math.abs(p[j]-reference[j]);if(d)changed++;max=Math.max(max,d);}checks.push({camera:[rx,ry],different_channels:changed,max_byte_error:max});}else reference=p;
   }
  }
  report={dataset:meta.name,source_bytes:meta.source_bytes,cutoff:meta.cutoff,resolution:[640,480],step:+$('step').value,window_max:+$('window').value,source_scale:meta.source_scale,dtype:meta.dtype,original_skipped:skip,image_checks:checks,runs,environment:{user_agent:navigator.userAgent,renderer:gl.getParameter(gl.RENDERER),max_3d_texture_size:gl.getParameter(gl.MAX_3D_TEXTURE_SIZE),max_2d_texture_size:gl.getParameter(gl.MAX_TEXTURE_SIZE),original_budget_bytes:budget},method:'Sequential modes, 3 views, 5 warmups+20 asynchronous GPU queries per mode/view; payload excludes CPU/browser/driver. Full source and selected source share cutoff, transfer, spacing and sample lattice.'};
  $('results').textContent=JSON.stringify(report,null,2);
  $('summary').textContent=runs.map(r=>`${r.mode}: ${r.gpu_median_ms?.toFixed(2)??'N/A'} ms · ${MiB(r.texture_bytes)}`).join('\n')+(skip?'\n原始未运行：'+skip:`\n图像核对：${checks.filter(c=>c.different_channels===0).length}/${checks.length} 完全一致`);$('download').disabled=false;
 }finally{[rx,ry,zoom]=old;await load(old[3]);}
}
async function action(fn){if(busy)return;busy=true;for(const e of document.querySelectorAll('button,select,input'))e.disabled=true;try{await fn();}catch(e){$('status').textContent=e.message;console.error(e);$('mode').value=current;}finally{busy=false;for(const e of document.querySelectorAll('button,select,input'))e.disabled=false;$('download').disabled=!report;}}
$('mode').onchange=()=>action(()=>load($('mode').value));$('benchmark').onclick=()=>action(benchmark);$('step').oninput=()=>{$('stepValue').textContent=$('step').value;draw();};$('window').oninput=()=>draw();$('reset').onclick=()=>{rx=Math.PI/2;ry=0;zoom=1.8;draw();};
$('download').onclick=()=>{const a=document.createElement('a'),u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));a.href=u;a.download=meta.name+'-rendering.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
let drag=null;canvas.onpointerdown=e=>{if(busy)return;canvas.setPointerCapture(e.pointerId);drag=[e.clientX,e.clientY,rx,ry];};canvas.onpointermove=e=>{if(!drag||busy)return;rx=drag[2]+(e.clientY-drag[1])*.008;ry=drag[3]+(e.clientX-drag[0])*.008;draw();};canvas.onpointerup=canvas.onpointercancel=()=>drag=null;canvas.addEventListener('wheel',e=>{e.preventDefault();if(busy)return;zoom=Math.max(.8,Math.min(4,zoom*Math.exp(e.deltaY*.001)));draw();},{passive:false});
window.addEventListener('resize',()=>{if(!busy)draw();});
await action(async()=>{meta=JSON.parse(new TextDecoder().decode(await data(url.href)));if(meta.schema_version!==4)throw Error('Require compact schema 4');$('title').textContent=meta.name+' · 全分辨率紧密分块';$('source').textContent=`原始 ${meta.dimensions_xyz.join(' × ')} · ${meta.dtype} · ${MiB(meta.source_bytes)}；${meta.bricks.toLocaleString()} 个非空小块。`;$('method').textContent=`删除原始值 ≤ ${meta.cutoff}；保留 ${(100*meta.selected_voxels/(meta.source_bytes/meta.bytes_per_voxel)).toFixed(2)}% 体素。未改变位深或分辨率。`;$('window').max=meta.value_max;$('window').value=meta.value_max;await load('compact');});
