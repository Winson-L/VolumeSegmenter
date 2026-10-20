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
uniform int count;
uniform vec3 clipMin, clipMax;
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
 float gridStart=max(0.,max(nearV.x,max(nearV.y,nearV.z)));
 float farT=min(farV.x,min(farV.y,farV.z));
 float first=1e30,last=-1e30;
 // Restrict marching to active component intersections. Keep the original
 // sample lattice so ROI and monolithic comparisons sample identical points.
 for(int i=0;i<${maxVolumes};i++){
  if(i>=count)break;
  vec3 lower=max(origins[i],clipMin),upper=min(origins[i]+extents[i],clipMax);
  if(any(greaterThanEqual(lower,upper)))continue;
  vec3 c=(lower-ro)/safeDir,e=(upper-ro)/safeDir;
  vec3 n=min(c,e),f=max(c,e);
  float enter=max(0.,max(n.x,max(n.y,n.z))),exitT=min(f.x,min(f.y,f.z));
  if(exitT>=enter){first=min(first,enter);last=max(last,exitT);}
 }
 float offset=max(0.,ceil((first-gridStart)/stepSize-.5));
 float nearT=gridStart+offset*stepSize;
 farT=min(farT,last);
 vec3 rgb=vec3(0);float remaining=1.;
 for(int s=0;s<8192;s++){
  float t=nearT+(float(s)+.5)*stepSize;
  if(t>=farT || remaining<.005)break;
  vec3 p=ro+rd*t;float d=0.;
  for(int i=0;i<${maxVolumes};i++){
   if(i>=count)break;

   if(all(greaterThanEqual(p,max(origins[i],clipMin)))&&all(lessThan(p,min(origins[i]+extents[i],clipMax))))d=max(d,density(i,p));
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
let textures = new Map(), meta = null, manifest = null, visible = [];
let loading = false, measuring = false, suite = null, clip = null;
let fixedResolution = null;
const study = new URLSearchParams(location.search).get('study') === 'foreground';
const base = new URL(new URLSearchParams(location.search).get('base') || (study ? './experiments/foreground/' : './experiments/spatial/'), location.href);
if (study) {
    const variants = [['original', 'Original'], ['threshold', 'Automatic threshold only'],
        ['conservative', 'Conservative · threshold 30 + region filter'],
        ['focused', 'Focused · threshold 60 + region filter'],
        ['opening', 'Opening · automatic threshold'], ['legacy_cleanup', 'Legacy erosion · automatic threshold'],
        ['aggressive', 'Aggressive · threshold 90 + region filter'],
        ['focused_decimated', 'Focused · 2× decimation control']];
    $('dataset').replaceChildren(...variants.map(([value, text]) => {
        const option = document.createElement('option'); option.value = value; option.textContent = text;
        option.selected = value === 'focused'; return option;
    }));
}
const customManifest = new URLSearchParams(location.search).get('manifest');
const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
const median = values => {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    return (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2;
};
function bytes(index) { return meta.components[index].dimensions_xyz.reduce((a, b) => a * b, 1); }
function accounting() {
    return {
        resident_components: [...textures.keys()].map(i => i + 1),
        visible_components: visible.flatMap((v, i) => v ? [i + 1] : []),
        resident_texture_payload_bytes: [...textures.keys()].reduce((sum, i) => sum + bytes(i), 0),
        visible_texture_payload_bytes: visible.reduce((sum, v, i) => sum + (v ? bytes(i) : 0), 0),
        dummy_texture_payload_bytes: 1,
        total_gpu_allocation_bytes: null
    };
}
function updateMemory() {
    if (!meta) return;
    const a = accounting();
    $('memory').textContent = `Resident: ${a.resident_components.length} textures · ${(a.resident_texture_payload_bytes / 1048576).toFixed(2)} MiB payload. Visible: ${a.visible_components.length}.`;
}
function lock(on) {
    for (const element of document.querySelectorAll('input,select,button')) element.disabled = on;
    if (!on) {
        $('dataset').disabled = !!customManifest;
        $('compare').disabled = !!customManifest;
        $('download').disabled = !suite;
    }
}
async function fetchOK(url) {
    const response = await fetch(url);
    if (!response.ok) throw Error(`${response.status}: ${url}`);
    return response;
}
function validate(m) {
    const vector = v => Array.isArray(v) && v.length === 3 && v.every(n => Number.isSafeInteger(n) && n > 0);
    if (m.schema_version !== 2 || m.dtype !== 'uint8' || !vector(m.dimensions_xyz) || !Array.isArray(m.components) || m.components.length > maxVolumes) throw Error('Unsupported metadata or too many components');
    for (const c of m.components) {
        if (!vector(c.dimensions_xyz) || !vector(c.extent_xyz) || !vector(c.spacing_xyz) || !Array.isArray(c.origin_xyz) || c.origin_xyz.length !== 3 || c.origin_xyz.some(n => !Number.isSafeInteger(n) || n < 0)) throw Error('Invalid component coordinates');
        if (c.dimensions_xyz.some(n => n > gl.getParameter(gl.MAX_3D_TEXTURE_SIZE))) throw Error('Component exceeds device 3D texture limit');
        if (c.origin_xyz.some((n, i) => n + c.extent_xyz[i] > m.dimensions_xyz[i]) || c.dimensions_xyz.some((n, i) => n !== Math.ceil(c.extent_xyz[i] / c.spacing_xyz[i]))) throw Error('Inconsistent component extent');
    }
}
function release(index) {
    const texture = textures.get(index);
    if (texture) { gl.deleteTexture(texture); textures.delete(index); }
}
async function upload(index) {
    if (textures.has(index)) return;
    const c = meta.components[index];
    const data = new Uint8Array(await (await fetchOK(new URL(c.file, manifest))).arrayBuffer());
    if (data.byteLength !== bytes(index)) throw Error(`Wrong byte length: ${c.file}`);
    const texture = gl.createTexture();
    try {
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_3D, texture);
        gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, ...c.dimensions_xyz, 0, gl.RED, gl.UNSIGNED_BYTE, data);
        for (const axis of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(gl.TEXTURE_3D, axis, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        if (gl.getError() !== gl.NO_ERROR) throw Error(`Texture upload failed: ${c.file}`);
        textures.set(index, texture);
    } catch (error) { gl.deleteTexture(texture); throw error; }
    // No application-level CPU copy is retained after upload.
}
async function select(indices, evict = true) {
    const chosen = new Set(indices);
    visible = meta.components.map((_, i) => +chosen.has(i));
    if (evict) for (const index of [...textures.keys()]) if (!chosen.has(index)) release(index);
    for (const index of indices) await upload(index);
    updateMemory();
    draw(); // Rebind every unit, releasing any stale sampler references.
}
function controls() {
    $('components').replaceChildren();
    meta.components.forEach((c, i) => {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'checkbox'; input.checked = !!visible[i];
        input.onchange = () => action(async () => {
            const selected = visible.flatMap((v, j) => (j === i ? input.checked : v) ? [j] : []);
            await select(selected, $('release').checked);
            controls();
        });
        const solo = document.createElement('button');
        solo.textContent = `Only ${i + 1}`;
        solo.style.width = 'auto';
        solo.onclick = () => action(async () => {
            await select([i], $('release').checked); controls(); status(`Showing block ${i + 1}`);
        });
        label.append(input, document.createTextNode(` Block ${i + 1} · ${(bytes(i) / 1048576).toFixed(2)} MiB `), solo);
        $('components').append(label);
    });
}
async function loadVariant(name, indices = null, keepAll = false) {
    // Evict previous dataset BEFORE uploading the replacement to bound residency.
    for (const i of [...textures.keys()]) release(i);
    meta = null;
    manifest = customManifest ? new URL(customManifest, location.href) : new URL(`${name}/metadata.json`, base);
    const next = await (await fetchOK(manifest)).json(); validate(next); meta = next; clip = null;
    visible = next.components.map(() => 0);
    if (keepAll) for (let i = 0; i < next.components.length; i++) await upload(i);
    await select(indices ?? next.components.map((_, i) => i), !keepAll);
    controls();
    if (customManifest) {
        const option = document.createElement('option'); option.value = 'custom';
        option.textContent = `Custom · ${next.parameters.mode} · ${next.parameters.downsample}×`;
        $('dataset').replaceChildren(option);
    } else $('dataset').value = name;
    const survival = next.foreground_metrics?.intensity_survival?.['60'];
    $('selection').textContent = next.parameters.cleanup && next.parameters.cleanup !== 'none'
        ? `Threshold ${next.parameters.threshold}; ${next.parameters.cleanup}; min region ${next.parameters.min_region_voxels} voxels. Removed ${survival?.removed_voxels ?? '?'} original voxels above intensity 60. This is a selection heuristic, not an anatomical guarantee.`
        : `Threshold ${next.parameters.threshold}; no structural cleanup.`;
    status(`${next.components.length} blocks · ${(next.output_bytes / 1048576).toFixed(2)} MiB total payload`);
}
function draw() {
    if (!meta) return;
    if (Math.ceil(Math.hypot(...meta.dimensions_xyz) / +$('step').value) > 8192) throw Error('Ray exceeds 8192 steps; increase step size.');
    const [width, height] = fixedResolution || [Math.round(canvas.clientWidth * Math.min(devicePixelRatio, 2)), Math.round(canvas.clientHeight * Math.min(devicePixelRatio, 2))];
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    gl.viewport(0, 0, width, height); gl.useProgram(program); gl.bindVertexArray(vao);
    gl.uniform2f(loc('resolution'), width, height); gl.uniform3fv(loc('fullDims'), meta.dimensions_xyz);
    gl.uniform3fv(loc('clipMin'), clip ? clip.origin_xyz : [0, 0, 0]);
    gl.uniform3fv(loc('clipMax'), clip ? clip.origin_xyz.map((n, i) => n + clip.extent_xyz[i]) : meta.dimensions_xyz);
    gl.uniform2f(loc('angles'), +$('rx').value * Math.PI / 180, +$('ry').value * Math.PI / 180);
    gl.uniform1f(loc('distanceScale'), +$('zoom').value); gl.uniform1f(loc('stepSize'), +$('step').value); gl.uniform1f(loc('cutoff'), +$('cutoff').value / 255);
    const active = visible.flatMap((v, i) => v && textures.has(i) ? [i] : []);
    gl.uniform1i(loc('count'), active.length);
    gl.uniform1iv(loc('volumes[0]'), Int32Array.from({ length: maxVolumes }, (_, i) => i));
    for (let slot = 0; slot < maxVolumes; slot++) {
        gl.activeTexture(gl.TEXTURE0 + slot);
        gl.bindTexture(gl.TEXTURE_3D, slot < active.length ? textures.get(active[slot]) : emptyTexture);
        if (slot >= active.length) continue;
        const c = meta.components[active[slot]];
        for (const [name, field] of [['origins', 'origin_xyz'], ['extents', 'extent_xyz'], ['spacings', 'spacing_xyz'], ['dimensions', 'dimensions_xyz']]) gl.uniform3fv(loc(`${name}[${slot}]`), c[field]);
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
}
async function measureFrames(samples = 60) {
    for (let i = 0; i < 5; i++) { await frame(); draw(); }
    const gpu = [], wall = [];
    for (let i = 0; i < samples; i++) {
        await frame();
        const start = performance.now();
        let query = null;
        if (ext) { query = gl.createQuery(); gl.beginQuery(ext.TIME_ELAPSED_EXT, query); }
        draw();
        if (query) gl.endQuery(ext.TIME_ELAPSED_EXT);
        gl.finish(); wall.push(performance.now() - start);
        if (query) {
            try {
                const deadline = performance.now() + 5000;
                while (!gl.getQueryParameter(query, gl.QUERY_RESULT_AVAILABLE)) {
                    if (performance.now() > deadline) throw Error('GPU query timed out');
                    await frame();
                }
                if (!gl.getParameter(ext.GPU_DISJOINT_EXT)) gpu.push(gl.getQueryParameter(query, gl.QUERY_RESULT) / 1e6);
            } finally { gl.deleteQuery(query); }
        }
    }
    return { ...accounting(), mode: meta.parameters.mode, downsample: meta.parameters.downsample,
        strategy: meta.parameters.strategy, gpu_median_ms: median(gpu), gpu_samples_ms: gpu,
        cpu_submit_and_finish_median_ms: median(wall), resolution: [canvas.width, canvas.height],
        camera: [+$('rx').value, +$('ry').value, +$('zoom').value], step: +$('step').value, cutoff: +$('cutoff').value };
}
async function action(fn) {
    if (loading || measuring) return;
    loading = true; lock(true);
    try { await fn(); } catch (error) { status(error.message); }
    finally { loading = false; lock(false); }
}
async function compare() {
    suite = null; $('download').disabled = true; $('report').textContent = '';
    const partition = await (await fetchOK(new URL(`${study ? 'focused' : 'partition'}/metadata.json`, base))).json();
    validate(partition);
    if (partition.parameters.downsample !== 1 || partition.parameters.strategy !== 'spatial') throw Error('Comparison requires full-resolution spatial partitions. Regenerate benchmark output.');
    const cases = [ {name: 'original', dataset: 'original'}, {name: 'all_blocks', dataset: 'partition'},
        ...partition.components.map((c, i) => ({name: `block_${i + 1}`, dataset: 'partition', indices: [i]})),
        {name: 'block_1_hidden_others_resident', dataset: 'partition', indices: [0], keepAll: true},
        {name: 'monolith_same_roi_1', dataset: 'crop', roi: partition.components[0]} ];
    if (study) {
        cases.splice(0, cases.length, {name: 'original', dataset: 'original'});
        for (const name of ['threshold', 'conservative', 'focused', 'opening', 'legacy_cleanup', 'aggressive', 'focused_decimated']) {
            const m = await (await fetchOK(new URL(`${name}/metadata.json`, base))).json(); validate(m);
            cases.push({name: `${name}/all`, dataset: name});
            for (let i = 0; i < m.components.length; i++) {
                cases.push({name: `${name}/block_${i + 1}`, dataset: name, indices: [i]});
                if (m.parameters.downsample === 1) cases.push({name: `${name}/monolith_roi_${i + 1}`, dataset: `${name}_monolith`, roi: m.components[i]});
            }
            cases.push({name: `${name}/hidden_others_resident`, dataset: name, indices: [0], keepAll: true});
            if (m.parameters.downsample === 1) cases.push({name: `${name}/monolith_all`, dataset: `${name}_monolith`});
        }
    }
    const runs = [], order = [];
    fixedResolution = [1280, 720];
    const old = ['rx', 'ry', 'zoom', 'step', 'cutoff'].map(id => $(id).value);
    [90, 0, 1.8, 1, 60].forEach((v, i) => { $(['rx', 'ry', 'zoom', 'step', 'cutoff'][i]).value = v; });
    let random = 42;
    try {
        for (let round = 0; round < 3; round++) {
            const shuffled = [...cases];
            for (let i = shuffled.length - 1; i > 0; i--) {
                random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
                const j = random % (i + 1); [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }
            for (const c of shuffled) {
                status(`Round ${round + 1}/3 · ${c.name}`);
                await loadVariant(c.dataset, c.indices ?? null, c.keepAll ?? false);
                // Recreated component controls must remain locked during the suite.
                lock(true); clip = c.roi || null;
                status(`Round ${round + 1}/3 · ${c.name}`);
                const result = await measureFrames(20);
                runs.push({case: c.name, dataset: c.dataset, input_sha256: meta.input_sha256, parameters: meta.parameters, components: meta.components, roi: c.roi || null, round: round + 1, ...result}); order.push(c.name);
            }
        }
        const results = cases.map(c => {
            const group = runs.filter(r => r.case === c.name);
            const samples = group.flatMap(r => r.gpu_samples_ms);
            return {case: c.name, resident_texture_payload_bytes: group[0].resident_texture_payload_bytes,
                visible_texture_payload_bytes: group[0].visible_texture_payload_bytes,
                gpu_median_ms: median(samples), round_medians_ms: group.map(r => r.gpu_median_ms), valid_gpu_samples: samples.length};
        });
        suite = {schema_version: 1, input_sha256: partition.input_sha256, partition_components: partition.components,
            environment: {user_agent: navigator.userAgent, renderer: gl.getParameter(gl.RENDERER)},
            methodology: 'Three seeded-shuffled rounds, five warmups and 20 timed frames per case per round; fixed 1280x720, camera 90/0/1.8, step 1, cutoff 60. Upload and network time excluded. Texture payload is R8 voxel bytes, NOT measured total VRAM. Single blocks show less content; Monolith ROI cases use the identical selected full-resolution data and block bounds; decimated cases have no matched ROI control. CPU buffers are not cached by this app. Driver memory reclamation may be deferred.',
            results, order, runs};
        $('report').textContent = JSON.stringify(suite, null, 2);
        status(JSON.stringify({results}, null, 2));
    } finally {
        fixedResolution = null; clip = null;
        old.forEach((value, i) => { $(['rx', 'ry', 'zoom', 'step', 'cutoff'][i]).value = value; });
        const report = suite;
        await loadVariant(study ? 'focused' : 'partition');
        if (report) status(JSON.stringify({results: report.results}, null, 2));
    }
}
$('dataset').onchange = () => action(() => loadVariant($('dataset').value));
$('all').onclick = () => action(async () => { await select(meta.components.map((_, i) => i)); controls(); status('Showing all blocks'); });
$('release').onchange = () => action(async () => { await select(visible.flatMap((v, i) => v ? [i] : []), $('release').checked); });
for (const id of ['rx', 'ry', 'zoom', 'step', 'cutoff']) $(id).oninput = () => { try { draw(); } catch (e) { status(e.message); } };
$('measure').onclick = () => action(async () => { const result = await measureFrames(); status(JSON.stringify(result, null, 2)); });
$('compare').onclick = () => action(compare);
$('download').onclick = () => {
    if (!suite) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(suite, null, 2)], {type: 'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = study ? 'foreground-render-comparison.json' : 'spatial-render-comparison.json'; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener('resize', () => { if (!loading) draw(); });
window.volumeStudy = {get report() { return suite; }};
await action(() => loadVariant($('dataset').value));
