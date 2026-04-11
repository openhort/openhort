// ═══════════════════════════════════════════════════════════════
//  HortPlanner Engine — Three.js Isometric Infrastructure Designer
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { WorldGrid, InternalGrid, GRID } from './grid.js';
import { ActionHistory, serializeWorld } from './history.js';
import { loadManifest, getManifest, getDisplayName, getPorts, getBodyDef, buildComponentMesh, playAnimation } from './models.js';

// ── Colors ──────────────────────────────────────────────────

const C = {
  bg:        0x080c18,
  grid:      0x1e3a5f,
  gridMajor: 0x2563eb,
  macMini:   0xa8b0bc,
  macBook:   0x6b7280,
  rpi:       0x16a34a,
  cloudVM:   0x3b82f6,
  docker:    0x0ea5e9,
  virtual:   0xa855f7,
  mcp:       0xf59e0b,
  llming:    0x8b5cf6,
  program:   0x10b981,
  agent:     0x06b6d4,
  fence:     0xf97316,
  portIn:    0x3b82f6,
  portOut:   0x22c55e,
  conn:      0xeab308,
  selected:  0x60a5fa,
  floor:     0x0f172a,
};

// ── Connection security levels ─────────────────────────────

const SECURITY_COLORS = {
  none:    0xeab308,   // yellow (unconfigured)
  read:    0x22c55e,   // green
  write:   0xeab308,   // yellow
  send:    0xf97316,   // orange
  destroy: 0xef4444,   // red
};

// ── Component definitions ───────────────────────────────────

// DEFS: visual properties per type. Grid sizing lives in grid.js (GRID).
// w/d are now derived from GRID at runtime for machine horts.
// h = wall height for containers, body height for tools (tools ~2× container to be visible inside walls)
const DEFS = {
  'mac-mini':     { h: 1.0, color: C.macMini, container: true,  metal: 0.85, rough: 0.20, ports: { in: 1, out: 1 }, cornerR: 0.35, feet: true },
  'macbook':      { h: 0.4, color: C.macBook, container: true,  metal: 0.80, rough: 0.25, ports: { in: 1, out: 1 }, screen: true, cornerR: 0.2 },
  'rpi':          { h: 0.5, color: C.rpi,     container: true,  metal: 0.30, rough: 0.70, ports: { in: 1, out: 1 }, cornerR: 0.08 },
  'cloud-vm':     { h: 1.2, color: C.cloudVM, container: true,  metal: 0.10, rough: 0.90, ports: { in: 1, out: 1 }, opacity: 0.55, cornerR: 0.1 },
  'docker':       { h: 1.0, color: C.docker,  container: true,  metal: 0.40, rough: 0.50, ports: { in: 1, out: 1 }, cornerR: 0.1 },
  'virtual-hort': { h: 1.0, color: C.virtual, container: false, metal: 0.10, rough: 0.90, ports: { in: 1, out: 1 }, opacity: 0.45, cornerR: 0.1 },
  'mcp-server':   { h: 2.0, color: C.mcp,     container: false, metal: 0.60, rough: 0.30, ports: { in: 1, out: 1 }, shape: 'hex' },
  'llming':       { h: 2.0, color: C.llming,  container: false, metal: 0.30, rough: 0.50, ports: { in: 1, out: 1 }, shape: 'ico' },
  'program':      { h: 2.0, color: C.program, container: false, metal: 0.50, rough: 0.40, ports: { in: 1, out: 1 }, shape: 'box' },
  'agent':        { h: 2.5, color: C.agent,   container: false, metal: 0.25, rough: 0.35, ports: { in: 1, out: 1 }, shape: 'diamond' },
  'fence':        { h: 0.08,color: C.fence,   container: false, metal: 0.00, rough: 1.00, ports: { in: 0, out: 0 }, opacity: 0.30 },
};

// Display names come from manifest (loaded async), fallback to type
function displayName(type) { return getDisplayName(type); }

/** Get the visual w/d for a component type (derived from GRID). */
function vizSize(type) {
  const g = GRID[type];
  if (g.cat === 'machine') {
    return { w: g.innerW + 0.7, d: g.innerD + 0.7 };
  }
  if (g.cat === 'tool') {
    return { w: g.footW * 0.8, d: g.footD * 0.8 };
  }
  // sub-horts: use footprint as visual size
  return { w: g.footW, d: g.footD };
}

// ── GLB model loader ───────────────────────────────────────

const _glbCache = new Map();
const _glbLoader = new GLTFLoader();

async function loadGLBModel(type) {
    if (_glbCache.has(type)) return _glbCache.get(type).clone();
    try {
        const gltf = await _glbLoader.loadAsync(`/static/models/glb/${type}.glb`);
        const model = gltf.scene;
        _glbCache.set(type, model);
        return model.clone();
    } catch (e) {
        console.warn(`GLB not found for ${type}, using procedural fallback`);
        return null;
    }
}

// ── Shaders ─────────────────────────────────────────────────

const GRID_VS = `
varying vec3 vWorld;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

// World-bounded version uses uWorldHalf to clip grid to the world area

const GRID_FS = `
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

const DOT_VS = `
varying vec3 vWorld;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

const DOT_FS = `
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

// ── Factory: labels ─────────────────────────────────────────

/** Create an HTML label div (managed by the engine's label overlay). */
function makeHtmlLabel(text, overlay) {
  if (!overlay) return null;
  const el = document.createElement('div');
  el.className = 'label-3d';
  el.textContent = text;
  overlay.appendChild(el);
  return el;
}

// ── Factory: ports (4-sided, universal) ─────────────────────

// Shared port glow texture — crisp diamond with tight bright edge
let _portGlowTex = null;
function getPortGlowTexture() {
  if (_portGlowTex) return _portGlowTex;
  const size = 64;
  const c = document.createElement('canvas');
  c.width = size; c.height = size;
  const ctx = c.getContext('2d');
  const cx = size / 2, cy = size / 2;
  // Diamond shape — crisp inner, tight falloff
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

// Shared round glow texture for flow particles
let _particleGlowTex = null;
function getParticleGlowTexture() {
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

function addPorts(group, def) {
  const totalPorts = (def.ports.in || 0) + (def.ports.out || 0);
  if (totalPorts === 0) return;

  const hitGeo = new THREE.SphereGeometry(0.30, 6, 6);
  const portY = def.h * 0.5 + 0.15;
  const sides = [
    { side: 'right', x:  def.w / 2 + 0.05, z: 0 },
    { side: 'left',  x: -def.w / 2 - 0.05, z: 0 },
    { side: 'front', x: 0, z:  def.d / 2 + 0.05 },
    { side: 'back',  x: 0, z: -def.d / 2 - 0.05 },
  ];

  for (const s of sides) {
    const g = new THREE.Group();

    // Glow sprite — hidden by default, shown on hover
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: getPortGlowTexture(), transparent: true, depthWrite: false })
    );
    sprite.scale.set(0.22, 0.22, 1);
    sprite.visible = false;
    sprite.userData.isPortGlow = true;
    g.add(sprite);

    // Invisible hit zone (for raycasting)
    const hit = new THREE.Mesh(hitGeo, new THREE.MeshBasicMaterial({ visible: false }));
    hit.userData = { isPort: true, portSide: s.side };
    g.add(hit);

    g.position.set(s.x, portY, s.z);
    group.add(g);
  }
}

// ── Rounded rect helpers ────────────────────────────────────

function rrShape(w, d, r) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -d / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + d - r); s.quadraticCurveTo(x + w, y + d, x + w - r, y + d);
  s.lineTo(x + r, y + d); s.quadraticCurveTo(x, y + d, x, y + d - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

function rrPath(w, d, r) {
  const p = new THREE.Path();
  const x = -w / 2, y = -d / 2;
  p.moveTo(x + r, y);
  p.lineTo(x + w - r, y); p.quadraticCurveTo(x + w, y, x + w, y + r);
  p.lineTo(x + w, y + d - r); p.quadraticCurveTo(x + w, y + d, x + w - r, y + d);
  p.lineTo(x + r, y + d); p.quadraticCurveTo(x, y + d, x, y + d - r);
  p.lineTo(x, y + r); p.quadraticCurveTo(x, y, x + r, y);
  return p;
}

// ── Factory: open-top container (single extruded wall ring, no corner artifacts) ──

function makeContainer(def) {
  const { w, h, d, color, metal, rough } = def;
  const t = 0.10;
  const r = def.cornerR || 0.15;
  const group = new THREE.Group();

  const isTransparent = !!def.opacity && def.opacity < 1;
  const mat = new THREE.MeshStandardMaterial({
    color, metalness: metal, roughness: rough,
    side: isTransparent ? THREE.FrontSide : THREE.DoubleSide,
    transparent: isTransparent, opacity: def.opacity ?? 1,
    depthWrite: !isTransparent, // transparent objects don't write depth (prevents z-fight)
    polygonOffset: isTransparent, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });

  // floor (rounded rect matching wall shape)
  const ft = 0.08;
  const floorShape = rrShape(w, d, r);
  const floorGeo = new THREE.ExtrudeGeometry(floorShape, { depth: ft, bevelEnabled: false });
  floorGeo.rotateX(-Math.PI / 2);
  // after rotate: extrudes from y=0 upward to y=ft
  const floor = new THREE.Mesh(floorGeo, mat);
  floor.receiveShadow = true;
  group.add(floor);

  // wall ring (extruded hollow shape, sits directly on floor top)
  const wallOuter = rrShape(w, d, r);
  const iw = w - t * 2, id = d - t * 2;
  const ir = Math.max(0.02, r - t);
  wallOuter.holes.push(rrPath(iw, id, ir));
  const wallGeo = new THREE.ExtrudeGeometry(wallOuter, { depth: h, bevelEnabled: false });
  wallGeo.rotateX(-Math.PI / 2);
  // after rotate: ring from y=0 (top) to y=-h (bottom)
  // translate so bottom = ft (floor top)
  wallGeo.translate(0, ft, 0); // extrude goes y=0..h after rotate; shift up by ft to sit on floor top
  const walls = new THREE.Mesh(wallGeo, mat);
  walls.castShadow = true;
  walls.userData.isWall = true;
  group.add(walls);

  // dark interior floor
  const inner = new THREE.Mesh(
    new THREE.PlaneGeometry(iw - 0.02, id - 0.02),
    new THREE.MeshStandardMaterial({ color: C.floor, roughness: 0.95 })
  );
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = ft + 0.005; // just above the floor box
  inner.receiveShadow = true;
  group.add(inner);

  // LED indicator
  const led = new THREE.Mesh(
    new THREE.SphereGeometry(0.06, 8, 8),
    new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: 0x22c55e, emissiveIntensity: 3 })
  );
  led.position.set(0, ft + h * 0.4, d / 2 + 0.01);
  group.add(led);

  // Feet (Snack Mini / Mac Mini style)
  if (def.feet) {
    const footMat = new THREE.MeshStandardMaterial({ color: 0x333333, metalness: 0.6, roughness: 0.4 });
    const footGeo = new THREE.CylinderGeometry(0.12, 0.14, 0.06, 12);
    const inset = 0.35;
    for (const [fx, fz] of [[-w/2+inset, -d/2+inset], [w/2-inset, -d/2+inset], [-w/2+inset, d/2-inset], [w/2-inset, d/2-inset]]) {
      const foot = new THREE.Mesh(footGeo, footMat);
      foot.position.set(fx, -0.03, fz);
      group.add(foot);
    }
    // raise entire model to sit on feet
    group.position.y = 0.06;
  }

  return group;
}

// ── Factory: screen (MacBook) ───────────────────────────────

function addScreen(group, def) {
  const { w, h, d } = def;
  const screenT = 0.05;
  // screen is roughly same depth as the base, tilted back ~110° from horizontal
  const screenD = d * 0.95;
  const tiltAngle = -0.17; // ~10° slight tilt

  const hinge = new THREE.Group();
  // hinge at the back edge of the base, at wall top
  hinge.position.set(0, h, -d / 2 + 0.05);

  // screen shell (tilted back like an open laptop)
  const shellGeo = new THREE.BoxGeometry(w - 0.1, screenD, screenT);
  const shell = new THREE.Mesh(shellGeo,
    new THREE.MeshStandardMaterial({ color: def.color, metalness: 0.8, roughness: 0.25 })
  );
  shell.position.y = screenD / 2;
  shell.castShadow = true;
  hinge.add(shell);

  // display face (dark with subtle glow)
  const displayGeo = new THREE.PlaneGeometry(w - 0.4, screenD - 0.25);
  const display = new THREE.Mesh(displayGeo,
    new THREE.MeshStandardMaterial({
      color: 0x0c1829, emissive: 0x1a3050, emissiveIntensity: 0.6,
      metalness: 0.1, roughness: 0.9,
    })
  );
  display.position.set(0, screenD / 2, screenT / 2 + 0.002);
  hinge.add(display);

  // tilt the whole screen assembly back
  hinge.rotation.x = tiltAngle;

  group.add(hinge);
}

// ── Factory: special shapes ─────────────────────────────────

function makeHexPrism(def) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(def.w / 2, def.w / 2, def.h, 6),
    new THREE.MeshStandardMaterial({
      color: def.color, metalness: def.metal, roughness: def.rough,
      emissive: def.color, emissiveIntensity: 0.25,
    })
  );
  mesh.position.y = def.h / 2 + 0.05;
  mesh.castShadow = true;
  group.add(mesh);
  return group;
}

function makeIcosphere(def) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.IcosahedronGeometry(def.w * 0.55, 1),
    new THREE.MeshStandardMaterial({
      color: def.color, metalness: def.metal, roughness: def.rough,
      emissive: def.color, emissiveIntensity: 0.35,
    })
  );
  mesh.position.y = def.h / 2 + 0.15;
  mesh.castShadow = true;
  mesh.userData.spin = true;
  group.add(mesh);
  return group;
}

function makeBox(def) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(def.w, def.h, def.d),
    new THREE.MeshStandardMaterial({
      color: def.color, metalness: def.metal, roughness: def.rough,
      transparent: !!def.opacity, opacity: def.opacity ?? 1,
    })
  );
  mesh.position.y = def.h / 2 + 0.05;
  mesh.castShadow = true;
  group.add(mesh);
  return group;
}

// ── Factory: component mesh ─────────────────────────────────

function createComponentMesh(type) {
  const sz = vizSize(type);
  const group = buildComponentMesh(type, sz.w, sz.d);

  // add ports (still uses DEFS for port count, will migrate to manifest)
  const ports = getPorts(type);
  const bodyDef = getBodyDef(type);
  const h = bodyDef.wallHeight || bodyDef.height || 1;
  addPorts(group, { w: sz.w, d: sz.d, h, ports });

  group.userData.compType = type;
  return group;
}

async function createComponentMeshAsync(type) {
  const sz = vizSize(type);

  // Try GLB first
  let group = await loadGLBModel(type);
  if (group) {
    // GLB loaded — add port hit targets for connection creation
    const ports = getPorts(type);
    const bodyDef = getBodyDef(type);
    const h = bodyDef.wallHeight || bodyDef.height || 1;
    addPorts(group, { w: sz.w, d: sz.d, h, ports });
    group.userData.compType = type;
    return group;
  }

  // Fallback to procedural
  group = buildComponentMesh(type, sz.w, sz.d);
  const ports = getPorts(type);
  const bodyDef = getBodyDef(type);
  const h = bodyDef.wallHeight || bodyDef.height || 1;
  addPorts(group, { w: sz.w, d: sz.d, h, ports });
  group.userData.compType = type;
  return group;
}

// ── Factory: connection ─────────────────────────────────────

function createConnectionMesh(fromPos, toPos, fromNormal, toNormal, security = 'none') {
  const connColor = SECURITY_COLORS[security] ?? SECURITY_COLORS.none;
  const dist = fromPos.distanceTo(toPos);
  const pullout = Math.max(0.8, dist * 0.3);
  // Ballistic arc — height scales with distance for dramatic 3D trajectories
  const arcHeight = Math.max(0.4, dist * 0.25);

  // Cubic bezier: exit along source normal, arc up, arrive along target normal
  const p0 = fromPos.clone();
  const p1 = fromPos.clone().add(fromNormal.clone().multiplyScalar(pullout));
  const p2 = toPos.clone().add(toNormal.clone().multiplyScalar(pullout));
  const p3 = toPos.clone();
  p1.y += arcHeight;
  p2.y += arcHeight;

  const curve = new THREE.CubicBezierCurve3(p0, p1, p2, p3);
  const group = new THREE.Group();

  // tube
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 64, 0.03, 8, false),
    new THREE.MeshStandardMaterial({
      color: connColor, emissive: connColor, emissiveIntensity: 0.6,
      transparent: true, opacity: 0.75,
    })
  );
  tube.userData.isConnTube = true;
  group.add(tube);

  // 3D arrow head at target end
  const tangent = curve.getTangent(1).normalize();
  const arrowGeo = new THREE.ConeGeometry(0.09, 0.28, 8);
  const arrowMat = new THREE.MeshStandardMaterial({
    color: connColor, emissive: connColor, emissiveIntensity: 1.5,
  });
  const arrow = new THREE.Mesh(arrowGeo, arrowMat);
  // Position slightly before the end so it overlaps the tube tip
  arrow.position.copy(p3).sub(tangent.clone().multiplyScalar(0.08));
  // Orient: ConeGeometry points along +Y by default, rotate to tangent
  const up = new THREE.Vector3(0, 1, 0);
  arrow.quaternion.setFromUnitVectors(up, tangent);
  group.add(arrow);

  // flow particles (3 glow sprites — always round)
  const pMat = new THREE.SpriteMaterial({
    map: getParticleGlowTexture(), color: connColor,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const particles = [];
  for (let i = 0; i < 3; i++) {
    const p = new THREE.Sprite(pMat.clone());
    p.scale.set(0.22, 0.22, 1);
    group.add(p);
    particles.push(p);
  }

  group.userData.curve = curve;
  group.userData.particles = particles;
  group.userData.isConnection = true;
  group.userData.security = security;
  return group;
}

// ═══════════════════════════════════════════════════════════════
//  Engine
// ═══════════════════════════════════════════════════════════════

export class HortPlannerEngine {
  constructor(container, callbacks = {}, labelOverlay = null) {
    this.container = container;
    this.cb = callbacks;
    this.labelOverlay = labelOverlay;
    this.components = new Map();   // id → { mesh, type, name, children[], parentId }
    this.connections = [];         // { id, from:{compId,portType,portIdx}, to:{...}, mesh }
    this.selectedId = null;
    this.selectedConnId = null;    // selected connection id
    this.activeTool = null;
    this.viewMode = 'isometric';
    this.currentLevelId = null;    // null = top level
    this.levelStack = [];          // [{id, name}]
    this._nextId = 1;
    this._nextConnId = 1;
    this.clock = new THREE.Clock();
    this._connectingFrom = null;
    this._previewLine = null;
    this._pointerStart = null;
    this._cameraTween = null;
    this._highlightedCompId = null;
    this._dragCandidate = null;   // compId that might be dragged
    this._dragging = null;        // compId currently being dragged
    this._dragOffset = new THREE.Vector3();
    this._dropPreviewType = null; // type being dragged from palette
    this.worldGrid = new WorldGrid();
    this.history = new ActionHistory();
    this.worldSize = 20;          // initial world: 50×50 centered on origin
    this.manifestLoaded = false;

    this._init();
  }

  // ── Setup ───────────────────────────────────────────────

  _init() {
    // ensure container has size (Quasar layout may not have rendered yet)
    let w = this.container.clientWidth || 800;
    let h = this.container.clientHeight || 600;

    // scene (no fog — grid shader handles its own fade)
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(C.bg);

    // camera (orthographic for true isometric)
    const size = 28;
    const aspect = w / h;
    this.camera = new THREE.OrthographicCamera(
      -size * aspect / 2, size * aspect / 2,
      size / 2, -size / 2, 0.1, 2000
    );
    this._setIsometricCamera();

    // renderer
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.4;
    this.container.appendChild(this.renderer.domElement);

    // post-processing
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.composer.addPass(new UnrealBloomPass(
      new THREE.Vector2(w, h), 0.5, 0.4, 0.88
    ));
    this.composer.addPass(new OutputPass());

    // lighting — strong global directional illumination
    this.scene.add(new THREE.AmbientLight(0x506080, 1.0));

    // key light (main shadow caster, top-right)
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
    keyLight.position.set(20, 40, 25);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(2048, 2048);
    const sc = keyLight.shadow.camera;
    sc.near = 1; sc.far = 120;
    sc.left = sc.bottom = -40; sc.right = sc.top = 40;
    this.scene.add(keyLight);

    // fill light (softer, opposite side — reduces harsh shadows)
    const fillLight = new THREE.DirectionalLight(0x8090b0, 0.6);
    fillLight.position.set(-15, 25, -10);
    this.scene.add(fillLight);

    // hemisphere (sky/ground ambient)
    this.scene.add(new THREE.HemisphereLight(0x4060a0, 0x101828, 0.5));

    // grid
    this._createGrid();

    // dot grid (2D mode)
    this._createDotGrid();

    // world boundary diamond
    this._createWorldBorder();

    // ghost preview for drop-into-hort
    this._createGhostPreview();

    // preview cells (drag highlighting)
    this._createPreviewCells();

    // controls — fixed isometric angle, pan + zoom only (SimCity style)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enableRotate = false;          // no rotation ever
    this.controls.minZoom = 0.15;  // zoom out far enough to see 50×50 world
    this.controls.maxZoom = 5;
    this.controls.screenSpacePanning = true;     // pan in screen plane
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.PAN,                     // left-click pans
      MIDDLE: THREE.MOUSE.DOLLY,                 // scroll zooms
      RIGHT: THREE.MOUSE.PAN,                    // right-click also pans
    };
    this.controls.touches = {
      ONE: THREE.TOUCH.PAN,
      TWO: THREE.TOUCH.DOLLY_PAN,
    };

    // raycaster
    this.raycaster = new THREE.Raycaster();
    this._groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

    // events
    this._bindEvents();

    // resize observer
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.container);

    // load model manifest then start render
    loadManifest().then(() => { this.manifestLoaded = true; });
    this._animate();
  }

  _createGrid() {
    // solid ground fill — covers the horizon so no background shows through
    const groundGeo = new THREE.PlaneGeometry(1, 1);
    groundGeo.rotateX(-Math.PI / 2);
    this._groundFill = new THREE.Mesh(groundGeo, new THREE.MeshBasicMaterial({
      color: C.bg, depthWrite: true,
    }));
    this._groundFill.renderOrder = -3;
    this.scene.add(this._groundFill);

    // grid (bounded by world size)
    const geo = new THREE.PlaneGeometry(200, 200);
    geo.rotateX(-Math.PI / 2);
    this.gridMesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
      vertexShader: GRID_VS,
      fragmentShader: GRID_FS,
      uniforms: {
        uTime: { value: 0 },
        uWorldHalf: { value: this.worldSize / 2 },
        uMinor: { value: new THREE.Color(C.grid) },
        uMajor: { value: new THREE.Color(C.gridMajor) },
      },
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    this.gridMesh.renderOrder = -1;
    this.scene.add(this.gridMesh);
  }

  _createDotGrid() {
    const geo = new THREE.PlaneGeometry(200, 200);
    geo.rotateX(-Math.PI / 2);
    this.dotGridMesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
      vertexShader: DOT_VS,
      fragmentShader: DOT_FS,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    this.dotGridMesh.position.y = 0.01; // slightly above ground
    this.dotGridMesh.renderOrder = -1;
    this.dotGridMesh.visible = false;  // hidden by default (shown in 2D mode)
    this.scene.add(this.dotGridMesh);
  }

  _showDotGrid(show) {
    if (this.dotGridMesh) this.dotGridMesh.visible = show;
    if (this.gridMesh) this.gridMesh.visible = !show;
    if (show) this.camera.up.set(0, 0, -1);
    else this.camera.up.set(0, 1, 0);
  }

  // world border is drawn by the grid shader (uWorldHalf) — no separate mesh needed
  _createWorldBorder() {}
  _rebuildWorldBorder() {}

  /** Grow world if a component is near the edge. */
  /** Fit the world grid tightly around all machine horts + padding.
   *  Grows AND shrinks. Accepts optional extra rect for drag preview. */
  _checkWorldGrowth(extraX, extraZ, extraW, extraD) {
    const pad = 8; // tiles of padding on each side
    const minSize = 20; // minimum world size

    // Find bounding box of all machine horts
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    this.components.forEach(comp => {
      if (comp.parentId !== null) return;
      const fw = comp.footW || 6, fd = comp.footD || 6;
      minX = Math.min(minX, comp.gridX);
      minZ = Math.min(minZ, comp.gridZ);
      maxX = Math.max(maxX, comp.gridX + fw);
      maxZ = Math.max(maxZ, comp.gridZ + fd);
    });

    // Include pending drag position
    if (extraX !== undefined) {
      const ew = extraW || 6, ed = extraD || 6;
      minX = Math.min(minX, extraX);
      minZ = Math.min(minZ, extraZ);
      maxX = Math.max(maxX, extraX + ew);
      maxZ = Math.max(maxZ, extraZ + ed);
    }

    // Nothing placed yet
    if (!isFinite(minX)) { this.worldSize = minSize; return; }

    // Compute needed size: content range + padding on each side, centered on origin
    const contentW = maxX - minX;
    const contentD = maxZ - minZ;
    const cx = (minX + maxX) / 2;
    const cz = (minZ + maxZ) / 2;
    // World must extend pad beyond the content in all 4 directions from the center
    const needHalfW = Math.max(Math.abs(minX - pad), Math.abs(maxX + pad));
    const needHalfD = Math.max(Math.abs(minZ - pad), Math.abs(maxZ + pad));
    const needHalf = Math.max(needHalfW, needHalfD);
    const newSize = Math.max(minSize, Math.ceil(needHalf * 2));

    if (newSize !== this.worldSize) {
      this.worldSize = newSize;
      this._rebuildWorldBorder();
    }
  }

  /** Pre-allocate a pool of flat cell planes for drag preview. */
  /** Dry-run: where would a child be placed? Returns {relX, relZ, fw, fd} or null. */
  _previewChildPlacement(parentId, type) {
    const parent = this.components.get(parentId);
    if (!parent || !parent.internalGrid) return null;
    const g = GRID[type];
    const fw = g.footW || 1;
    const fd = g.footD || 1;
    // try finding space in the current grid without modifying it
    const slot = parent.internalGrid.findSpace(fw, fd);
    if (slot) return { relX: slot.x, relZ: slot.z, fw, fd, wouldGrow: false };
    // would need growth — estimate where it would go
    let testW = parent.innerW, testD = parent.innerD;
    for (let i = 0; i < 10; i++) {
      testW++; testD++;
      // create a temporary grid to test
      const testGrid = new InternalGrid(testW, testD);
      // copy existing occupants
      if (parent.internalGrid.childRects) {
        for (const [cid, rect] of parent.internalGrid.childRects) {
          testGrid.occupy(cid, rect.x, rect.z, rect.w, rect.d);
        }
      }
      const testSlot = testGrid.findSpace(fw, fd);
      if (testSlot) return { relX: testSlot.x, relZ: testSlot.z, fw, fd, wouldGrow: true, newW: testW, newD: testD };
    }
    return null;
  }

  /** Ghost mesh for drop-into-hort preview. */
  _createGhostPreview() {
    const geo = new THREE.BoxGeometry(1, 1, 1);
    this._ghostMesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: 0x60a5fa, transparent: true, opacity: 0.4,
      depthWrite: false, depthTest: false,
    }));
    this._ghostMesh.visible = false;
    this._ghostMesh.renderOrder = 10;
    this.scene.add(this._ghostMesh);
  }

  _createPreviewCells() {
    this._previewPool = [];
    this._previewGroup = new THREE.Group();
    this._previewGroup.visible = false;
    const geo = new THREE.PlaneGeometry(0.96, 0.96);
    geo.rotateX(-Math.PI / 2);
    for (let i = 0; i < 120; i++) {
      const mat = new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.25, depthWrite: false });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.visible = false;
      mesh.renderOrder = 1;
      this._previewGroup.add(mesh);
      this._previewPool.push(mesh);
    }
    this.scene.add(this._previewGroup);
  }

  /** Show preview cells at given grid positions with color. */
  _showPreview(contentCells, gapCells, valid) {
    this._previewGroup.visible = true;
    let idx = 0;
    const green = 0x22c55e, red = 0xef4444, dimBlue = 0x1e3a5f;
    for (const c of contentCells) {
      if (idx >= this._previewPool.length) break;
      const m = this._previewPool[idx++];
      m.visible = true;
      m.position.set(c.x + 0.5, 0.02, c.z + 0.5);
      m.material.color.setHex(valid ? green : red);
      m.material.opacity = valid ? 0.22 : 0.30;
    }
    for (const c of gapCells) {
      if (idx >= this._previewPool.length) break;
      const m = this._previewPool[idx++];
      m.visible = true;
      m.position.set(c.x + 0.5, 0.015, c.z + 0.5);
      m.material.color.setHex(valid ? dimBlue : red);
      m.material.opacity = valid ? 0.08 : 0.12;
    }
    // hide unused
    for (; idx < this._previewPool.length; idx++)
      this._previewPool[idx].visible = false;
  }

  _hidePreview() {
    this._previewGroup.visible = false;
    for (const m of this._previewPool) m.visible = false;
    if (this._previewHortId) { this._setGlow(this._previewHortId, false); this._previewHortId = null; }
    if (this._ghostMesh) this._ghostMesh.visible = false;
  }

  /** Show grid preview during palette dragover. */
  _updateDropPreview(e) {
    // read the type from the dragover event (set by dragstart)
    // browsers restrict getData in dragover, so we stash the type via a class on body
    const type = document.body.dataset.hortDragType;
    if (!type || !GRID[type]) { this._hidePreview(); return; }

    const g = GRID[type];
    const pos = this._screenToGround(e.clientX, e.clientY);
    if (!pos) { this._hidePreview(); return; }

    if (this.currentLevelId === null && g.cat !== 'machine') {
      // hovering a sub-hort/tool over the world → preview placement inside target hort
      const hortId = this.worldGrid.hortAt(pos.x, pos.z);
      if (hortId) {
        const comp = this.components.get(hortId);
        if (comp) {
          // highlight the target hort
          const cells = this.worldGrid.getContentCells(comp.gridX, comp.gridZ, comp.innerW, comp.innerD);
          this._showPreview(cells, [], true);
          if (this._previewHortId !== hortId) {
            if (this._previewHortId) this._setGlow(this._previewHortId, false);
            this._setGlow(hortId, true);
            this._previewHortId = hortId;
          }
          // show ghost of where the child would land
          const preview = this._previewChildPlacement(hortId, type);
          if (preview) {
            const sz = vizSize(type);
            const scaleX = (comp.footW || comp.innerW) / (comp.innerW || 1);
            const scaleZ = (comp.footD || comp.innerD) / (comp.innerD || 1);
            const scale = Math.min(scaleX, scaleZ);
            const px = comp.mesh.position.x - (comp.footW || comp.innerW) / 2
              + (preview.relX + preview.fw / 2) * scaleX;
            const pz = comp.mesh.position.z - (comp.footD || comp.innerD) / 2
              + (preview.relZ + preview.fd / 2) * scaleZ;
            this._ghostMesh.visible = true;
            const wallH = DEFS[comp.type]?.h || 1;
            this._ghostMesh.position.set(px, comp.mesh.position.y + wallH + 0.3, pz);
            this._ghostMesh.scale.set(sz.w * scale, DEFS[type].h * scale * 0.7, sz.d * scale);
          }
          return;
        }
      }
      // not over a hort → show red indicator + hide ghost
      if (this._previewHortId) { this._setGlow(this._previewHortId, false); this._previewHortId = null; }
      this._ghostMesh.visible = false;
      const gx = Math.round(pos.x - 0.5);
      const gz = Math.round(pos.z - 0.5);
      this._showPreview([{ x: gx, z: gz }], [], false);
      return;
    }

    if (g.cat === 'machine' && this.currentLevelId === null) {
      const gx = Math.round(pos.x - g.innerW / 2);
      const gz = Math.round(pos.z - g.innerD / 2);
      this._checkWorldGrowth(gx, gz, g.innerW, g.innerD);
      const content = this.worldGrid.getContentCells(gx, gz, g.innerW, g.innerD);
      const gap = this.worldGrid.getGapCells(gx, gz, g.innerW, g.innerD);
      const { valid } = this.worldGrid.canPlace(gx, gz, g.innerW, g.innerD);
      this._showPreview(content, gap, valid);
    }
  }

  _setIsometricCamera() {
    const d = 35;
    this.camera.position.set(d, d, d);
    this.camera.lookAt(this.controls?.target ?? new THREE.Vector3());
  }

  _setFlatCamera() {
    this.camera.position.set(0.01, 45, 0.01);
    this.camera.lookAt(this.controls?.target ?? new THREE.Vector3());
  }

  // ── Public API ────────────────────────────────────────────

  setActiveTool(type) {
    this.activeTool = type;
    this.renderer.domElement.style.cursor = type ? 'crosshair' : '';
    // cancel any in-progress connection
    if (type) this._cancelConnection();
  }

  setViewMode(mode) {
    this.viewMode = mode;
    if (mode === 'flat') {
      // true top-down: camera directly above target, up = -Z
      const t = this.controls.target;
      this.camera.up.set(0, 0, -1);
      this.camera.position.set(t.x, 60, t.z);
      this.camera.lookAt(t);
      this.controls.update();
      this._showDotGrid(true);
    } else {
      // isometric
      this.camera.up.set(0, 1, 0);
      const t = this.controls.target;
      const d = 35;
      this._tweenCamera(t.clone().add(new THREE.Vector3(d, d, d)));
      this._showDotGrid(false);
    }
  }

  // ── Placement System (grid-based, relative coords) ────────

  async handleDrop(type, clientX, clientY) {
    if (!DEFS[type] || !GRID[type]) return null;
    this._hidePreview();

    const g = GRID[type];
    const pos = this._screenToGround(clientX, clientY);
    if (!pos) return null;

    if (this.currentLevelId === null) {
      // MAIN WORLD
      if (g.cat !== 'machine') {
        // dropping non-machine onto world → check if over a hort
        const hortId = this.worldGrid.hortAt(pos.x, pos.z);
        if (hortId) return await this._addChild(hortId, type);
        return null;
      }
      const gx = Math.round(pos.x - g.innerW / 2);
      const gz = Math.round(pos.z - g.innerD / 2);
      if (!this.worldGrid.canPlace(gx, gz, g.innerW, g.innerD).valid) return null;
      return await this._placeMachineHort(type, gx, gz);
    } else {
      // INSIDE A CONTAINER (isolated view)
      if (g.cat === 'machine') return null;
      return await this._addChild(this.currentLevelId, type);
    }
  }

  /** Place a machine hort in the world grid. */
  async _placeMachineHort(type, gx, gz) {
    const g = GRID[type];
    const def = DEFS[type];
    const id = this._nextId++;
    const mesh = await createComponentMeshAsync(type);
    mesh.position.set(gx + g.innerW / 2, 0, gz + g.innerD / 2);
    mesh.userData.componentId = id;

    mesh.scale.set(0, 0, 0);
    this._tweenScale(mesh, 1, 350);
    this.scene.add(mesh);

    this.worldGrid.occupy(id, gx, gz, g.innerW, g.innerD);

    const comp = {
      mesh, type, name: displayName(type),
      _labelEl: makeHtmlLabel(displayName(type), this.labelOverlay),
      children: [], parentId: null,
      gridX: gx, gridZ: gz,
      footW: g.innerW, footD: g.innerD,
      innerW: g.innerW, innerD: g.innerD,
      internalGrid: new InternalGrid(g.innerW, g.innerD),
      relX: 0, relZ: 0,
    };
    this.components.set(id, comp);
    this._checkWorldGrowth();
    this.history.push({ type: 'place', compId: id, compType: type, gridX: gx, gridZ: gz });
    this._emitCounts();
    return { id, type, name: comp.name };
  }

  /** Add a child (sub-hort or tool) into a container. */
  async _addChild(parentId, type) {
    const parent = this.components.get(parentId);
    if (!parent || !parent.internalGrid) return null;
    const g = GRID[type];
    const def = DEFS[type];
    const fw = g.footW || 1;
    const fd = g.footD || 1;

    // find space in parent's internal grid
    let slot = parent.internalGrid.findSpace(fw, fd);
    if (!slot) {
      // grow until space found (try wider, then taller, repeat)
      for (let attempt = 0; attempt < 20 && !slot; attempt++) {
        parent.internalGrid.grow(parent.innerW + 1, parent.innerD);
        parent.innerW += 1;
        slot = parent.internalGrid.findSpace(fw, fd);
        if (slot) break;
        parent.internalGrid.grow(parent.innerW, parent.innerD + 1);
        parent.innerD += 1;
        slot = parent.internalGrid.findSpace(fw, fd);
      }
      if (!slot) return null;
      // if parent is a machine hort, resize world grid
      if (parent.parentId === null) {
        this.worldGrid.vacate(parentId);
        if (!this.worldGrid.canPlace(parent.gridX, parent.gridZ, parent.innerW, parent.innerD).valid) {
          return null;
        }
        this.worldGrid.occupy(parentId, parent.gridX, parent.gridZ, parent.innerW, parent.innerD);
        parent.footW = parent.innerW;
        parent.footD = parent.innerD;
        await this._rebuildContainerMesh(parentId);
      }
    }

    const id = this._nextId++;
    parent.internalGrid.occupy(id, slot.x, slot.z, fw, fd);
    const mesh = await createComponentMeshAsync(type);
    mesh.userData.componentId = id;
    mesh.scale.set(0, 0, 0);
    this._tweenScale(mesh, 1, 300);
    this.scene.add(mesh);

    const hasInner = g.cat === 'subhort';
    const comp = {
      mesh, type, name: displayName(type),
      _labelEl: makeHtmlLabel(displayName(type), this.labelOverlay),
      children: [], parentId,
      relX: slot.x, relZ: slot.z,
      footW: fw, footD: fd,
      innerW: hasInner ? (g.innerW || 4) : null,
      innerD: hasInner ? (g.innerD || 4) : null,
      internalGrid: hasInner ? new InternalGrid(g.innerW || 4, g.innerD || 4) : null,
      gridX: 0, gridZ: 0,
    };
    this.components.set(id, comp);
    parent.children.push(id);

    this._updateLevelView();
    this._emitCounts();
    return { id, type, name: comp.name };
  }

  /** Rebuild a container's 3D mesh after resize (full dispose + recreate). */
  async _rebuildContainerMesh(compId) {
    const comp = this.components.get(compId);
    if (!comp) return;
    const def = DEFS[comp.type];
    const g = GRID[comp.type];

    // Compute visual size from current inner dimensions
    let w, d;
    if (g.cat === 'machine') {
      w = comp.innerW + 0.7;
      d = comp.innerD + 0.7;
    } else {
      w = comp.footW || vizSize(comp.type).w;
      d = comp.footD || vizSize(comp.type).d;
    }

    // Try GLB first, fall back to procedural
    let newGroup = await loadGLBModel(comp.type);
    if (!newGroup) {
      newGroup = buildComponentMesh(comp.type, w, d);
    }
    const ports = getPorts(comp.type);
    const bodyDef = getBodyDef(comp.type);
    const h = bodyDef.wallHeight || bodyDef.height || 1;
    addPorts(newGroup, { w, d, h, ports });
    newGroup.userData.compType = comp.type;
    newGroup.userData.componentId = compId;

    // Position
    if (comp.parentId === null) {
      newGroup.position.set(comp.gridX + comp.innerW / 2, 0, comp.gridZ + comp.innerD / 2);
    } else {
      newGroup.position.copy(comp.mesh.position);
    }

    // Preserve feet offset
    if (def.feet) newGroup.position.y = comp.mesh.position.y;

    // Swap in scene
    const wasSelected = this.selectedId === compId;
    this.scene.remove(comp.mesh);
    comp.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    this.scene.add(newGroup);
    comp.mesh = newGroup;

    // Re-apply selection glow
    if (wasSelected) this._setGlow(compId, true);

    // Rebuild attached connections
    this._rebuildConnectionsFor(compId);
  }

  // ── Level View Rendering ──────────────────────────────────

  /**
   * Position and scale all meshes based on the current navigation level.
   * - World view: machine horts at world coords, children miniature inside.
   * - Isolated view: current container's children at 1:1, others hidden.
   */
  _updateLevelView() {
    if (this.currentLevelId === null) {
      this._renderWorldView();
    } else {
      this._renderIsolatedView(this.currentLevelId);
    }
  }

  _renderWorldView() {
    this.components.forEach((comp, id) => {
      if (comp.parentId === null) {
        // machine hort — visible at world position
        comp.mesh.visible = true;
        comp.mesh.position.set(comp.gridX + comp.innerW / 2, 0, comp.gridZ + comp.innerD / 2);
        comp.mesh.scale.set(1, 1, 1);
      } else {
        // child — render miniature inside parent chain
        this._positionInAncestorView(comp, id);
      }
    });
    // connections
    this.connections.forEach(conn => {
      const fv = this.components.get(conn.from.compId)?.mesh.visible;
      const tv = this.components.get(conn.to.compId)?.mesh.visible;
      conn.mesh.visible = fv && tv;
    });
  }

  _renderIsolatedView(containerId) {
    const container = this.components.get(containerId);
    if (!container) return;

    this.components.forEach((comp, id) => {
      if (id === containerId) {
        // the container itself — visible as the "room" (walls + floor)
        comp.mesh.visible = true;
        // position so its internal grid origin is at (0,0)
        const g = GRID[comp.type];
        const wall = g?.wall || 0.15;
        comp.mesh.position.set(comp.innerW / 2, 0, comp.innerD / 2);
        comp.mesh.scale.set(1, 1, 1);
      } else if (comp.parentId === containerId) {
        // direct children — visible at relative grid position, full 1:1 scale
        comp.mesh.visible = true;
        comp.mesh.position.set(comp.relX + comp.footW / 2, 0.05, comp.relZ + comp.footD / 2);
        comp.mesh.scale.set(1, 1, 1);
        // show their sub-children as miniatures
        for (const gcId of comp.children) {
          this._positionInParentView(this.components.get(gcId), gcId, comp, id);
        }
      } else if (this._isDescendantOf(id, containerId) && comp.parentId !== containerId) {
        // handled by _positionInParentView above
      } else {
        comp.mesh.visible = false;
      }
    });

    // connections: only show if both endpoints are inside this container
    this.connections.forEach(conn => {
      const fromComp = this.components.get(conn.from.compId);
      const toComp = this.components.get(conn.to.compId);
      const fromInside = fromComp && (fromComp.parentId === containerId || conn.from.compId === containerId);
      const toInside = toComp && (toComp.parentId === containerId || conn.to.compId === containerId);
      conn.mesh.visible = fromInside && toInside;
    });
  }

  /** Position a child as a miniature inside its parent's footprint in the current view. */
  _positionInAncestorView(comp, id) {
    const parent = this.components.get(comp.parentId);
    if (!parent) { comp.mesh.visible = false; return; }

    if (!parent.mesh.visible) { comp.mesh.visible = false; return; }

    // scale: parent footprint / parent internal size
    const scaleX = (parent.footW || parent.innerW) / (parent.innerW || 1);
    const scaleZ = (parent.footD || parent.innerD) / (parent.innerD || 1);
    const scale = Math.min(scaleX, scaleZ);

    // position relative to parent mesh center
    const parentPos = parent.mesh.position;
    const halfW = (parent.footW || parent.innerW) / 2;
    const halfD = (parent.footD || parent.innerD) / 2;

    const wx = parentPos.x - halfW + (comp.relX + comp.footW / 2) * scaleX;
    const wz = parentPos.z - halfD + (comp.relZ + comp.footD / 2) * scaleZ;

    comp.mesh.visible = true;
    comp.mesh.position.set(wx, parent.mesh.position.y + 0.1, wz);
    comp.mesh.scale.set(scale, scale, scale);
  }

  /** Position a grandchild as miniature inside its parent (in isolated view). */
  _positionInParentView(comp, id, parent, parentId) {
    if (!comp) return;
    const scaleX = parent.footW / (parent.innerW || 1);
    const scaleZ = parent.footD / (parent.innerD || 1);
    const scale = Math.min(scaleX, scaleZ);

    const px = parent.mesh.position;
    const wx = px.x - parent.footW / 2 + (comp.relX + comp.footW / 2) * scaleX;
    const wz = px.z - parent.footD / 2 + (comp.relZ + comp.footD / 2) * scaleZ;

    comp.mesh.visible = true;
    comp.mesh.position.set(wx, px.y + 0.1, wz);
    comp.mesh.scale.set(scale, scale, scale);
  }

  _isDescendantOf(childId, ancestorId) {
    let cur = this.components.get(childId);
    while (cur) {
      if (cur.parentId === ancestorId) return true;
      cur = this.components.get(cur.parentId);
    }
    return false;
  }

  removeComponent(id) {
    const comp = this.components.get(id);
    if (!comp) return;

    // remove children recursively
    for (const childId of [...comp.children]) this.removeComponent(childId);

    // remove connections involving this component
    this.connections = this.connections.filter(c => {
      if (c.from.compId === id || c.to.compId === id) {
        this.scene.remove(c.mesh);
        c.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
        return false;
      }
      return true;
    });

    // unparent + vacate from parent's internal grid
    if (comp.parentId !== null) {
      const parent = this.components.get(comp.parentId);
      if (parent) {
        parent.children = parent.children.filter(c => c !== id);
        parent.internalGrid?.vacate(id);
      }
    }

    this.scene.remove(comp.mesh);
    comp.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    if (comp._labelEl) { comp._labelEl.remove(); comp._labelEl = null; }
    this.worldGrid.vacate(id);
    this.components.delete(id);

    if (this.selectedId === id) { this.selectedId = null; this.cb.onDeselect?.(); }
    this._checkWorldGrowth();
    this._emitCounts();
  }

  selectComponent(id) {
    if (this.selectedId === id) return;
    this.deselectConnection();
    if (this.selectedId !== null) this._setGlow(this.selectedId, false);
    this.selectedId = id;
    if (id !== null) {
      this._setGlow(id, true);
      this.cb.onSelect?.(this._compData(id));
    }
  }

  deselectAll() {
    if (this.selectedId !== null) this._setGlow(this.selectedId, false);
    this.selectedId = null;
    this.cb.onDeselect?.();
  }

  enterComponent(id) {
    const comp = this.components.get(id);
    if (!comp || !comp.internalGrid) return; // must be a container

    this.levelStack.push({
      id: this.currentLevelId,
      name: this.currentLevelId ? this.components.get(this.currentLevelId)?.name ?? '?' : 'Infrastructure',
    });
    this.currentLevelId = id;

    this._updateLevelView();

    // zoom into the internal grid — fill the screen with the hort contents
    const iw = comp.innerW || 4;
    const ih = comp.innerD || 4;
    const center = new THREE.Vector3(iw / 2, 0, ih / 2);
    this.controls.target.copy(center);

    // set zoom to fit the internal grid
    const frustumH = this.camera.top - this.camera.bottom; // 28
    this.camera.zoom = Math.max(0.3, frustumH / (Math.max(iw, ih) * 2.2));
    this.camera.updateProjectionMatrix();

    const camD = Math.max(iw, ih) * 0.6 + 3;
    this._tweenCamera(center.clone().add(new THREE.Vector3(camD, camD, camD)));

    this.deselectAll();
    this._emitLevelChange();
  }

  exitLevel() {
    if (!this.levelStack.length) return;
    const prev = this.levelStack.pop();
    this.currentLevelId = prev.id;

    this._updateLevelView();

    if (this.currentLevelId === null) {
      this.controls.target.set(0, 0, 0);
      this._tweenCamera(new THREE.Vector3(35, 35, 35));
    } else {
      const comp = this.components.get(this.currentLevelId);
      if (comp) {
        const center = new THREE.Vector3((comp.innerW || 4) / 2, 0, (comp.innerD || 4) / 2);
        this.controls.target.copy(center);
        const d = Math.max(comp.innerW || 4, comp.innerD || 4) + 8;
        this._tweenCamera(center.clone().add(new THREE.Vector3(d, d, d)));
      }
    }
    this._emitLevelChange();
  }

  navigateToRoot() {
    while (this.levelStack.length) this.exitLevel();
  }

  navigateToLevel(id) {
    while (this.levelStack.length && this.currentLevelId !== id) this.exitLevel();
  }

  /** Jump camera to origin, show whole world, navigate to root level. */
  goHome() {
    this.navigateToRoot();
    this.controls.target.set(0, 0, 0);
    // zoom to fit world: frustumSize / worldSize ≈ needed zoom
    const frustumH = this.camera.top - this.camera.bottom; // base frustum height (28)
    this.camera.zoom = Math.max(0.15, frustumH / (this.worldSize * 1.5));
    this.camera.updateProjectionMatrix();
    if (this.viewMode === 'flat') {
      this.camera.up.set(0, 0, -1);
      this.camera.position.set(0, 60, 0);
    } else {
      this.camera.up.set(0, 1, 0);
      const d = 35;
      this.camera.position.set(d, d, d);
    }
    this.camera.lookAt(this.controls.target);
    this.controls.update();
    this._updateLevelView();
  }

  /** Undo last action — rebuilds world from snapshot. */
  async undo() {
    const action = this.history.undo();
    if (!action) return;
    await this._applyAction(action, true); // reverse
  }

  /** Redo last undone action. */
  async redo() {
    const action = this.history.redo();
    if (!action) return;
    await this._applyAction(action, false); // forward
  }

  async _applyAction(action, reverse) {
    if (action.type === 'place') {
      if (reverse) {
        this.removeComponent(action.compId);
      } else {
        await this._placeMachineHort(action.compType, action.gridX, action.gridZ);
      }
    } else if (action.type === 'addChild') {
      if (reverse) {
        this.removeComponent(action.compId);
      } else {
        await this._addChild(action.parentId, action.compType);
      }
    } else if (action.type === 'move') {
      const id = action.compId;
      const comp = this.components.get(id);
      if (!comp) return;
      const gx = reverse ? action.oldX : action.newX;
      const gz = reverse ? action.oldZ : action.newZ;
      this.worldGrid.move(id, gx, gz);
      comp.gridX = gx;
      comp.gridZ = gz;
      comp.mesh.position.set(gx + (comp.footW || 1) / 2, 0, gz + (comp.footD || 1) / 2);
      this._rebuildConnectionsFor(id);
    } else if (action.type === 'remove') {
      // undo remove = re-add (simplified: we store the serialized state before removal)
      if (reverse && action.snapshot) {
        // TODO: restore from snapshot
      }
    }
    this._updateLevelView();
    this._emitCounts();
  }

  /** Export world state as YAML-compatible JSON. */
  exportState() {
    return serializeWorld(this);
  }

  /** Resize a container by delta grid steps. */
  async resizeContainer(id, dw, dd) {
    const comp = this.components.get(id);
    if (!comp || comp.innerW == null) return;

    const newW = Math.max(2, comp.innerW + dw);
    const newD = Math.max(2, comp.innerD + dd);
    if (newW === comp.innerW && newD === comp.innerD) return;

    // check children still fit
    if (comp.internalGrid) {
      const bb = comp.internalGrid.boundingBox();
      if (newW < bb.maxX || newD < bb.maxZ) return; // children would overflow
    }

    const oldW = comp.innerW, oldD = comp.innerD;
    comp.innerW = newW;
    comp.innerD = newD;
    if (comp.internalGrid) comp.internalGrid.grow(newW, newD);

    // update world grid if machine hort
    if (comp.parentId === null) {
      this.worldGrid.vacate(id);
      if (!this.worldGrid.canPlace(comp.gridX, comp.gridZ, newW, newD).valid) {
        comp.innerW = oldW; comp.innerD = oldD; // revert
        this.worldGrid.occupy(id, comp.gridX, comp.gridZ, oldW, oldD);
        return;
      }
      this.worldGrid.occupy(id, comp.gridX, comp.gridZ, newW, newD);
      comp.footW = newW;
      comp.footD = newD;
    }

    await this._rebuildContainerMesh(id);
    this._updateLevelView();
    this.history.push({ type: 'resize', compId: id, oldW, oldD, newW, newD });
  }

  /** Set the trust level of a hort (trusted, sandboxed, untrusted). */
  setTrust(id, trust) {
    const comp = this.components.get(id);
    if (!comp) return;
    comp.trust = trust || null;
    // Visual: tint the container border based on trust
    const trustColors = { trusted: 0x22c55e, sandboxed: 0xeab308, untrusted: 0xef4444 };
    const color = trustColors[trust];
    if (color) {
      comp.mesh.traverse(c => {
        if (c.isMesh && c.userData?.isWall) {
          c.material = c.material.clone();
          c.material.emissive = new THREE.Color(color);
          c.material.emissiveIntensity = 0.15;
        }
      });
    } else {
      // clear tint
      comp.mesh.traverse(c => {
        if (c.isMesh && c.userData?.isWall) {
          c.material.emissiveIntensity = 0;
        }
      });
    }
    this.cb.onSelect?.(this._compData(id));
  }

  updateProperty(id, key, value) {
    const comp = this.components.get(id);
    if (!comp) return;
    if (key === 'name') {
      comp.name = value;
      if (comp._labelEl) comp._labelEl.textContent = value;
    }
  }

  // ── Presets ──────────────────────────────────────────────

  clearAll() {
    for (const conn of this.connections) {
      this.scene.remove(conn.mesh);
      conn.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    }
    this.connections = [];
    for (const [, comp] of this.components) {
      this.scene.remove(comp.mesh);
      comp.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
      if (comp._labelEl) comp._labelEl.remove();
    }
    this.components.clear();
    if (this.labelOverlay) this.labelOverlay.innerHTML = '';
    this.selectedId = null;
    this.currentLevelId = null;
    this.levelStack = [];
    this._cancelConnection();
    this._dragging = null;
    this._dragCandidate = null;
    this.worldGrid.clear();
    this.worldSize = 20;
    this._rebuildWorldBorder();
    this.cb.onDeselect?.();
    this._emitCounts();
    this._emitLevelChange();
  }

  async loadPreset(preset) {
    if (!preset?.components) return; // guard: not a hort preset
    this.clearAll();
    const idMap = new Map();

    // 1. place machine horts first (world grid)
    let firstMachineId = null;
    for (let i = 0; i < preset.components.length; i++) {
      const c = preset.components[i];
      if (c.parent !== undefined) continue;
      const g = GRID[c.type];
      if (g?.cat === 'machine') {
        const gx = Math.round(c.x ?? 0);
        const gz = Math.round(c.z ?? 0);
        const data = await this._placeMachineHort(c.type, gx, gz);
        if (data) {
          idMap.set(i, data.id);
          if (!firstMachineId) firstMachineId = data.id;
          const comp = this.components.get(data.id);
          if (comp) comp.name = c.name;
        }
      }
    }

    // 2. place children inside their parents (and orphan tools into first machine)
    for (let i = 0; i < preset.components.length; i++) {
      const c = preset.components[i];
      const g = GRID[c.type];
      let parentId;
      if (c.parent !== undefined) {
        parentId = idMap.get(c.parent);
      } else if (g?.cat !== 'machine') {
        // orphan tool/subhort — put in first machine hort
        parentId = firstMachineId;
      } else {
        continue; // machine hort already placed
      }
      if (!parentId) continue;
      const data = await this._addChild(parentId, c.type);
      if (data) {
        idMap.set(i, data.id);
        const comp = this.components.get(data.id);
        if (comp) comp.name = c.name;
      }
    }

    // 3. connections (support [fi,fp,ti,tp] or [fi,fp,ti,tp,security])
    for (const connDef of preset.connections) {
      const [fi, fp, ti, tp, security] = connDef;
      const sec = security || 'none';
      const fromId = idMap.get(fi);
      const toId = idMap.get(ti);
      if (fromId == null || toId == null) continue;
      const ep = this._connEndpoints(fromId, toId);
      const mesh = createConnectionMesh(ep.fromPos, ep.toPos, ep.fromNormal, ep.toNormal, sec);
      this.scene.add(mesh);
      this.connections.push({
        id: this._nextConnId++,
        from: { compId: fromId, portType: 'output', portIndex: 0 },
        to: { compId: toId, portType: 'input', portIndex: 0 },
        mesh, security: sec,
      });
    }

    this._checkWorldGrowth();
    this._centerCamera();
    this._updateLevelView();
    this._emitCounts();
  }

  _centerCamera() {
    if (this.components.size === 0) return;
    const center = new THREE.Vector3();
    let count = 0;
    this.components.forEach(c => {
      if (c.parentId === null) { center.add(c.mesh.position); count++; }
    });
    if (count === 0) return;
    center.divideScalar(count);
    this.controls.target.copy(center);
    const d = this.viewMode === 'flat' ? 0.01 : 35;
    const y = this.viewMode === 'flat' ? 55 : 35;
    this._tweenCamera(center.clone().add(new THREE.Vector3(d, y, d)));
  }

  resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w < 10 || h < 10) return;  // skip while collapsed / hidden
    const size = 28;
    const aspect = w / h;
    this.camera.left   = -size * aspect / 2;
    this.camera.right  =  size * aspect / 2;
    this.camera.top    =  size / 2;
    this.camera.bottom = -size / 2;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.composer.setSize(w, h);
  }

  dispose() {
    this._ro?.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    cancelAnimationFrame(this._rafId);
  }

  // (Legacy nesting/visibility removed — replaced by _updateLevelView)

  // ── Connections ───────────────────────────────────────────

  _startConnection(compId) {
    this._connectingFrom = { compId };
    // preview line from component center
    const comp = this.components.get(compId);
    if (!comp) return;
    const fromPos = comp.mesh.position.clone();
    fromPos.y += DEFS[comp.type]?.h * 0.5 + 0.15 || 1;
    const geo = new THREE.BufferGeometry().setFromPoints([fromPos, fromPos.clone()]);
    this._previewLine = new THREE.Line(geo, new THREE.LineBasicMaterial({
      color: C.conn, transparent: true, opacity: 0.5,
    }));
    this.scene.add(this._previewLine);
  }

  _updatePreview(clientX, clientY) {
    if (!this._previewLine) return;
    const pos = this._screenToGround(clientX, clientY);
    if (!pos) return;
    pos.y = 0.5;
    const arr = this._previewLine.geometry.attributes.position.array;
    arr[3] = pos.x; arr[4] = pos.y; arr[5] = pos.z;
    this._previewLine.geometry.attributes.position.needsUpdate = true;
  }

  _endConnection(compId) {
    if (!this._connectingFrom) return;
    const fromId = this._connectingFrom.compId;
    if (fromId === compId) { this._cancelConnection(); return; }

    const ep = this._connEndpoints(fromId, compId);
    const security = 'none';
    const mesh = createConnectionMesh(ep.fromPos, ep.toPos, ep.fromNormal, ep.toNormal, security);
    this.scene.add(mesh);

    this.connections.push({
      id: this._nextConnId++,
      from: { compId: fromId, portType: 'output', portIndex: 0 },
      to:   { compId,         portType: 'input',  portIndex: 0 },
      mesh, security,
    });
    this._cancelConnection();
    this._emitCounts();
  }

  _cancelConnection() {
    if (this._previewLine) {
      this.scene.remove(this._previewLine);
      this._previewLine.geometry.dispose();
      this._previewLine = null;
    }
    this._connectingFrom = null;
  }

  // ── Selection highlight ───────────────────────────────────

  _setGlow(id, on) {
    const comp = this.components.get(id);
    if (!comp) return;
    comp.mesh.traverse(c => {
      if (!c.isMesh || c.userData.isPort || c.userData.isLabel) return;
      if (on) {
        c._origEmissive = c.material.emissive?.getHex() ?? 0;
        c._origEmissiveI = c.material.emissiveIntensity ?? 0;
        c.material = c.material.clone();
        c.material.emissive = new THREE.Color(C.selected);
        c.material.emissiveIntensity = 0.12; // subtle tint, object stays visible
      } else if (c._origEmissive !== undefined) {
        c.material.emissive = new THREE.Color(c._origEmissive);
        c.material.emissiveIntensity = c._origEmissiveI;
      }
    });
  }

  // ── Descendant repositioning (for drag preview) ────────────

  /** Reposition all descendants of a component based on current mesh positions. */
  _repositionDescendants(parentId) {
    const parent = this.components.get(parentId);
    if (!parent) return;
    for (const childId of parent.children) {
      const child = this.components.get(childId);
      if (!child) continue;
      this._positionInAncestorView(child, childId);
      this._repositionDescendants(childId); // recurse for grandchildren
    }
  }

  /** Rebuild connections for a component AND all its descendants. */
  _rebuildConnectionTree(compId) {
    this._rebuildConnectionsFor(compId);
    const comp = this.components.get(compId);
    if (!comp) return;
    for (const childId of comp.children) {
      this._rebuildConnectionTree(childId);
    }
  }

  // ── Drag tint (red on collision) ───────────────────────────

  _setDragTint(id, collision) {
    const comp = this.components.get(id);
    if (!comp) return;
    const tintColor = collision ? 0xef4444 : 0x000000;
    const intensity = collision ? 0.35 : 0;
    comp.mesh.traverse(c => {
      if (!c.isMesh || c.userData?.isPort || c.userData?.isLabel) return;
      if (!c._dragOrigEmissive && c._dragOrigEmissive !== 0) {
        c._dragOrigEmissive = c.material.emissive?.getHex() ?? 0;
        c._dragOrigEmissiveI = c.material.emissiveIntensity ?? 0;
        c.material = c.material.clone();
      }
      if (collision) {
        c.material.emissive.setHex(tintColor);
        c.material.emissiveIntensity = intensity;
      } else {
        c.material.emissive.setHex(c._dragOrigEmissive);
        c.material.emissiveIntensity = c._dragOrigEmissiveI;
      }
    });
  }

  _clearDragTint(id) {
    const comp = this.components.get(id);
    if (!comp) return;
    comp.mesh.traverse(c => {
      if (c._dragOrigEmissive !== undefined) {
        c.material.emissive.setHex(c._dragOrigEmissive);
        c.material.emissiveIntensity = c._dragOrigEmissiveI;
        delete c._dragOrigEmissive;
        delete c._dragOrigEmissiveI;
      }
    });
  }

  // ── Auto-routing: best face pair ───────────────────────────

  /** Pick the best face on each component for a connection between them. */
  _bestFacePair(fromId, toId) {
    const fc = this.components.get(fromId);
    const tc = this.components.get(toId);
    if (!fc || !tc) return { fromFace: 'right', toFace: 'left' };
    const dx = tc.mesh.position.x - fc.mesh.position.x;
    const dz = tc.mesh.position.z - fc.mesh.position.z;
    if (Math.abs(dx) >= Math.abs(dz)) {
      return dx >= 0
        ? { fromFace: 'right', toFace: 'left' }
        : { fromFace: 'left', toFace: 'right' };
    }
    return dz >= 0
      ? { fromFace: 'front', toFace: 'back' }
      : { fromFace: 'back', toFace: 'front' };
  }

  /** World position + outward normal on a component face.
   *  spread = horizontal offset along the wall tangent (separates in/out).
   *  isFrom: true = output (offset one way), false = input (offset other way). */
  _facePos(compId, face, spread = 0, isFrom = true) {
    const comp = this.components.get(compId);
    if (!comp) return { pos: new THREE.Vector3(), normal: new THREE.Vector3(1, 0, 0) };
    const sz = vizSize(comp.type);
    const def = DEFS[comp.type];
    const h = def.h;
    const sign = isFrom ? -1 : 1;
    let lx = 0, lz = 0, nx = 0, nz = 0;
    switch (face) {
      case 'right':
        lx = sz.w / 2; nx = 1;
        lz = sign * Math.min(spread, sz.d * 0.3);
        break;
      case 'left':
        lx = -sz.w / 2; nx = -1;
        lz = sign * Math.min(spread, sz.d * 0.3);
        break;
      case 'front':
        lz = sz.d / 2; nz = 1;
        lx = sign * Math.min(spread, sz.w * 0.3);
        break;
      case 'back':
        lz = -sz.d / 2; nz = -1;
        lx = sign * Math.min(spread, sz.w * 0.3);
        break;
    }
    const local = new THREE.Vector3(lx, h * 0.5 + 0.15, lz);
    comp.mesh.updateMatrixWorld();
    return { pos: local.applyMatrix4(comp.mesh.matrixWorld), normal: new THREE.Vector3(nx, 0, nz) };
  }

  /** Build both endpoints for a connection, auto-picking faces. */
  _connEndpoints(fromId, toId) {
    const { fromFace, toFace } = this._bestFacePair(fromId, toId);
    const spread = 0.35;
    const from = this._facePos(fromId, fromFace, spread, true);
    const to   = this._facePos(toId,   toFace,  spread, false);
    return { fromPos: from.pos, fromNormal: from.normal, toPos: to.pos, toNormal: to.normal };
  }

  // ── Connection selection & security ────────────────────────

  selectConnection(connId) {
    // deselect any component first
    if (this.selectedId !== null) { this._setGlow(this.selectedId, false); this.selectedId = null; }
    if (this.selectedConnId === connId) return;
    if (this.selectedConnId !== null) this._setConnGlow(this.selectedConnId, false);
    this.selectedConnId = connId;
    if (connId !== null) {
      this._setConnGlow(connId, true);
      this.cb.onSelectConnection?.(this._connData(connId));
    }
  }

  deselectConnection() {
    if (this.selectedConnId !== null) this._setConnGlow(this.selectedConnId, false);
    this.selectedConnId = null;
    this.cb.onDeselectConnection?.();
  }

  /** Remove a connection by id. */
  removeConnection(connId) {
    const idx = this.connections.findIndex(c => c.id === connId);
    if (idx === -1) return;
    const conn = this.connections[idx];
    this.scene.remove(conn.mesh);
    conn.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    this.connections.splice(idx, 1);
    if (this.selectedConnId === connId) { this.selectedConnId = null; this.cb.onDeselectConnection?.(); }
    this._emitCounts();
  }

  /** Change security level of a connection and rebuild its mesh. */
  setConnectionSecurity(connId, level) {
    const conn = this.connections.find(c => c.id === connId);
    if (!conn) return;
    conn.security = level;
    const ep = this._connEndpoints(conn.from.compId, conn.to.compId);
    this.scene.remove(conn.mesh);
    conn.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    conn.mesh = createConnectionMesh(ep.fromPos, ep.toPos, ep.fromNormal, ep.toNormal, level);
    this.scene.add(conn.mesh);
    if (this.selectedConnId === connId) {
      this._setConnGlow(connId, true);
      this.cb.onSelectConnection?.(this._connData(connId));
    }
  }

  _setConnGlow(connId, on) {
    const conn = this.connections.find(c => c.id === connId);
    if (!conn) return;
    conn.mesh.traverse(c => {
      if (!c.isMesh || !c.userData?.isConnTube) return;
      if (on) {
        c.material = c.material.clone();
        c.material.emissiveIntensity = 1.8;
        c.material.opacity = 1.0;
      } else {
        c.material.emissiveIntensity = 0.6;
        c.material.opacity = 0.75;
      }
    });
  }

  _connData(connId) {
    const conn = this.connections.find(c => c.id === connId);
    if (!conn) return null;
    const fromComp = this.components.get(conn.from.compId);
    const toComp = this.components.get(conn.to.compId);
    return {
      id: connId,
      fromName: fromComp?.name || '?',
      toName: toComp?.name || '?',
      fromType: fromComp?.type || '?',
      toType: toComp?.type || '?',
      security: conn.security || 'none',
    };
  }

  _raycastConnections() {
    const targets = [];
    this.connections.forEach(conn => {
      if (!conn.mesh.visible) return;
      conn.mesh.traverse(c => { if (c.userData?.isConnTube) targets.push(c); });
    });
    return this.raycaster.intersectObjects(targets);
  }

  _findConnectionByTube(tubeObj) {
    for (const conn of this.connections) {
      let found = false;
      conn.mesh.traverse(c => { if (c === tubeObj) found = true; });
      if (found) return conn;
    }
    return null;
  }

  // ── Events ────────────────────────────────────────────────

  _bindEvents() {
    const el = this.renderer.domElement;

    el.addEventListener('pointerdown', e => {
      if (e.button !== 0) return; // left-click only
      this._pointerStart = { x: e.clientX, y: e.clientY, time: performance.now() };
      this._dragCandidate = null;
      this._dragging = null;

      // if no tool and not connecting, check if we clicked a component (drag candidate)
      if (!this.activeTool && !this._connectingFrom) {
        const mouse = this._ndcFromEvent(e);
        this.raycaster.setFromCamera(mouse, this.camera);

        // skip ports — they handle connections, not dragging
        const portHits = this._raycastPorts();
        if (portHits.length) return;

        const compHits = this._raycastComponents();
        if (compHits.length) {
          const compMesh = this._findComponentParent(compHits[0].object);
          if (compMesh) {
            this._dragCandidate = compMesh.userData.componentId;
            this.controls.enabled = false; // disable orbit so it doesn't compete with drag
            // compute offset so the component doesn't jump to cursor center
            const groundPos = this._screenToGround(e.clientX, e.clientY);
            if (groundPos) {
              const comp = this.components.get(this._dragCandidate);
              this._dragOffset.copy(comp.mesh.position).sub(groundPos);
            }
          }
        }
      }
    });

    el.addEventListener('pointermove', e => {
      // connection preview
      this._updatePreview(e.clientX, e.clientY);

      // drag-to-move component
      if (this._dragCandidate && this._pointerStart) {
        const dx = Math.abs(e.clientX - this._pointerStart.x);
        const dy = Math.abs(e.clientY - this._pointerStart.y);
        if (dx + dy > 6 && !this._dragging) {
          // promote candidate to active drag
          this._dragging = this._dragCandidate;
          this.controls.enabled = false;
          this.selectComponent(this._dragging);
          this.renderer.domElement.style.cursor = 'grabbing';
        }
      }

      if (this._dragging) {
        const pos = this._screenToGround(e.clientX, e.clientY);
        if (pos) {
          const comp = this.components.get(this._dragging);
          if (!comp) return;
          const fw = comp.footW || 1;
          const fd = comp.footD || 1;

          if (comp.parentId === null && this.currentLevelId === null) {
            // ── Machine hort in world view ──
            const gx = Math.round(pos.x + this._dragOffset.x - fw / 2);
            const gz = Math.round(pos.z + this._dragOffset.z - fd / 2);
            comp.mesh.position.set(gx + fw / 2, 0, gz + fd / 2);
            // Move descendants with parent (don't call _updateLevelView — it resets parent pos)
            this._repositionDescendants(this._dragging);
            this._rebuildConnectionTree(this._dragging);
            // Collision check — tint mesh red if invalid
            const { valid } = this.worldGrid.canPlace(gx, gz, fw, fd, this._dragging);
            this._setDragTint(this._dragging, !valid);
            comp._pendingGridX = gx;
            comp._pendingGridZ = gz;
            // Grow world if dragging near edge
            this._checkWorldGrowth(gx, gz, fw, fd);
          } else if (comp.parentId !== null && this.currentLevelId === comp.parentId) {
            // ── Child in isolated view only ──
            const parentId = comp.parentId;
            const parent = this.components.get(parentId);
            if (!parent) return;

            // Compute target grid position (clamped to ≥ 0)
            let gx = Math.max(0, Math.round(pos.x + this._dragOffset.x - fw / 2));
            let gz = Math.max(0, Math.round(pos.z + this._dragOffset.z - fd / 2));

            // Auto-grow: only when child would exceed bounds, grow by 1 cell at a time
            const maxX = gx + fw;
            const maxZ = gz + fd;
            if (maxX > parent.innerW || maxZ > parent.innerD) {
              const newW = Math.max(parent.innerW, maxX + 1);  // +1 breathing room
              const newD = Math.max(parent.innerD, maxZ + 1);
              let canGrow = true;
              if (parent.parentId === null) {
                this.worldGrid.vacate(parentId);
                canGrow = this.worldGrid.canPlace(parent.gridX, parent.gridZ, newW, newD).valid;
                if (canGrow) {
                  parent.innerW = newW; parent.innerD = newD;
                  parent.footW = newW; parent.footD = newD;
                  this.worldGrid.occupy(parentId, parent.gridX, parent.gridZ, newW, newD);
                } else {
                  this.worldGrid.occupy(parentId, parent.gridX, parent.gridZ, parent.innerW, parent.innerD);
                }
              } else {
                parent.innerW = newW; parent.innerD = newD;
              }
              if (canGrow) {
                parent.internalGrid?.grow(newW, newD);
                this._rebuildContainerMesh(parentId);
                parent.mesh.position.set(parent.innerW / 2, 0, parent.innerD / 2);
                this._checkWorldGrowth();
              }
              // Clamp if growth was blocked
              if (!canGrow) {
                gx = Math.min(gx, parent.innerW - fw);
                gz = Math.min(gz, parent.innerD - fd);
              }
            }

            // Clamp to parent bounds
            gx = Math.max(0, Math.min(gx, parent.innerW - fw));
            gz = Math.max(0, Math.min(gz, parent.innerD - fd));

            comp.mesh.position.set(gx + fw / 2, 0.05, gz + fd / 2);
            this._rebuildConnectionTree(this._dragging);
            comp._pendingRelX = gx;
            comp._pendingRelZ = gz;
          }
        }
        return;
      }

      this._highlightPort(e);
    });

    el.addEventListener('pointerup', e => {
      if (e.button !== 0) return;

      // finalize drag-to-move
      if (this._dragging) {
        const id = this._dragging;
        this._dragging = null;
        this._dragCandidate = null;
        this._pointerStart = null;
        this.controls.enabled = true;
        this.renderer.domElement.style.cursor = '';
        this._clearDragTint(id);

        const comp = this.components.get(id);
        if (comp && comp._pendingGridX !== undefined) {
          // Machine hort world move
          const gx = comp._pendingGridX;
          const gz = comp._pendingGridZ;
          delete comp._pendingGridX;
          delete comp._pendingGridZ;
          const fw = comp.footW || 1;
          const oldX = comp.gridX, oldZ = comp.gridZ;
          if (this.worldGrid.move(id, gx, gz)) {
            comp.gridX = gx;
            comp.gridZ = gz;
            comp.mesh.position.set(gx + fw / 2, 0, gz + (comp.footD || 1) / 2);
            this.history.push({ type: 'move', compId: id, oldX, oldZ, newX: gx, newZ: gz });
          } else {
            comp.mesh.position.set(comp.gridX + fw / 2, 0, comp.gridZ + (comp.footD || 1) / 2);
          }
        } else if (comp && comp._pendingRelX !== undefined) {
          // Child internal grid move
          const rx = comp._pendingRelX;
          const rz = comp._pendingRelZ;
          delete comp._pendingRelX;
          delete comp._pendingRelZ;
          const parent = this.components.get(comp.parentId);
          if (parent?.internalGrid?.move(id, rx, rz)) {
            comp.relX = rx;
            comp.relZ = rz;
            comp.mesh.position.set(rx + (comp.footW || 1) / 2, 0.05, rz + (comp.footD || 1) / 2);
          } else {
            comp.mesh.position.set(comp.relX + (comp.footW || 1) / 2, 0.05, comp.relZ + (comp.footD || 1) / 2);
          }
        }
        this._rebuildConnectionsFor(id);
        this._updateLevelView();
        return;
      }

      this._dragCandidate = null;
      this.controls.enabled = true; // re-enable orbit (was disabled on component click)
      this._onPointerClick(e);
    });

    el.addEventListener('dblclick', e => this._onDblClick(e));
    el.addEventListener('contextmenu', e => {
      if (this._connectingFrom) { e.preventDefault(); this._cancelConnection(); }
    });

    // drag & drop with grid preview
    for (const target of [el, this.container]) {
      target.addEventListener('dragover', e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        this._updateDropPreview(e);
      });
      target.addEventListener('dragleave', () => { this._hidePreview(); });
      target.addEventListener('drop', e => {
        e.preventDefault();
        e.stopPropagation();
        this._hidePreview();
        const type = e.dataTransfer.getData('text/plain');
        if (type) this.handleDrop(type, e.clientX, e.clientY);
      });
    }
  }

  /** Handle a left-click (pointer up with < 6px movement). */
  _onPointerClick(e) {
    if (!this._pointerStart) return;
    const dx = Math.abs(e.clientX - this._pointerStart.x);
    const dy = Math.abs(e.clientY - this._pointerStart.y);
    const dt = performance.now() - this._pointerStart.time;
    this._pointerStart = null;

    if (dx + dy > 6 || dt > 400) return; // was an orbit drag

    const mouse = this._ndcFromEvent(e);
    this.raycaster.setFromCamera(mouse, this.camera);

    // 1. ports → start / end connection (any side, universal)
    const portHits = this._raycastPorts();
    if (portHits.length) {
      const hit = portHits[0].object;
      const compMesh = this._findComponentParent(hit);
      if (compMesh) {
        const compId = compMesh.userData.componentId;
        if (this._connectingFrom) {
          this._endConnection(compId);
        } else {
          this._startConnection(compId);
        }
        return;
      }
    }

    // 2. cancel connection on empty click
    if (this._connectingFrom) { this._cancelConnection(); return; }

    // 3. check connections (wire click)
    const connHits = this._raycastConnections();
    if (connHits.length) {
      const conn = this._findConnectionByTube(connHits[0].object);
      if (conn) {
        this.deselectAll();
        this.selectConnection(conn.id);
        return;
      }
    }

    // 4. select component
    const compHits = this._raycastComponents();
    if (compHits.length) {
      const compMesh = this._findComponentParent(compHits[0].object);
      if (compMesh) {
        this.deselectConnection();
        this.selectComponent(compMesh.userData.componentId);
        return;
      }
    }

    // 5. deselect all
    this.deselectAll();
    this.deselectConnection();
  }

  _onDblClick(e) {
    const mouse = this._ndcFromEvent(e);
    this.raycaster.setFromCamera(mouse, this.camera);
    const hits = this._raycastComponents();
    if (hits.length) {
      const compMesh = this._findComponentParent(hits[0].object);
      if (compMesh) {
        const id = compMesh.userData.componentId;
        const comp = this.components.get(id);
        if (comp && comp.internalGrid) this.enterComponent(id);
      }
    }
  }

  _highlightPort(e) {
    // Hide previously highlighted glows
    if (this._highlightedCompId) {
      const prev = this.components.get(this._highlightedCompId);
      if (prev) prev.mesh.traverse(c => { if (c.userData?.isPortGlow) c.visible = false; });
      this._highlightedCompId = null;
    }

    const mouse = this._ndcFromEvent(e);
    this.raycaster.setFromCamera(mouse, this.camera);

    // Check ports first (precise hover)
    const portHits = this._raycastPorts();
    if (portHits.length) {
      const compMesh = this._findComponentParent(portHits[0].object);
      if (compMesh) {
        const compId = compMesh.userData.componentId;
        this._showAllPortGlows(compId);
        this.renderer.domElement.style.cursor = 'pointer';
        return;
      }
    }

    // Check component body (show port glows when hovering anywhere on the object)
    const compHits = this._raycastComponents();
    if (compHits.length) {
      const compMesh = this._findComponentParent(compHits[0].object);
      if (compMesh) {
        const compId = compMesh.userData.componentId;
        this._showAllPortGlows(compId);
        // Only show pointer cursor if actually over a port
        if (!this.activeTool && !this._dragging) this.renderer.domElement.style.cursor = '';
        return;
      }
    }

    if (!this.activeTool && !this._dragging) this.renderer.domElement.style.cursor = '';
  }

  /** Show all 4 port glows on a component. */
  _showAllPortGlows(compId) {
    const comp = this.components.get(compId);
    if (!comp) return;
    comp.mesh.traverse(c => { if (c.userData?.isPortGlow) c.visible = true; });
    this._highlightedCompId = compId;
  }

  /** Rebuild all connections attached to a component (after it moves). */
  _rebuildConnectionsFor(compId) {
    for (const conn of this.connections) {
      if (conn.from.compId !== compId && conn.to.compId !== compId) continue;
      const ep = this._connEndpoints(conn.from.compId, conn.to.compId);
      this.scene.remove(conn.mesh);
      conn.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
      conn.mesh = createConnectionMesh(ep.fromPos, ep.toPos, ep.fromNormal, ep.toNormal, conn.security || 'none');
      this.scene.add(conn.mesh);
    }
  }

  // ── Raycast helpers ───────────────────────────────────────

  _ndcFromEvent(e) {
    const rect = this.container.getBoundingClientRect();
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
  }

  _screenToGround(clientX, clientY) {
    const rect = this.container.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = new THREE.Vector3();
    const ok = this.raycaster.ray.intersectPlane(this._groundPlane, hit);
    return ok ? hit : null;
  }

  _raycastPorts() {
    const targets = [];
    this.components.forEach(comp => {
      if (!comp.mesh.visible) return;
      comp.mesh.traverse(c => { if (c.userData?.isPort) targets.push(c); });
    });
    return this.raycaster.intersectObjects(targets);
  }

  _raycastComponents() {
    const targets = [];
    this.components.forEach(comp => {
      if (!comp.mesh.visible) return;
      comp.mesh.traverse(c => {
        if (c.isMesh && !c.userData?.isPort && !c.userData?.isLabel) targets.push(c);
      });
    });
    return this.raycaster.intersectObjects(targets);
  }

  _findComponentParent(obj) {
    while (obj) {
      if (obj.userData?.componentId) return obj;
      obj = obj.parent;
    }
    return null;
  }

  // ── Tweens / animation helpers ────────────────────────────

  _tweenCamera(targetPos, duration = 900) {
    this._cameraTween = {
      start: this.camera.position.clone(),
      target: targetPos.clone(),
      t0: performance.now(),
      dur: duration,
    };
  }

  _tweenScale(mesh, target, duration) {
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

  // ── Helpers ───────────────────────────────────────────────

  _compData(id) {
    const comp = this.components.get(id);
    if (!comp) return null;
    const def = DEFS[comp.type];

    // Build ancestry path (root → ... → this component), each with siblings
    const ancestry = [];
    let curId = id;
    while (curId !== null) {
      const c = this.components.get(curId);
      if (!c) break;
      const entry = { id: curId, name: c.name, type: c.type, siblings: [] };
      if (c.parentId !== null) {
        const par = this.components.get(c.parentId);
        if (par) {
          entry.siblings = par.children
            .filter(sid => sid !== curId)
            .map(sid => { const s = this.components.get(sid); return s ? { id: sid, name: s.name, type: s.type } : null; })
            .filter(Boolean);
        }
      } else {
        this.components.forEach((c2, cid) => {
          if (c2.parentId === null && cid !== curId) entry.siblings.push({ id: cid, name: c2.name, type: c2.type });
        });
      }
      ancestry.unshift(entry);
      curId = c.parentId;
    }

    return {
      id, type: comp.type, name: comp.name,
      isContainer: !!comp.internalGrid, children: comp.children.length,
      ports: { ...def.ports },
      innerW: comp.innerW, innerD: comp.innerD,
      footW: comp.footW, footD: comp.footD,
      trust: comp.trust || null,
      ancestry,
    };
  }

  _emitCounts() {
    this.cb.onCountChange?.(this.components.size, this.connections.length);
  }

  _emitLevelChange() {
    // Build breadcrumb: skip the null (world) entry, show only named levels
    const stack = [];
    for (const l of this.levelStack) {
      if (l.id !== null) {
        const comp = this.components.get(l.id);
        stack.push({ id: l.id, name: comp?.name ?? l.name });
      }
    }
    if (this.currentLevelId !== null) {
      const cur = this.components.get(this.currentLevelId);
      stack.push({ id: this.currentLevelId, name: cur?.name ?? '?' });
    }
    this.cb.onLevelChange?.(stack);
  }

  // ── HTML label projection ─────────────────────────────────

  _updateHtmlLabels() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.components.forEach((comp) => {
      const el = comp._labelEl;
      if (!el) return;
      if (!comp.mesh.visible) { el.style.display = 'none'; return; }
      const def = DEFS[comp.type];
      const isContainer = !!comp.internalGrid;
      const sz = vizSize(comp.type);
      const pos = comp.mesh.position.clone();

      if (isContainer) {
        // Containers: label at bottom-front edge, out of the way of children
        pos.y += 0.15;
        pos.z += sz.d / 2 + 0.2;
        el.style.fontSize = '10px';
        el.style.color = '#94a3b8';
      } else {
        // Tools: label above the top
        pos.y += (def?.h || 1) + 0.3;
        el.style.fontSize = '11px';
        el.style.color = '#e2e8f0';
      }

      pos.project(this.camera);
      if (pos.z > 1) { el.style.display = 'none'; return; }
      const sx = (pos.x * 0.5 + 0.5) * w;
      const sy = (-pos.y * 0.5 + 0.5) * h;
      el.style.display = '';
      el.style.transform = `translate(-50%, 0) translate(${sx}px, ${sy}px)`;
    });
  }

  // ── Render loop ───────────────────────────────────────────

  _animate() {
    this._rafId = requestAnimationFrame(() => this._animate());

    const dt = this.clock.getDelta();
    const t = this.clock.getElapsedTime();

    // dynamic grid: always covers entire viewport at any zoom/pan/angle
    const zoom = this.camera.zoom || 1;
    const frustumMax = Math.max(
      (this.camera.right - this.camera.left),
      (this.camera.top - this.camera.bottom)
    ) / zoom;
    // 20× frustum covers the isometric ground projection generously
    const gridScale = Math.max(2, frustumMax * 20 / 200);
    const tx = this.controls.target.x;
    const tz = this.controls.target.z;
    if (this.gridMesh) {
      this.gridMesh.material.uniforms.uTime.value = t;
      this.gridMesh.material.uniforms.uWorldHalf.value = this.worldSize / 2;
      this.gridMesh.scale.set(gridScale, 1, gridScale);
      this.gridMesh.position.set(tx, 0, tz);
    }
    if (this.dotGridMesh) {
      this.dotGridMesh.scale.set(gridScale, 1, gridScale);
      this.dotGridMesh.position.set(tx, 0.01, tz);
    }
    // ground fill: same position/scale, covers horizon
    if (this._groundFill) {
      this._groundFill.scale.set(gridScale * 300, 1, gridScale * 300);
      this._groundFill.position.set(tx, -0.02, tz);
    }

    // camera tween
    if (this._cameraTween) {
      const tw = this._cameraTween;
      const p = Math.min((performance.now() - tw.t0) / tw.dur, 1);
      const ease = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      this.camera.position.lerpVectors(tw.start, tw.target, ease);
      this.camera.lookAt(this.controls.target);
      if (p >= 1) this._cameraTween = null;
    }

    // spinning icospheres (LLMings)
    this.components.forEach(comp => {
      comp.mesh.traverse(c => {
        if (c.userData?.spin) c.rotation.y += dt * 0.6;
      });
    });

    // Project HTML labels to screen positions
    this._updateHtmlLabels();

    // connection flow particles
    this.connections.forEach(conn => {
      const { curve, particles } = conn.mesh.userData;
      if (!curve || !particles) return;
      particles.forEach((p, i) => {
        const flowT = ((t * 0.35 + i / particles.length) % 1);
        const pt = curve.getPointAt(flowT);
        p.position.set(pt.x - conn.mesh.position.x, pt.y - conn.mesh.position.y, pt.z - conn.mesh.position.z);
      });
    });

    this.controls.update();
    // skip render when container is collapsed (avoids zero-size framebuffer errors)
    if (this.container.clientWidth > 10 && this.container.clientHeight > 10) {
      this.composer.render();
    }
  }
}
