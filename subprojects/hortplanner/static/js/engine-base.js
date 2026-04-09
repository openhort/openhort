// ═══════════════════════════════════════════════════════════════
//  engine-base.js — Shared foundation for HortPlanner engines
//  Pure utility functions, shaders, and constants.
//  Imported by engine.js (infrastructure) and engine-home.js (home editor).
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

// Re-export Three.js and addons for consumers
export { THREE, OrbitControls, EffectComposer, RenderPass, UnrealBloomPass, OutputPass };

// ── Colors ──────────────────────────────────────────────────

export const COLORS = {
  bg:        0x080c18,
  grid:      0x1e3a5f,
  gridMajor: 0x2563eb,
  floor:     0x0f172a,
  selected:  0x60a5fa,
  portIn:    0x3b82f6,
  portOut:   0x22c55e,
};

// ── Grid shaders ────────────────────────────────────────────

export const GRID_VS = `
varying vec3 vWorld;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

export const GRID_FS = `
uniform float uTime;
uniform float uWorldHalf;
uniform vec3 uMinor;
uniform vec3 uMajor;
varying vec3 vWorld;

void main() {
  vec2 c = vWorld.xz;

  // world boundary — grid only inside the world square
  float dx = max(abs(c.x) - uWorldHalf, 0.0);
  float dz = max(abs(c.y) - uWorldHalf, 0.0);
  float outside = max(dx, dz);
  float inWorld = 1.0 - smoothstep(0.0, 1.5, outside);
  if (inWorld < 0.01) discard;

  // grid lines every 1 unit — each cell = 1 tile, 50×50 world = 50 visible tiles
  vec2 g1 = abs(fract(c - 0.5) - 0.5) / fwidth(c);
  float grid = 1.0 - min(min(g1.x, g1.y), 1.0);

  // boundary edge glow
  float edgeDist = min(abs(abs(c.x) - uWorldHalf), abs(abs(c.y) - uWorldHalf));
  float edge = smoothstep(0.5, 0.0, edgeDist) * 0.6;

  float pulse = 0.92 + 0.08 * sin(uTime * 0.3);

  vec3 col = uMajor * grid * 0.45 + vec3(0.15, 0.30, 0.85) * edge;
  float a = (grid * 0.25 * pulse + edge) * inWorld;

  gl_FragColor = vec4(col, a);
}`;

// ── Dot grid shader (n8n-style, for 2D mode) ───────────────

export const DOT_VS = `
varying vec3 vWorld;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

export const DOT_FS = `
varying vec3 vWorld;

void main() {
  vec2 c = vWorld.xz;

  // dot at every grid intersection (every 2 units = lower density)
  vec2 nearest = round(c / 2.0) * 2.0;
  float dist = length(c - nearest);

  // crisp circle — large enough to be visible at any zoom
  float radius = 0.12;
  float aa = fwidth(dist) * 1.5;
  float dot = 1.0 - smoothstep(radius - aa, radius + aa, dist);

  vec3 col = vec3(0.18, 0.14, 0.32);
  gl_FragColor = vec4(col, dot * 0.55);
}`;

// ── Glow textures ───────────────────────────────────────────

let _particleGlowTex = null;
/**
 * Shared round glow texture for flow particles.
 * Canvas-based radial gradient, cached after first call.
 */
export function getParticleGlowTexture() {
  if (_particleGlowTex) return _particleGlowTex;
  const size = 64;
  const c = document.createElement('canvas');
  c.width = size; c.height = size;
  const ctx = c.getContext('2d');
  const cx = size / 2, cy = size / 2;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, size / 2);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.8)');
  grad.addColorStop(0.5, 'rgba(255,255,255,0.3)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  _particleGlowTex = new THREE.CanvasTexture(c);
  return _particleGlowTex;
}

let _portGlowTex = null;
/**
 * Shared port glow texture — crisp diamond with tight bright edge.
 * Canvas-based radial gradient, cached after first call.
 */
export function getPortGlowTexture() {
  if (_portGlowTex) return _portGlowTex;
  const size = 64;
  const c = document.createElement('canvas');
  c.width = size; c.height = size;
  const ctx = c.getContext('2d');
  const cx = size / 2, cy = size / 2;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.35);
  grad.addColorStop(0, 'rgba(140,200,255,1)');
  grad.addColorStop(0.5, 'rgba(96,165,250,0.9)');
  grad.addColorStop(0.8, 'rgba(60,130,246,0.3)');
  grad.addColorStop(1, 'rgba(60,130,246,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  _portGlowTex = new THREE.CanvasTexture(c);
  return _portGlowTex;
}

// ── Scene creation ──────────────────────────────────────────

/**
 * Create a complete Three.js scene with orthographic camera, renderer,
 * post-processing (bloom), lighting, and OrbitControls (pan+zoom only).
 *
 * Returns { scene, camera, renderer, composer, controls, raycaster, groundPlane }.
 */
export function createScene(container) {
  const w = container.clientWidth || 800;
  const h = container.clientHeight || 600;

  // Scene (no fog — grid shader handles its own fade)
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLORS.bg);

  // Camera (orthographic for true isometric)
  const size = 28;
  const aspect = w / h;
  const camera = new THREE.OrthographicCamera(
    -size * aspect / 2, size * aspect / 2,
    size / 2, -size / 2, 0.1, 2000
  );
  // Default isometric position
  const d = 35;
  camera.position.set(d, d, d);
  camera.lookAt(new THREE.Vector3());

  // Renderer
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.4;
  container.appendChild(renderer.domElement);

  // Post-processing
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  composer.addPass(new UnrealBloomPass(
    new THREE.Vector2(w, h), 0.5, 0.4, 0.88
  ));
  composer.addPass(new OutputPass());

  // Lighting — strong global directional illumination
  scene.add(new THREE.AmbientLight(0x506080, 1.0));

  // Key light (main shadow caster, top-right)
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
  keyLight.position.set(20, 40, 25);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(2048, 2048);
  const sc = keyLight.shadow.camera;
  sc.near = 1; sc.far = 120;
  sc.left = sc.bottom = -40; sc.right = sc.top = 40;
  scene.add(keyLight);

  // Fill light (softer, opposite side — reduces harsh shadows)
  const fillLight = new THREE.DirectionalLight(0x8090b0, 0.6);
  fillLight.position.set(-15, 25, -10);
  scene.add(fillLight);

  // Hemisphere (sky/ground ambient)
  scene.add(new THREE.HemisphereLight(0x4060a0, 0x101828, 0.5));

  // Controls — fixed isometric angle, pan + zoom only (SimCity style)
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enableRotate = false;          // no rotation ever
  controls.minZoom = 0.15;  // zoom out far enough to see 50×50 world
  controls.maxZoom = 5;
  controls.screenSpacePanning = true;     // pan in screen plane
  controls.mouseButtons = {
    LEFT: THREE.MOUSE.PAN,                // left-click pans
    MIDDLE: THREE.MOUSE.DOLLY,            // scroll zooms
    RIGHT: THREE.MOUSE.PAN,              // right-click also pans
  };
  controls.touches = {
    ONE: THREE.TOUCH.PAN,
    TWO: THREE.TOUCH.DOLLY_PAN,
  };

  // Raycaster + ground plane
  const raycaster = new THREE.Raycaster();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  return { scene, camera, renderer, composer, controls, raycaster, groundPlane };
}

// ── Grid creation ───────────────────────────────────────────

/**
 * Create the shader-based grid mesh (world-bounded line grid).
 * Returns the grid mesh (already added to scene).
 * Also creates and adds a ground fill plane behind the grid.
 *
 * Returns { gridMesh, groundFill }.
 */
export function createGrid(scene, worldSize) {
  // Solid ground fill — covers the horizon so no background shows through
  const groundGeo = new THREE.PlaneGeometry(1, 1);
  groundGeo.rotateX(-Math.PI / 2);
  const groundFill = new THREE.Mesh(groundGeo, new THREE.MeshBasicMaterial({
    color: COLORS.bg, depthWrite: true,
  }));
  groundFill.renderOrder = -3;
  scene.add(groundFill);

  // Grid (bounded by world size)
  const geo = new THREE.PlaneGeometry(200, 200);
  geo.rotateX(-Math.PI / 2);
  const gridMesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
    vertexShader: GRID_VS,
    fragmentShader: GRID_FS,
    uniforms: {
      uTime: { value: 0 },
      uWorldHalf: { value: worldSize / 2 },
      uMinor: { value: new THREE.Color(COLORS.grid) },
      uMajor: { value: new THREE.Color(COLORS.gridMajor) },
    },
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  }));
  gridMesh.renderOrder = -1;
  scene.add(gridMesh);

  return { gridMesh, groundFill };
}

// ── Dot grid creation ───────────────────────────────────────

/**
 * Create the dot grid mesh for 2D/flat mode (n8n-style dots).
 * Returns the dot grid mesh (already added to scene, hidden by default).
 */
export function createDotGrid(scene) {
  const geo = new THREE.PlaneGeometry(200, 200);
  geo.rotateX(-Math.PI / 2);
  const dotGridMesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
    vertexShader: DOT_VS,
    fragmentShader: DOT_FS,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  }));
  dotGridMesh.position.y = 0.01; // slightly above ground
  dotGridMesh.renderOrder = -1;
  dotGridMesh.visible = false;  // hidden by default (shown in 2D mode)
  scene.add(dotGridMesh);
  return dotGridMesh;
}

// ── HTML labels ─────────────────────────────────────────────

/**
 * Create an HTML label div and append it to the overlay container.
 * Returns the element (or null if no overlay provided).
 */
export function makeHtmlLabel(text, overlay) {
  if (!overlay) return null;
  const el = document.createElement('div');
  el.className = 'label-3d';
  el.textContent = text;
  overlay.appendChild(el);
  return el;
}

// ── Scale animation ─────────────────────────────────────────

/**
 * Animate a mesh's scale from 0 to `target` over `duration` ms
 * with ease-out cubic easing.
 */
export function tweenScale(mesh, target, duration) {
  const t0 = performance.now();
  const step = () => {
    const t = Math.min((performance.now() - t0) / duration, 1);
    const e = 1 - Math.pow(1 - t, 3); // ease-out cubic
    const s = e * target;
    mesh.scale.set(s, s, s);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── Grid uniform updates ────────────────────────────────────

/**
 * Per-frame grid update: repositions grid/dot-grid/ground-fill to follow
 * the camera target, scales to cover the viewport, and updates shader uniforms.
 *
 * Call this every frame in the animation loop.
 *
 * @param {THREE.Mesh} gridMesh       - The line grid mesh (may be null)
 * @param {THREE.Mesh} dotGridMesh    - The dot grid mesh (may be null)
 * @param {THREE.Mesh} groundFill     - The ground fill plane (may be null)
 * @param {number}     time           - Elapsed time (seconds) from THREE.Clock
 * @param {number}     worldSize      - Current world size (tiles)
 * @param {OrbitControls} controls    - OrbitControls instance
 * @param {THREE.OrthographicCamera} camera - The orthographic camera
 */
export function updateGridUniforms(gridMesh, dotGridMesh, groundFill, time, worldSize, controls, camera) {
  const zoom = camera.zoom || 1;
  const frustumMax = Math.max(
    (camera.right - camera.left),
    (camera.top - camera.bottom)
  ) / zoom;
  // 20× frustum covers the isometric ground projection generously
  const gridScale = Math.max(2, frustumMax * 20 / 200);
  const tx = controls.target.x;
  const tz = controls.target.z;

  if (gridMesh) {
    gridMesh.material.uniforms.uTime.value = time;
    gridMesh.material.uniforms.uWorldHalf.value = worldSize / 2;
    gridMesh.scale.set(gridScale, 1, gridScale);
    gridMesh.position.set(tx, 0, tz);
  }
  if (dotGridMesh) {
    dotGridMesh.scale.set(gridScale, 1, gridScale);
    dotGridMesh.position.set(tx, 0.01, tz);
  }
  // Ground fill: same position/scale, covers horizon
  if (groundFill) {
    groundFill.scale.set(gridScale * 300, 1, gridScale * 300);
    groundFill.position.set(tx, -0.02, tz);
  }
}

// ── 3D → screen projection ──────────────────────────────────

/**
 * Project a 3D world position to 2D screen coordinates.
 *
 * @param {THREE.Vector3} pos3d - World position to project
 * @param {THREE.Camera}  camera - The camera
 * @param {number} containerW    - Container width in pixels
 * @param {number} containerH    - Container height in pixels
 * @returns {{ x: number, y: number, behind: boolean }}
 *   x, y in pixel coordinates; behind=true if the point is behind the camera.
 */
export function projectToScreen(pos3d, camera, containerW, containerH) {
  const projected = pos3d.clone().project(camera);
  const behind = projected.z > 1;
  const x = (projected.x * 0.5 + 0.5) * containerW;
  const y = (-projected.y * 0.5 + 0.5) * containerH;
  return { x, y, behind };
}
