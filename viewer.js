const $ = id => document.getElementById(id);
const canvas = $('canvas');
const gl = canvas.getContext('webgl2', {antialias: false, preserveDrawingBuffer: true});
const status = text => { $('status').textContent = text; };
if (!gl) { status('WebGL2 is required.'); throw Error('WebGL2 unavailable'); }
const maxVolumes = Math.min(15, gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS));
const ext = gl.getExtension('EXT_disjoint_timer_query_webgl2');
const vertex = `#version 300 es
layout(location=0) in vec2 position;
void main(){gl_Position=vec4(position,0,1);}`;
const fragment = `#version 300 es
precision highp float;
precision highp sampler3D;
out vec4 color;
uniform sampler3D volumes[${maxVolumes}];
uniform vec3 origins[${maxVolumes}], extents[${maxVolumes}], spacings[${maxVolumes}], dimensions[${maxVolumes}];
uniform int enabled[${maxVolumes}], count;
uniform vec3 fullDims;
uniform vec2 resolution, angles;
uniform float distanceScale, stepSize, cutoff;
float density(int i,vec3 p){
 vec3 uv=(floor((p-origins[i])/spacings[i])+0.5)/dimensions[i];
 ${Array.from({length:maxVolumes},(_,i)=>`if(i==${i}) return texture(volumes[${i}],uv).r;`).join('\n')}
 return 0.;
}
vec3 rotate(vec3 p){
 float cx=cos(angles.x),sx=sin(angles.x),cy=cos(angles.y),sy=sin(angles.y);
 p=vec3(p.x,cx*p.y-sx*p.z,sx*p.y+cx*p.z);
 return vec3(cy*p.x+sy*p.z,p.y,-sy*p.x+cy*p.z);
}
void main(){
 vec2 uv=(gl_FragCoord.xy/resolution*2.-1.); uv.x*=resolution.x/resolution.y;
 float scale=max(fullDims.x,max(fullDims.y,fullDims.z));
 vec3 ro=fullDims*.5+rotate(vec3(0,0,-scale*distanceScale));
 vec3 rd=rotate(normalize(vec3(uv,1.5)));
 // Preserve sign for nearly parallel rays, including exact zero.
 vec3 safeDir=vec3(rd.x<0.?-1.:1.,rd.y<0.?-1.:1.,rd.z<0.?-1.:1.)*max(abs(rd),vec3(1e-7));
 vec3 a=(vec3(0)-ro)/safeDir,b=(fullDims-ro)/safeDir;
 vec3 nearV=min(a,b),farV=max(a,b);
 float nearT=max(0.,max(nearV.x,max(nearV.y,nearV.z)));
 float farT=min(farV.x,min(farV.y,farV.z));
 vec3 rgb=vec3(0);float remaining=1.;
 for(int s=0;s<8192;s++){
  float t=nearT+(float(s)+.5)*stepSize;
  if(t>=farT || remaining<.005)break;
  vec3 p=ro+rd*t;float d=0.;
  for(int i=0;i<${maxVolumes};i++){
   if(i>=count)break;
   if(enabled[i]==0)continue;
   if(all(greaterThanEqual(p,origins[i]))&&all(lessThan(p,origins[i]+extents[i])))d=max(d,density(i,p));
  }
  if(d>cutoff){
   float alpha=1.-exp(-d*stepSize*.12);
   vec3 tint=mix(vec3(.22,.5,.7),vec3(1.,.9,.72),d);
   rgb+=remaining*alpha*tint;remaining*=1.-alpha;
  }
 }
 color=vec4(pow(rgb+remaining*vec3(.025,.035,.05),vec3(1./2.2)),1.);
}`;
function shader(type, source) {
 const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);
 if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;
}
const program=gl.createProgram();
try {
 for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){
  const s=shader(type,source);gl.attachShader(program,s);gl.deleteShader(s);
 }
 gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
} catch(error){status(error.message);throw error;}
gl.useProgram(program);
const locations=new Map();
function loc(name){if(!locations.has(name))locations.set(name,gl.getUniformLocation(program,name));return locations.get(name);}
const vao=gl.createVertexArray();gl.bindVertexArray(vao);
const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
const emptyTexture=gl.createTexture();
gl.bindTexture(gl.TEXTURE_3D,emptyTexture);
gl.texImage3D(gl.TEXTURE_3D,0,gl.R8,1,1,1,0,gl.RED,gl.UNSIGNED_BYTE,new Uint8Array([0]));
gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);
gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
let textures=[], meta=null, visible=[], loading=false, measuring=false;
let lastMeasurement=null;
const base=new URL(new URLSearchParams(location.search).get('base') || './experiments/current/',location.href);
const customManifest=new URLSearchParams(location.search).get('manifest');
async function fetchOK(url){const response=await fetch(url);if(!response.ok)throw Error(`${response.status}: ${url}`);return response;}
function validate(m){
 const vector=(v)=>Array.isArray(v)&&v.length===3&&v.every(n=>Number.isSafeInteger(n)&&n>0);
 if(m.schema_version!==2||m.dtype!=='uint8'||!vector(m.dimensions_xyz)||!Array.isArray(m.components)||m.components.length>maxVolumes)throw Error('Unsupported metadata or too many components');
 for(const c of m.components){
  if(!vector(c.dimensions_xyz)||!vector(c.extent_xyz)||!vector(c.spacing_xyz)||!Array.isArray(c.origin_xyz)||c.origin_xyz.length!==3||c.origin_xyz.some(n=>!Number.isSafeInteger(n)||n<0))throw Error('Invalid component coordinates');
  if(c.dimensions_xyz.some(n=>n>gl.getParameter(gl.MAX_3D_TEXTURE_SIZE)))throw Error('Component exceeds device 3D texture limit');
  if(c.origin_xyz.some((n,i)=>n+c.extent_xyz[i]>m.dimensions_xyz[i])||c.dimensions_xyz.some((n,i)=>n!==Math.ceil(c.extent_xyz[i]/c.spacing_xyz[i])))throw Error('Inconsistent component extent');
 }
}
async function load(){
 if(loading||measuring)return;
 loading=true;$('dataset').disabled=true;status('Loading…');
 const nextTextures=[];
 try{
  const manifest=customManifest?new URL(customManifest,location.href):new URL(`${$('dataset').value}/metadata.json`,base);
  const next=await (await fetchOK(manifest)).json();validate(next);
  for(const c of next.components){
   const data=new Uint8Array(await (await fetchOK(new URL(c.file,manifest))).arrayBuffer());
   if(data.length!==c.dimensions_xyz.reduce((a,b)=>a*b,1))throw Error(`Wrong byte length: ${c.file}`);
   const tex=gl.createTexture();nextTextures.push(tex);gl.bindTexture(gl.TEXTURE_3D,tex);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);
   gl.texImage3D(gl.TEXTURE_3D,0,gl.R8,...c.dimensions_xyz,0,gl.RED,gl.UNSIGNED_BYTE,data);
   for(const axis of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T,gl.TEXTURE_WRAP_R])gl.texParameteri(gl.TEXTURE_3D,axis,gl.CLAMP_TO_EDGE);
   gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
   if(gl.getError()!==gl.NO_ERROR)throw Error(`Texture upload failed: ${c.file}`);
  }
  for(const tex of textures)gl.deleteTexture(tex);textures=nextTextures;meta=next;visible=next.components.map(()=>1);
  $('components').replaceChildren();
  next.components.forEach((c,i)=>{const label=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.checked=true;input.onchange=()=>{visible[i]=+input.checked;draw();};label.append(input,document.createTextNode(` Component ${i+1}`));$('components').append(label);});
  if(customManifest){
   const option=document.createElement('option');option.value='custom';option.textContent=`Custom · ${next.parameters.mode} · ${next.parameters.downsample}×`;
   $('dataset').replaceChildren(option);$('dataset').disabled=true;
  }
  status(`${next.components.length} components · ${(next.output_bytes/1048576).toFixed(2)} MiB\n${next.dimensions_xyz.join(' × ')} original voxels`);
  draw();
 }catch(error){for(const tex of nextTextures)gl.deleteTexture(tex);status(`${error.message}\nGenerate experiments first; see README.`);}
 finally{loading=false;$('dataset').disabled=!!customManifest;}
}
function draw(){
 if(!meta)return;
 if(Math.ceil(Math.hypot(...meta.dimensions_xyz)/+$('step').value)>8192){status('Ray exceeds 8192 steps; increase step size.');return;}
 const width=Math.round(canvas.clientWidth*Math.min(devicePixelRatio,2)),height=Math.round(canvas.clientHeight*Math.min(devicePixelRatio,2));
 if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
 gl.viewport(0,0,width,height);gl.useProgram(program);gl.bindVertexArray(vao);
 gl.uniform2f(loc('resolution'),width,height);gl.uniform3fv(loc('fullDims'),meta.dimensions_xyz);
 gl.uniform2f(loc('angles'),+$('rx').value*Math.PI/180,+$('ry').value*Math.PI/180);
 gl.uniform1f(loc('distanceScale'),+$('zoom').value);gl.uniform1f(loc('stepSize'),+$('step').value);gl.uniform1f(loc('cutoff'),+$('cutoff').value/255);
 gl.uniform1i(loc('count'),textures.length);
 gl.uniform1iv(loc('volumes[0]'),Int32Array.from({length:maxVolumes},(_,i)=>i));
 // Every declared sampler references a valid texture, even when its branch is unused.
 for(let i=0;i<maxVolumes;i++){gl.activeTexture(gl.TEXTURE0+i);gl.bindTexture(gl.TEXTURE_3D,textures[i]||textures[0]||emptyTexture);}
 meta.components.forEach((c,i)=>{
  for(const [name,field] of [['origins','origin_xyz'],['extents','extent_xyz'],['spacings','spacing_xyz'],['dimensions','dimensions_xyz']])gl.uniform3fv(loc(`${name}[${i}]`),c[field]);
  gl.uniform1i(loc(`enabled[${i}]`),visible[i]);
 });
 gl.drawArrays(gl.TRIANGLES,0,3);
}
const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
async function measure(){
 if(!meta||loading||measuring)return;
 measuring=true;const controls=[...document.querySelectorAll('input,select,button')];const disabled=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);
 status('Measuring 60 frames…');
 try{
  for(let i=0;i<10;i++){await frame();draw();}gl.finish();
  const gpu=[], intervals=[];
  for(let i=0;i<60;i++){
   const begin=performance.now();await frame();
   let query=null;
   if(ext){query=gl.createQuery();gl.beginQuery(ext.TIME_ELAPSED_EXT,query);}
   draw();
   if(query)gl.endQuery(ext.TIME_ELAPSED_EXT);
   gl.finish();intervals.push(performance.now()-begin);
   if(query){
    try{
     const deadline=performance.now()+5000;
     while(!gl.getQueryParameter(query,gl.QUERY_RESULT_AVAILABLE)){if(performance.now()>deadline)throw Error('GPU query timed out');await frame();}
     if(!gl.getParameter(ext.GPU_DISJOINT_EXT))gpu.push(gl.getQueryParameter(query,gl.QUERY_RESULT)/1e6);
    }finally{gl.deleteQuery(query);}
   }
  }
  const median=a=>{if(!a.length)return null;const b=[...a].sort((a,b)=>a-b);return (b[Math.floor((b.length-1)/2)]+b[Math.floor(b.length/2)])/2;};
  lastMeasurement={mode:meta.parameters.mode,downsample:meta.parameters.downsample,visible:[...visible],resolution:[canvas.width,canvas.height],camera:[+$('rx').value,+$('ry').value,+$('zoom').value],step:+$('step').value,cutoff:+$('cutoff').value,gpu_median_ms:median(gpu),gpu_valid_samples:gpu.length,raf_and_finish_median_ms:median(intervals),user_agent:navigator.userAgent,renderer:gl.getParameter(gl.RENDERER)};
  status(JSON.stringify(lastMeasurement,null,2));return lastMeasurement;
 }finally{measuring=false;controls.forEach((c,i)=>c.disabled=disabled[i]);}
}
$('dataset').onchange=load;
for(const id of ['rx','ry','zoom','step','cutoff'])$(id).oninput=draw;
$('measure').onclick=()=>measure().catch(e=>status(e.message));
window.addEventListener('resize',draw);
// Exposed for reproducible browser QA and copying measurement JSON.
window.volumeStudy={load,draw,measure,get metadata(){return meta;},get measurement(){return lastMeasurement;},get glError(){return gl.getError();}};
await load();
