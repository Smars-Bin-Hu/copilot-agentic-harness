// The robot of the Enter screen in 3D (1.6.76): one canvas, one fragment shader that draws the robot of enter.js from distances, no library and no model file.
// BOT3D.make(box) puts the canvas in `box` and returns {draw, colours}; null when the browser has no WebGL, and enter.js keeps its flat robot. It costs nothing while the picture does not change.
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
uniform float blink, glow;
uniform vec3 cBody, cHead, cLine, cVisor, cLight;
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

// The distance to the robot, and which part: 1 body, 2 head, 3 visor, 4 line, 5 bulb.
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
  vec3 light = normalize(vec3(-.45, .7, .8)), base = part < 1.5 ? cBody : part < 2.5 ? cHead : part < 3.5 ? cVisor : part < 4.5 ? cLine : cLight;
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
  if (part > 4.5) colour = cLight;
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

  function make(box) {
    const canvas = h("canvas", {class: "en-bot3d"});
    const gl = canvas.getContext("webgl", {alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: "low-power", failIfMajorPerformanceCaveat: true});
    if (!gl) return null;
    const stage = (type, text) => { const shader = gl.createShader(type); gl.shaderSource(shader, text); gl.compileShader(shader); return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null; };
    const vertex = stage(gl.VERTEX_SHADER, VERTEX), fragment = stage(gl.FRAGMENT_SHADER, FRAGMENT);
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
    const place = {size: at("size"), turn: at("turn"), nod: at("nod"), arm: at("arm"), look: at("look"), blink: at("blink"), glow: at("glow"), body: at("cBody"), head: at("cHead"), line: at("cLine"), visor: at("cVisor"), light: at("cLight")};
    let scale = 1, last = "", gone = false, stamp = 0, frames = 0, spent = 0;
    canvas.addEventListener("webglcontextlost", () => { gone = true; box.classList.add("flat"); });
    function fit() {
      const dpr = Math.min(devicePixelRatio || 1, 2) * scale, width = Math.round(canvas.clientWidth * dpr), height = Math.round(canvas.clientHeight * dpr);
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
      last = "";
    }
    // A slow computer draws fewer pixels and the robot goes on turning.
    function pace(now) {
      if (stamp && now - stamp < 250) { spent += now - stamp; frames++; }
      stamp = now;
      if (frames < 60) return;
      if (spent / frames > 40 && scale > .5) { scale *= .75; fit(); }
      else if (spent / frames < 20 && scale < 1) { scale = Math.min(1, scale / .75); fit(); }  // the computer is free again (a test run or a build ended): the pixels come back (1.7.35)
      frames = spent = 0;
    }
    function draw(view, now) {
      if (gone) return;
      fit();
      const key = [view.yaw, view.pitch, view.headYaw, view.headPitch, view.roll, view.arm, view.eyeX, view.eyeY, view.blink, view.glow].map((value) => value.toFixed(3)).join();
      if (key === last || !canvas.width) return;
      last = key;
      pace(now);
      gl.uniformMatrix3fv(place.turn, false, turning(view.yaw, view.pitch, 0));
      gl.uniformMatrix3fv(place.nod, false, turning(view.headYaw, view.headPitch, view.roll));
      gl.uniform2f(place.arm, Math.cos(view.arm), -Math.sin(view.arm));
      gl.uniform2f(place.look, view.eyeX, view.eyeY);
      gl.uniform1f(place.blink, view.blink);
      gl.uniform1f(place.glow, view.glow);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    box.append(canvas);
    box.classList.add("solid");
    colours();
    return {draw, colours};
  }
  return {make};
})();
