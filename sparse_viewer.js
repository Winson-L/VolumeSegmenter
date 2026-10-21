const $=id=>document.getElementById(id), canvas=$('canvas');
const gl=canvas.getContext('webgl2',{antialias:false,preserveDrawingBuffer:true});
if(!gl)throw Error('WebGL2 required');
const params = new URLSearchParams(location.search);
const embedded = params.get('embed') === '1', originalMode = params.get('original') === '1';
if (embedded) { document.querySelector('aside').hidden = true; document.body.style.overflow = 'hidden'; }
let sharedRotation = null;
const ext=gl.getExtension('EXT_disjoint_timer_query_webgl2');
const vs=`#version 300 es
layout(location=0) in vec2 position;void main(){gl_Position=vec4(position,0,1);}`;
const fs=`#version 300 es
precision highp float;precision highp int;precision highp sampler3D;precision highp usampler3D;
out vec4 color;uniform sampler3D atlas;uniform usampler3D pages;
uniform ivec3 slots;uniform vec3 fullDims,clipMin,clipMax;
uniform mat3 sharedRotation;uniform bool useSharedRotation;
uniform vec2 resolution,angles;uniform float distanceScale,stepSize,cutoff;uniform int brickSize,sparseMode;
vec3 rotate(vec3 p){if(useSharedRotation)return sharedRotation*p;float cx=cos(angles.x),sx=sin(angles.x),cy=cos(angles.y),sy=sin(angles.y);p=vec3(p.x,cx*p.y-sx*p.z,sx*p.y+cx*p.z);return vec3(cy*p.x+sy*p.z,p.y,-sy*p.x+cy*p.z);}
void main(){
 vec2 uv=gl_FragCoord.xy/resolution*2.-1.;uv.x*=resolution.x/resolution.y;
 float scale=max(fullDims.x,max(fullDims.y,fullDims.z));
 vec3 ro=fullDims*.5+rotate(vec3(0,0,-scale*distanceScale)),rd=rotate(normalize(vec3(uv,1.5)));
 vec3 sd=vec3(rd.x<0.?-1.:1.,rd.y<0.?-1.:1.,rd.z<0.?-1.:1.)*max(abs(rd),vec3(1e-7));
 vec3 a=-ro/sd,b=(fullDims-ro)/sd,n=min(a,b),f=max(a,b);
 float start=max(0.,max(n.x,max(n.y,n.z))),end=min(f.x,min(f.y,f.z));
 a=(clipMin-ro)/sd;b=(clipMax-ro)/sd;n=min(a,b);f=max(a,b);
 float first=max(0.,max(n.x,max(n.y,n.z)));end=min(end,min(f.x,min(f.y,f.z)));
 float sampleIndex=max(0.,ceil((first-start)/stepSize-.5));
 vec3 rgb=vec3(0);float remaining=1.;ivec3 cachedCell=ivec3(-1),atlasOffset=ivec3(0);uint page=0u;
 for(int s=0;s<8192;s++){
  float t=start+(sampleIndex+.5)*stepSize;if(t>=end||remaining<.005)break;
  vec3 p=ro+rd*t;ivec3 v=ivec3(floor(p));float d=0.;
  if(all(greaterThanEqual(p,clipMin))&&all(lessThan(p,clipMax))){
   if(sparseMode==0)d=texelFetch(atlas,v,0).r;
   else{
    ivec3 cell=v/brickSize;
    if(any(notEqual(cell,cachedCell))){
     cachedCell=cell;page=texelFetch(pages,cell,0).r;
     int slot=int(page)-1;
     atlasOffset=ivec3(slot%slots.x,(slot/slots.x)%slots.y,slot/(slots.x*slots.y))*brickSize-cell*brickSize;
    }
    if(page==0u){
     vec3 edge=(vec3(cell)+step(vec3(0),rd))*float(brickSize);
     vec3 exits=(edge-ro)/sd;
     if(abs(rd.x)<1e-7)exits.x=1e30;if(abs(rd.y)<1e-7)exits.y=1e30;if(abs(rd.z)<1e-7)exits.z=1e30;
     float leave=min(exits.x,min(exits.y,exits.z));
     sampleIndex=max(sampleIndex+1.,ceil((leave-start)/stepSize-.5));continue;
    }
    d=texelFetch(atlas,atlasOffset+v,0).r;
   }
  }
  if(d>cutoff){float alpha=1.-exp(-d*stepSize*.12);vec3 tint=mix(vec3(.22,.5,.7),vec3(1.,.9,.72),d);rgb+=remaining*alpha*tint;remaining*=1.-alpha;}
  sampleIndex+=1.;
 }
 color=vec4(pow(rgb+remaining*vec3(.025,.035,.05),vec3(1./2.2)),1.);
}`;
function compile(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
const program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,vs));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fs));gl.linkProgram(program);
if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
gl.useProgram(program);const vao=gl.createVertexArray();gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
const loc=name=>gl.getUniformLocation(program,name), median=a=>{const s=[...a].sort((a,b)=>a-b);return s.length?(s[Math.floor((s.length-1)/2)]+s[Math.floor(s.length/2)])/2:null;};
const frame=()=>new Promise(r=>requestAnimationFrame(r));
let meta,density,owners,texture,pageTexture,slots=[1,1,1],selected=new Set(),bounds,mode=1,payload=0,pageBytes=0,activeBricks=0,busy=false,report=null,fixed=null;
const url=new URL(new URLSearchParams(location.search).get('manifest')||'./experiments/supervolume/selected/metadata.json',location.href);
async function fetchData(path){const r=await fetch(new URL(path,url));if(!r.ok)throw Error(`${r.status}: ${path}`);return r;}
function texture3D(data,dims,integer=false){
 if(dims.some(n=>n>gl.getParameter(gl.MAX_3D_TEXTURE_SIZE)))throw Error('Texture exceeds device limits');
 const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_3D,t);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);
 gl.texImage3D(gl.TEXTURE_3D,0,integer?gl.R32UI:gl.R8,...dims,0,integer?gl.RED_INTEGER:gl.RED,integer?gl.UNSIGNED_INT:gl.UNSIGNED_BYTE,data);
 for(const k of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER])gl.texParameteri(gl.TEXTURE_3D,k,gl.NEAREST);
 for(const k of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T,gl.TEXTURE_WRAP_R])gl.texParameteri(gl.TEXTURE_3D,k,gl.CLAMP_TO_EDGE);
 if(gl.getError()!==gl.NO_ERROR){gl.deleteTexture(t);throw Error('Texture allocation failed');}return t;
}
function pack(ids,sparse=true){
 const chosen=new Set(ids), b=meta.brick_size, dims=meta.dimensions_xyz, grid=dims.map(n=>Math.ceil(n/b));
 const active=meta.bricks.filter(r=>r.groups.some(g=>chosen.has(g)));
 const max=Math.floor(gl.getParameter(gl.MAX_3D_TEXTURE_SIZE)/b), n=active.length;
 const side=Math.min(max,Math.max(1,Math.ceil(Math.cbrt(n))));slots=[side,side,Math.max(1,Math.ceil(n/(side*side)))];
 if(slots[2]>max)throw Error('Selection exceeds atlas capacity');
 const atlasDims=sparse?slots.map(n=>n*b):dims;
 const data=new Uint8Array(atlasDims.reduce((a,b)=>a*b,1)),page=new Uint32Array(grid.reduce((a,b)=>a*b,1));
 bounds={lo:[...dims],hi:[0,0,0]};activeBricks=n;
 active.forEach((r,i)=>{
  const [cx,cy,cz]=r.cell_xyz;page[(cz*grid[1]+cy)*grid[0]+cx]=i+1;
  const slot=[i%slots[0],Math.floor(i/slots[0])%slots[1],Math.floor(i/(slots[0]*slots[1]))];
  const [dx,dy,dz]=r.dimensions_xyz,[ox,oy,oz]=r.origin_xyz;
  for(let z=0;z<dz;z++)for(let y=0;y<dy;y++)for(let x=0;x<dx;x++){
   const src=r.offset+(z*dy+y)*dx+x;if(!chosen.has(owners[src])||!density[src])continue;
   const p=[ox+x,oy+y,oz+z];for(let k=0;k<3;k++){bounds.lo[k]=Math.min(bounds.lo[k],p[k]);bounds.hi[k]=Math.max(bounds.hi[k],p[k]+1);}
   const q=sparse?p.map((v,k)=>slot[k]*b+v-r.cell_xyz[k]*b):p;
   data[(q[2]*atlasDims[1]+q[1])*atlasDims[0]+q[0]]=density[src];
  }
 });
 if(!n)bounds={lo:[0,0,0],hi:[0,0,0]};
 if(texture)gl.deleteTexture(texture);if(pageTexture)gl.deleteTexture(pageTexture);
 texture=null;pageTexture=null;
 gl.activeTexture(gl.TEXTURE0);texture=texture3D(data,atlasDims);
 gl.activeTexture(gl.TEXTURE1);pageTexture=texture3D(sparse?page:new Uint32Array(1),sparse?grid:[1,1,1],true);
 mode=sparse?1:0;payload=data.byteLength;pageBytes=sparse?page.byteLength:4;selected=chosen;
 $('memory').textContent=`${n} bricks · ${(payload/1048576).toFixed(3)} MiB ${sparse?'atlas':'monolith'} + ${(pageBytes/1048576).toFixed(3)} MiB page table. CPU export buffers: ${((density.byteLength+owners.byteLength)/1048576).toFixed(3)} MiB.`;
 draw();
}
function draw(){
 if(!texture)return;
 const dims=meta.dimensions_xyz;if(Math.ceil(Math.hypot(...dims)/+$('step').value)>8192)throw Error('Increase step: ray exceeds iteration limit');
 const [w,h]=fixed||[Math.round(canvas.clientWidth*Math.min(devicePixelRatio,2)),Math.round(canvas.clientHeight*Math.min(devicePixelRatio,2))];
 if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
 gl.viewport(0,0,w,h);gl.useProgram(program);gl.bindVertexArray(vao);
 gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_3D,texture);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_3D,pageTexture);
 gl.uniform1i(loc('useSharedRotation'),sharedRotation ? 1 : 0);
 if(sharedRotation)gl.uniformMatrix3fv(loc('sharedRotation'),false,sharedRotation);
 gl.uniform1i(loc('atlas'),0);gl.uniform1i(loc('pages'),1);gl.uniform3iv(loc('slots'),slots);gl.uniform3fv(loc('fullDims'),dims);
 gl.uniform3fv(loc('clipMin'),bounds.lo);gl.uniform3fv(loc('clipMax'),bounds.hi);gl.uniform2f(loc('resolution'),w,h);
 gl.uniform2f(loc('angles'),+$('rx').value*Math.PI/180,+$('ry').value*Math.PI/180);
 gl.uniform1f(loc('distanceScale'),+$('zoom').value);gl.uniform1f(loc('stepSize'),+$('step').value);gl.uniform1f(loc('cutoff'),+$('cutoff').value/255);
 gl.uniform1i(loc('brickSize'),meta.brick_size);gl.uniform1i(loc('sparseMode'),mode);gl.drawArrays(gl.TRIANGLES,0,3);
}
function controls(){
 $('groups').replaceChildren();
 for(const g of meta.groups){const l=document.createElement('label'),c=document.createElement('input'),solo=document.createElement('button');c.type='checkbox';c.checked=selected.has(g.id);c.disabled=busy;
 c.onchange=()=>action(async()=>{const ids=new Set(selected);c.checked?ids.add(g.id):ids.delete(g.id);pack([...ids]);controls();});solo.textContent='Only';solo.disabled=busy;solo.onclick=()=>action(async()=>{pack([g.id]);controls();});
 l.append(c,document.createTextNode(` ${g.name} · ${g.selected_voxels.toLocaleString()} voxels`),solo);$('groups').append(l);}
}
async function action(fn){if(busy)return;busy=true;for(const e of document.querySelectorAll('input,button'))e.disabled=true;
 try{await fn();}catch(e){$('status').textContent=e.message;console.error(e);if(embedded)parent.postMessage({type:'volume-error',message:e.message},location.origin);}finally{busy=false;for(const e of document.querySelectorAll('input,button'))e.disabled=false;$('download').disabled=!report;controls();}}
function pixels(){const p=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,p);return p;}
async function measure(){for(let i=0;i<5;i++){await frame();draw();}const gpu=[],wall=[];
 for(let i=0;i<20;i++){await frame();const t=performance.now(),q=ext?gl.createQuery():null;
 if(q)gl.beginQuery(ext.TIME_ELAPSED_EXT,q);draw();if(q)gl.endQuery(ext.TIME_ELAPSED_EXT);gl.finish();wall.push(performance.now()-t);
 if(q){try{const deadline=performance.now()+5000;while(!gl.getQueryParameter(q,gl.QUERY_RESULT_AVAILABLE)){if(performance.now()>deadline)throw Error('GPU query timeout');await frame();}
 if(!gl.getParameter(ext.GPU_DISJOINT_EXT))gpu.push(gl.getQueryParameter(q,gl.QUERY_RESULT)/1e6);}finally{gl.deleteQuery(q);}}}
 return {gpu_samples_ms:gpu,gpu_median_ms:median(gpu),cpu_submit_finish_median_ms:median(wall),texture_bytes:payload,page_bytes:pageBytes,bricks:activeBricks};}
async function compare(){
 report=null;$('download').disabled=true;const all=meta.groups.map(g=>g.id),old=['rx','ry','zoom','step','cutoff'].map(id=>$(id).value),oldIDs=[...selected];
 fixed=[1280,720];const runs=[],images=[];
 const cases=[{name:'all',ids:all},...meta.groups.map(g=>({name:`group_${g.id}`,ids:[g.id]}))];
 try{
  [90,0,1.8,1,60].forEach((v,i)=>$( ['rx','ry','zoom','step','cutoff'][i]).value=v);
  // Exact framebuffer checks at multiple orientations; no screenshot approximation.
  for(const [rx,ry] of [[90,0],[35,45],[-20,110]])for(const c of cases){
   $('rx').value=rx;$('ry').value=ry;pack(c.ids,false);const reference=pixels();pack(c.ids,true);const actual=pixels();let changed=0,max=0;
   for(let i=0;i<actual.length;i++){const d=Math.abs(actual[i]-reference[i]);if(d)changed++;max=Math.max(max,d);}
   images.push({case:c.name,camera:[rx,ry,1.8],different_channels:changed,max_byte_error:max});
  }
  $('rx').value=90;$('ry').value=0;let seed=42;
  for(let round=1;round<=3;round++){
   const tasks=cases.flatMap(c=>[{...c,sparse:true},{...c,sparse:false}]);
   for(let i=tasks.length-1;i>0;i--){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const j=seed%(i+1);[tasks[i],tasks[j]]=[tasks[j],tasks[i]];}
   for(const c of tasks){$('status').textContent=`Round ${round}/3 · ${c.name} · ${c.sparse?'sparse':'monolith'}`;pack(c.ids,c.sparse);runs.push({case:c.name,sparse:c.sparse,round,...await measure()});}
  }
  const results=cases.flatMap(c=>[true,false].map(sparse=>{const group=runs.filter(r=>r.case===c.name&&r.sparse===sparse),samples=group.flatMap(r=>r.gpu_samples_ms);
   return {case:c.name,sparse,gpu_median_ms:median(samples),round_medians_ms:group.map(r=>r.gpu_median_ms),valid_gpu_samples:samples.length,texture_bytes:group[0].texture_bytes,page_bytes:group[0].page_bytes};}));
  report={schema_version:1,input_sha256:meta.input_sha256,selected_sha256:meta.selected_sha256,brick_size:meta.brick_size,
   environment:{user_agent:navigator.userAgent,renderer:gl.getParameter(gl.RENDERER)},
   methodology:'Same selected voxels, shader transfer and original sample lattice. Three shuffled rounds; five warmups plus 20 GPU queries. 1280x720, camera90/0/1.8, step1, cutoff60. Repacking/network/upload excluded. Payload excludes driver allocations. CPU export arrays retained. Three-angle framebuffer checks.',results,runs,image_checks:images};
  $('report').textContent=JSON.stringify(report,null,2);
  const table=document.createElement('table');table.innerHTML='<tr><th>Selection</th><th>Mode</th><th>MiB</th><th>GPU ms</th></tr>';
  for(const r of results){const tr=document.createElement('tr');for(const value of [r.case,r.sparse?'Sparse':'Mono',((r.texture_bytes+r.page_bytes)/1048576).toFixed(3),r.gpu_median_ms?.toFixed(3)??'Unavailable']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}$('results').replaceChildren(table);
  $('status').textContent=`Complete. ${images.filter(i=>i.different_channels===0).length}/${images.length} exact framebuffer matches.`;
 }finally{fixed=null;old.forEach((v,i)=>$( ['rx','ry','zoom','step','cutoff'][i]).value=v);pack(oldIDs,true);}
}
$('all').onclick=()=>action(async()=>{pack(meta.groups.map(g=>g.id));controls();});$('compare').onclick=()=>action(compare);
$('download').onclick=()=>{if(!report)return;const u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=u;a.download='supervolume-rendering.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
for(const id of ['rx','ry','zoom','step','cutoff'])$(id).oninput=()=>{try{draw();}catch(e){$('status').textContent=e.message;}};
window.addEventListener('resize',()=>{if(!busy)draw();});
function announce() {
 if (embedded) parent.postMessage({type:'volume-ready', original:originalMode,
  payload_bytes:payload+pageBytes, bricks:activeBricks, groups:meta.groups.map(g=>({id:g.id,name:g.name})),
  dimensions:meta.dimensions_xyz, selected_voxels:meta.selected_voxels},location.origin);
}
window.addEventListener('message',event=>{
 if(!embedded||event.origin!==location.origin||event.source!==parent||!meta)return;
 const m=event.data;
 if(m?.type==='volume-camera'&&Array.isArray(m.rotation)&&m.rotation.length===9&&m.rotation.every(Number.isFinite)){
  sharedRotation=m.rotation;
  for(const [id,value,lo,hi] of [['zoom',m.zoom,.8,4],['step',m.step,.5,4],['cutoff',m.cutoff,0,254]])
   if(Number.isFinite(value))$(id).value=Math.max(lo,Math.min(hi,value));
  draw();
 } else if(m?.type==='volume-selection'&&!originalMode&&Array.isArray(m.ids)){
  action(async()=>{pack(m.ids.filter(id=>meta.groups.some(g=>g.id===id)));controls();announce();});
 }
});
await action(async()=>{
 meta=await(await fetchData(url.href)).json();
 if(meta.schema_version!==3||meta.format!=='cropped-grid-bricks')throw Error('Unsupported sparse manifest');
 if(originalMode){
  const rawURL=new URL(params.get('input')||'./skull_256x256x256_uint8.raw',location.href);
  const raw=new Uint8Array(await(await fetchData(rawURL.href)).arrayBuffer());
  if(raw.length!==meta.dimensions_xyz.reduce((a,b)=>a*b,1))throw Error('Original dimensions do not match');
  const sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('');
  if(sha!==meta.input_sha256)throw Error('Original and selected dataset hashes differ');
  gl.activeTexture(gl.TEXTURE0);texture=texture3D(raw,meta.dimensions_xyz);
  gl.activeTexture(gl.TEXTURE1);pageTexture=texture3D(new Uint32Array(1),[1,1,1],true);
  mode=0;payload=raw.byteLength;pageBytes=4;bounds={lo:[0,0,0],hi:meta.dimensions_xyz};
  draw();announce();return;
 }
 density=new Uint8Array(await(await fetchData(meta.density_file)).arrayBuffer());owners=new Uint8Array(await(await fetchData(meta.owners_file)).arrayBuffer());
 if(density.length!==meta.density_bytes||owners.length!==density.length)throw Error('Payload length mismatch');
 const cells=new Set(),dims=meta.dimensions_xyz,b=meta.brick_size;
 if(![8,16,32].includes(b)||dims.length!==3||dims.some(n=>!Number.isSafeInteger(n)||n<=0))throw Error('Invalid dimensions');
 for(const r of meta.bricks){const key=r.cell_xyz.join(',');if(cells.has(key))throw Error('Duplicate brick cell');cells.add(key);
  if(r.origin_xyz.length!==3||r.dimensions_xyz.length!==3||r.cell_xyz.length!==3||[...r.origin_xyz,...r.cell_xyz,r.offset,r.bytes].some(n=>!Number.isSafeInteger(n)||n<0)||r.dimensions_xyz.some(n=>!Number.isSafeInteger(n)||n<=0))throw Error('Invalid brick');
  if(r.dimensions_xyz.reduce((a,b)=>a*b,1)!==r.bytes||r.offset+r.bytes>density.length||r.origin_xyz.some((v,k)=>v<r.cell_xyz[k]*b||v+r.dimensions_xyz[k]>Math.min(dims[k],(r.cell_xyz[k]+1)*b)))throw Error('Invalid bounds or offsets');
 }
 $('selection').textContent=`${meta.selected_voxels.toLocaleString()} selected voxels. Groups are intensity candidates, not anatomical labels. Changing display cutoff cannot restore discarded data.`;
 pack(meta.groups.map(g=>g.id));announce();$('status').textContent='Ready. Compare verifies matching images and measures each logical group.';
});
