// The robot of the Enter screen in 3D (1.6.76): one canvas, one fragment shader that draws the robot of enter.js from distances, no library and no model file.
// BOT3D.make(box, {boss}) puts the canvas in `box` and returns {draw, colours}; `boss` adds the super agent's gear (1.8.1), in `--sa-gear`, after the skin `view.skin` given to `draw` (pet.js); null when the browser has no WebGL, and enter.js keeps its flat robot. It costs nothing while the picture does not change.
"use strict";

const BOT3D = (function () {
  const VERTEX = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  const FRAGMENT = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 size;
uniform mat3 turn, nod;
uniform vec2 arm, look;
uniform float blink, glow, skin;
uniform vec3 cBody, cHead, cLine, cVisor, cLight, cGear;
const float CAMERA = 260., HIGH = 115., MIDDLE = 4.5, FAR = 330.;
const vec3 NECK = vec3(0., -5., 0.), SHOULDER = vec3(28., -13., 0.);

float box(vec3 p, vec3 half_, float r) { vec3 q = abs(p) - half_ + r; return length(max(q, 0.)) + min(max(q.x, max(q.y, q.z)), 0.) - r; }
float rod(vec3 p, vec3 a, vec3 b, float r) { vec3 pa = p - a, ba = b - a; return length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0., 1.)) - r; }
float plate(vec3 p, vec2 half_, float corner, float depth) {
  vec2 q = abs(p.xy) - half_ + corner;
  vec2 w = vec2(length(max(q, 0.)) + min(max(q.x, q.y), 0.) - corner, abs(p.z) - depth);
  return min(max(w.x, w.y), 0.) + length(max(w, 0.)) - .6;
}
vec3 inHead(vec3 q) { return nod * (q - NECK) + NECK; }

// The distance to the robot, and which part: 1 body, 2 head, 3 visor, 4 line, 5 bulb, 6 gear (BOSS only, in cGear), 7 neon frame (in cLine).
vec2 world(vec3 p) {
  vec3 q = turn * p, h = inHead(q);
  vec2 best = vec2(box(q - vec3(0., -24., 0.), vec3(20., 21., 15.), 13.), 1.);
  best.x = min(best.x, rod(q, vec3(-28., -14., 0.), vec3(-28., -30., 0.), 5.));
  vec3 a = q - SHOULDER;
  a.xy = mat2(arm.x, arm.y, -arm.y, arm.x) * a.xy;
  best.x = min(best.x, rod(a, vec3(0., -1., 0.), vec3(0., -17., 0.), 5.));
  float d = box(h - vec3(0., 16., 0.), vec3(26., 21., 18.), 15.);
  if (d < best.x) best = vec2(d, 2.);
  d = plate(h - vec3(0., 16., 17.6), vec2(19., 11.), 9., 1.6);
  if (d < best.x) best = vec2(d, 3.);
  d = rod(h, vec3(0., 36., 0.), vec3(0., 44., 0.), 1.2);
  if (d < best.x) best = vec2(d, 4.);
  d = length(h - vec3(0., 47., 0.)) - 3.6;
  if (d < best.x) best = vec2(d, 5.);
#ifdef BOSS
  // the super agent (1.8.1): its gear depends on the skin (skin, pet.js): 0 commander, 1 ninja, 2 pilot, 3 mecha, 4 neon
  vec3 e = vec3(abs(h.x), h.y, h.z);
  if (skin < .5) {  // a headset that hugs the head, a microphone at the mouth, a ring of light round the bulb
    vec3 b = h - vec3(0., 15., -8.);
    vec2 hoop = vec2(b.x, b.y * 1.2);
    d = max((length(vec2(length(hoop) - 29., b.z)) - 2.4) * .8, -b.y);
    if (d < best.x) best = vec2(d, 4.);
    d = rod(e, vec3(24., 14., -3.), vec3(30.5, 14., -3.), 7.5);
    if (d < best.x) best = vec2(d, 6.);
    d = min(rod(h, vec3(-30., 9., 3.), vec3(-27., 3., 16.), 1.4), rod(h, vec3(-27., 3., 16.), vec3(-14., 1., 22.), 1.4));
    if (d < best.x) best = vec2(d, 4.);
    d = length(h - vec3(-12.5, 1., 22.5)) - 2.8;
    if (d < best.x) best = vec2(d, 5.);
    vec3 r = h - vec3(0., 47., 0.);
    d = length(vec2(length(r.xz) - 7., r.y)) - 1.;
    if (d < best.x) best = vec2(d, 5.);
  } else if (skin < 1.5) {  // a headband with its knot and two tails at the side
    float head = box(h - vec3(0., 16., 0.), vec3(26., 21., 18.), 15.);
    d = max(head - 1.8, abs(h.y - 30.) - 3.2);
    d = min(d, length(h - vec3(-27., 29., -5.)) - 3.6);
    d = min(d, min(rod(h, vec3(-28., 29., -6.), vec3(-39., 21., -10.), 1.7), rod(h, vec3(-28., 28., -5.), vec3(-36., 14., -4.), 1.7)));
    if (d < best.x) best = vec2(d, 6.);
  } else if (skin < 2.5) {  // goggles pushed up on the forehead, on a strap
    float head = box(h - vec3(0., 16., 0.), vec3(26., 21., 18.), 15.);
    d = max(head - 1., abs(h.y - 31.) - 1.6);
    if (d < best.x) best = vec2(d, 4.);
    d = rod(e, vec3(9.5, 31., 12.), vec3(9.5, 31., 19.), 6.2);
    if (d < best.x) best = vec2(d, 6.);
    d = rod(e, vec3(9.5, 31., 19.), vec3(9.5, 31., 20.2), 4.4);
    if (d < best.x) best = vec2(d, 5.);
  } else if (skin < 3.5) {  // a V crest with a gem, and armour on the shoulders
    d = rod(e, vec3(2., 27., 17.), vec3(21., 45., 11.), 1.9);
    if (d < best.x) best = vec2(d, 6.);
    d = length(h - vec3(0., 27., 18.)) - 3.4;
    if (d < best.x) best = vec2(d, 5.);
    d = box(vec3(abs(q.x), q.y, q.z) - vec3(27., -8., 0.), vec3(8., 4.5, 9.), 3.5);
    if (d < best.x) best = vec2(d, 6.);
  } else {  // a crown of spikes that fans out over the head, and a frame of light round the visor, both glowing
    vec3 c = e - vec3(0., 32., 2.);
    d = min(min(rod(c, vec3(5., 0., 0.), vec3(9., 15., 2.), 2.1), rod(c, vec3(12., -1., 0.), vec3(21., 11., 1.), 2.1)), rod(c, vec3(18., -4., 0.), vec3(30., 4., 0.), 1.9));
    if (d < best.x) best = vec2(d, 6.);
    vec3 v = h - vec3(0., 16., 18.);
    d = max(plate(v, vec2(22., 14.), 11., 1.), -plate(v, vec2(19.5, 11.5), 9., 4.));
    if (d < best.x) best = vec2(d, 7.);
  }
#endif
  return best;
}
vec3 normalAt(vec3 p) {
  const vec2 e = vec2(.06, -.06);
  return normalize(e.xyy * world(p + e.xyy).x + e.yyx * world(p + e.yyx).x + e.yxy * world(p + e.yxy).x + e.xxx * world(p + e.xxx).x);
}
void main() {
  vec2 uv = (gl_FragCoord.xy - size * .5) / size.y * HIGH;
  vec3 from = vec3(0., MIDDLE, CAMERA), ray = normalize(vec3(uv.x, uv.y + MIDDLE, 0.) - from);
  float centre = dot(-from, ray), gap = 3600. - (dot(from, from) - centre * centre);  // a ball round the robot: most of the canvas stops here
  if (gap < 0.) { gl_FragColor = vec4(0.); return; }
  float t = centre - sqrt(gap), nearest = 99.;
  vec2 hit = vec2(0.);
  for (int i = 0; i < 64; i++) {
    hit = world(from + ray * t);
    nearest = min(nearest, hit.x);
    if (hit.x < .03 || t > FAR) break;
    t += hit.x;
  }
  float pixel = HIGH / size.y;
  if (hit.x >= .03) {  // no hit: only a soft edge, so the shape has no steps
    float a = 1. - smoothstep(0., pixel * 1.4, nearest);
    gl_FragColor = vec4(cBody * a, a);
    return;
  }
  vec3 p = from + ray * t, n = normalAt(p), q = turn * p, h = inHead(q);
  float part = hit.y, facing = max(dot(n, -ray), 0.);
  vec3 light = normalize(vec3(-.45, .7, .8)), base = part < 1.5 ? cBody : part < 2.5 ? cHead : part < 3.5 ? cVisor : part < 4.5 ? cLine : part < 5.5 ? cLight : part < 6.5 ? cGear : cLine;
  float lit = .62 + .42 * max(dot(n, light), 0.) + .08 * n.y;
  vec3 colour = base * lit + vec3(.32) * pow(max(dot(reflect(-light, n), -ray), 0.), part > 2.5 && part < 3.5 ? 26. : 44.) * (part > 2.5 && part < 3.5 ? 1.2 : .5);
  if (part < 2.5) {  // lacquer, on a dark robot only: it lifts the shape off a dark page, where a light robot needs nothing
    float dark = 1. - smoothstep(.2, .6, cBody.r);
    vec3 r = reflect(ray, n);
    float rim = pow(1. - facing, 3.), sky = smoothstep(-.1, .7, r.y);
    float spot = pow(max(dot(normalize(light - ray), n), 0.), 110.);
    float softbox = smoothstep(.42, .5, r.y) * smoothstep(.92, .8, r.y) * smoothstep(.62, .4, abs(r.x + .15));
    colour += dark * (vec3(.5, .56, .66) * rim * (.3 + .7 * sky) + vec3(1.) * spot * .8 + vec3(.72, .78, .86) * softbox * .16);
  }
  if (part > 4.5 && part < 5.5) colour = cLight;
  if (part > 5.5 && skin > 3.5) { vec3 own = part < 6.5 ? cGear : cLine; colour = mix(colour, own * 1.15, .6) + own * glow * .3 * (1. - facing); }  // neon: the crown and the frame glow
  if (part > 5.5 && part < 6.5 && skin < .5 && abs(h.x) > 30.) colour = mix(colour, cLight, smoothstep(pixel, -pixel, length(h.yz - vec2(14., -3.)) - 2.6));  // the lamp on each ear cup
  if (part > 2.5 && part < 3.5) {  // the eyes are on the visor
    float eye = length(vec2(abs(h.x - look.x) - 8., (h.y - 16. - look.y) / max(blink, .08))) - 4.3;
    colour += cLight * glow * .35 * exp(-max(eye, 0.) * .32);
    colour = mix(colour, cLight, smoothstep(pixel, -pixel, eye));
  }
  if (part < 1.5 && q.z > 0. && abs(q.x) < 20.) {  // the core, on the chest
    float core = length(q.xy - vec2(0., -24.)) - 6.;
    colour = mix(colour, cLight, smoothstep(pixel, -pixel, core));
  }
  gl_FragColor = vec4(colour, 1.);
}`;
  const PROBE = document.createElement("canvas").getContext("2d", {willReadFrequently: true});
  function rgb(text, fallback) {
    if (!PROBE || !text) return fallback;
    PROBE.clearRect(0, 0, 1, 1);
    PROBE.fillStyle = "#000";
    PROBE.fillStyle = text;
    PROBE.fillRect(0, 0, 1, 1);
    const data = PROBE.getImageData(0, 0, 1, 1).data;
    return [data[0] / 255, data[1] / 255, data[2] / 255];
  }
  // Yaw, then pitch, then roll, as what turns a point of the world into a point of the robot. By columns.
  function turning(yaw, pitch, roll) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cx = Math.cos(pitch), sx = Math.sin(pitch), cz = Math.cos(roll), sz = Math.sin(roll);
    return new Float32Array([cy * cz + sy * sx * sz, -cy * sz + sy * sx * cz, sy * cx, cx * sz, cx * cz, -sx, -sy * cz + cy * sx * sz, sy * sz + cy * sx * cz, cy * cx]);
  }

  function make(box, options) {
    const canvas = h("canvas", {class: "en-bot3d"});
    const gl = canvas.getContext("webgl", {alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: "low-power", failIfMajorPerformanceCaveat: true});
    if (!gl) return null;
    const stage = (type, text) => { const shader = gl.createShader(type); gl.shaderSource(shader, text); gl.compileShader(shader); return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null; };
    const vertex = stage(gl.VERTEX_SHADER, VERTEX), fragment = stage(gl.FRAGMENT_SHADER, (options && options.boss ? "#define BOSS 1\n" : "") + FRAGMENT);
    if (!vertex || !fragment) return null;
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.bindAttribLocation(program, 0, "p");
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const at = (name) => gl.getUniformLocation(program, name);
    const place = {size: at("size"), turn: at("turn"), nod: at("nod"), arm: at("arm"), look: at("look"), blink: at("blink"), glow: at("glow"), skin: at("skin"), body: at("cBody"), head: at("cHead"), line: at("cLine"), visor: at("cVisor"), light: at("cLight"), gear: at("cGear")};
    let last = "", gone = false;
    canvas.addEventListener("webglcontextlost", () => { gone = true; box.classList.add("flat"); });
    function fit() {
      // Always full pixels: a busy computer turns the robot more slowly, never blurs it (1.7.41).
      const dpr = Math.min(devicePixelRatio || 1, 2), width = Math.round(canvas.clientWidth * dpr), height = Math.round(canvas.clientHeight * dpr);
      if (!width || !height || (canvas.width === width && canvas.height === height)) return;
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(place.size, width, height);
      last = "";
    }
    function colours() {
      const style = getComputedStyle(box);
      const set = (where, name, fallback) => gl.uniform3fv(where, rgb(style.getPropertyValue(name).trim(), fallback));
      set(place.body, "--robot-body", [.93, .94, .95]);
      set(place.head, "--robot-head", [.97, .97, .98]);
      set(place.line, "--robot-line", [.1, .11, .12]);
      set(place.visor, "--robot-visor", [.1, .11, .13]);
      set(place.light, "--c", [.2, .75, .45]);
      set(place.gear, "--sa-gear", [.12, .37, .82]);
      last = "";
    }
    function draw(view) {
      if (gone) return;
      fit();
      const key = [view.yaw, view.pitch, view.headYaw, view.headPitch, view.roll, view.arm, view.eyeX, view.eyeY, view.blink, view.glow, view.skin || 0].map((value) => value.toFixed(3)).join();
      if (key === last || !canvas.width) return;
      last = key;
      gl.uniformMatrix3fv(place.turn, false, turning(view.yaw, view.pitch, 0));
      gl.uniformMatrix3fv(place.nod, false, turning(view.headYaw, view.headPitch, view.roll));
      gl.uniform2f(place.arm, Math.cos(view.arm), -Math.sin(view.arm));
      gl.uniform2f(place.look, view.eyeX, view.eyeY);
      gl.uniform1f(place.blink, view.blink);
      gl.uniform1f(place.glow, view.glow);
      gl.uniform1f(place.skin, view.skin || 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    box.append(canvas);
    box.classList.add("solid");
    colours();
    return {draw, colours};
  }
  return {make};
})();
