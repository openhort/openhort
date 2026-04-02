// ═══════════════════════════════════════════════════════════════
//  HortPlanner Engine — Three.js Isometric Infrastructure Designer
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { WorldGrid, InternalGrid, GRID } from './grid.js';

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
  portIn:    0x3b82f6,
  portOut:   0x22c55e,
  conn:      0xeab308,
  selected:  0x60a5fa,
  floor:     0x0f172a,
};

// ── Component definitions ───────────────────────────────────

// DEFS: visual properties per type. Grid sizing lives in grid.js (GRID).
// w/d are now derived from GRID at runtime for machine horts.
// h = wall height for containers, body height for tools (tools ~2× container to be visible inside walls)
const DEFS = {
  'mac-mini':     { h: 1.0, color: C.macMini, container: true,  metal: 0.85, rough: 0.20, ports: { in: 2, out: 2 }, cornerR: 0.35, feet: true },
  'macbook':      { h: 0.4, color: C.macBook, container: true,  metal: 0.80, rough: 0.25, ports: { in: 2, out: 2 }, screen: true, cornerR: 0.2 },
  'rpi':          { h: 0.5, color: C.rpi,     container: true,  metal: 0.30, rough: 0.70, ports: { in: 1, out: 1 }, cornerR: 0.08 },
  'cloud-vm':     { h: 1.2, color: C.cloudVM, container: true,  metal: 0.10, rough: 0.90, ports: { in: 2, out: 2 }, opacity: 0.55, cornerR: 0.1 },
  'docker':       { h: 1.0, color: C.docker,  container: true,  metal: 0.40, rough: 0.50, ports: { in: 1, out: 1 }, cornerR: 0.1 },
  'virtual-hort': { h: 1.0, color: C.virtual, container: false, metal: 0.10, rough: 0.90, ports: { in: 1, out: 1 }, opacity: 0.45, cornerR: 0.1 },
  'mcp-server':   { h: 2.0, color: C.mcp,     container: false, metal: 0.60, rough: 0.30, ports: { in: 1, out: 1 }, shape: 'hex' },
  'llming':       { h: 2.0, color: C.llming,  container: false, metal: 0.30, rough: 0.50, ports: { in: 2, out: 1 }, shape: 'ico' },
  'program':      { h: 2.0, color: C.program, container: false, metal: 0.50, rough: 0.40, ports: { in: 1, out: 1 }, shape: 'box' },
};

const DISPLAY_NAMES = {
  'mac-mini': 'SnackMini', 'macbook': 'SnackBook Pro',
  'rpi': 'Strawberry Pi', 'cloud-vm': 'Cloud VM',
  'docker': 'Docker', 'virtual-hort': 'Virtual Hort',
  'mcp-server': 'MCP Server', 'llming': 'LLMing', 'program': 'Program',
};
function displayName(type) { return DISPLAY_NAMES[type] || type.replace(/-/g, ' '); }

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

function makeLabel(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 512; canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.font = 'bold 44px -apple-system, "Segoe UI", Roboto, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#0a0e1a';
  ctx.lineWidth = 4;
  ctx.strokeText(text, 256, 64);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, 256, 64);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: tex, transparent: true })
  );
  sprite.scale.set(3, 0.75, 1);
  sprite.userData.isLabel = true;
  return sprite;
}

// ── Factory: ports ──────────────────────────────────────────

function addPorts(group, def) {
  const geo = new THREE.SphereGeometry(0.12, 12, 12);
  const hitGeo = new THREE.SphereGeometry(0.35, 8, 8);

  const makePort = (type, index, x, y, z) => {
    const color = type === 'input' ? C.portIn : C.portOut;
    const g = new THREE.Group();

    // visible sphere
    g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      color, emissive: color, emissiveIntensity: 1.2,
    })));

    // invisible hit area
    const hit = new THREE.Mesh(hitGeo, new THREE.MeshBasicMaterial({ visible: false }));
    hit.userData = { isPort: true, portType: type, portIndex: index };
    g.add(hit);

    g.position.set(x, y, z);
    group.add(g);
  };

  // input ports — left side
  for (let i = 0; i < def.ports.in; i++) {
    const y = (i + 1) / (def.ports.in + 1) * def.h + 0.15;
    makePort('input', i, -def.w / 2 - 0.2, y, 0);
  }
  // output ports — right side
  for (let i = 0; i < def.ports.out; i++) {
    const y = (i + 1) / (def.ports.out + 1) * def.h + 0.15;
    makePort('output', i, def.w / 2 + 0.2, y, 0);
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

  // floor (simple box)
  const ft = 0.08; // floor thickness
  const floor = new THREE.Mesh(new THREE.BoxGeometry(w, ft, d), mat);
  floor.position.y = ft / 2; // sits from y=0 to y=ft
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
  const def = DEFS[type];
  const sz = vizSize(type);
  // merge size into a combined object for factory functions
  const p = { ...def, w: sz.w, d: sz.d };
  let group;

  if (def.container) {
    group = makeContainer(p);
    if (def.screen) addScreen(group, p);
  } else if (def.shape === 'hex') {
    group = makeHexPrism(p);
  } else if (def.shape === 'ico') {
    group = makeIcosphere(p);
  } else {
    group = makeBox(p);
  }

  addPorts(group, p);
  group.userData.compType = type;
  return group;
}

// ── Factory: connection ─────────────────────────────────────

function createConnectionMesh(fromPos, toPos) {
  const mid = new THREE.Vector3().addVectors(fromPos, toPos).multiplyScalar(0.5);
  mid.y += 1.8 + fromPos.distanceTo(toPos) * 0.15;

  const curve = new THREE.QuadraticBezierCurve3(fromPos.clone(), mid, toPos.clone());
  const group = new THREE.Group();

  // tube
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 48, 0.035, 8, false),
    new THREE.MeshStandardMaterial({
      color: C.conn, emissive: C.conn, emissiveIntensity: 0.6,
      transparent: true, opacity: 0.75,
    })
  );
  group.add(tube);

  // flow particles (3 small glowing spheres)
  const pGeo = new THREE.SphereGeometry(0.09, 8, 8);
  const pMat = new THREE.MeshStandardMaterial({
    color: 0xffffff, emissive: C.conn, emissiveIntensity: 2.5,
  });
  const particles = [];
  for (let i = 0; i < 3; i++) {
    const p = new THREE.Mesh(pGeo, pMat);
    group.add(p);
    particles.push(p);
  }

  group.userData.curve = curve;
  group.userData.particles = particles;
  group.userData.isConnection = true;
  return group;
}

// ═══════════════════════════════════════════════════════════════
//  Engine
// ═══════════════════════════════════════════════════════════════

export class HortPlannerEngine {
  constructor(container, callbacks = {}) {
    this.container = container;
    this.cb = callbacks;
    this.components = new Map();   // id → { mesh, type, name, children[], parentId }
    this.connections = [];         // { id, from:{compId,portType,portIdx}, to:{...}, mesh }
    this.selectedId = null;
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
    this._highlightedPorts = [];
    this._dragCandidate = null;   // compId that might be dragged
    this._dragging = null;        // compId currently being dragged
    this._dragOffset = new THREE.Vector3();
    this._dropPreviewType = null; // type being dragged from palette
    this.worldGrid = new WorldGrid();
    this.worldSize = 50;          // initial world: 50×50 centered on origin

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

    // start render loop
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
  _checkWorldGrowth() {
    const half = this.worldSize / 2;
    let needGrow = false;
    this.components.forEach(comp => {
      if (comp.parentId !== null) return;
      const g = GRID[comp.type];
      if (!g) return;
      const margin = 3; // grow when within 3 cells of edge
      const right = comp.gridX + (comp.innerW || 4);
      const bottom = comp.gridZ + (comp.innerD || 4);
      if (right > half - margin || bottom > half - margin ||
          comp.gridX < -half + margin || comp.gridZ < -half + margin) {
        needGrow = true;
      }
    });
    if (needGrow) {
      this.worldSize += 20; // grow by 20 units
      this._rebuildWorldBorder();
    }
  }

  /** Pre-allocate a pool of flat cell planes for drag preview. */
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
      // check if hovering over a hort → show hort highlight
      const hortId = this.worldGrid.hortAt(pos.x, pos.z);
      if (hortId) {
        const comp = this.components.get(hortId);
        if (comp) {
          const cells = this.worldGrid.getContentCells(comp.gridX, comp.gridZ, comp.gridW, comp.gridD);
          this._showPreview(cells, [], true);
          return;
        }
      }
      this._hidePreview();
      return;
    }

    if (g.cat === 'machine' && this.currentLevelId === null) {
      const gx = Math.round(pos.x - g.innerW / 2);
      const gz = Math.round(pos.z - g.innerD / 2);
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

  handleDrop(type, clientX, clientY) {
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
        if (hortId) return this._addChild(hortId, type);
        return null;
      }
      const gx = Math.round(pos.x - g.innerW / 2);
      const gz = Math.round(pos.z - g.innerD / 2);
      if (!this.worldGrid.canPlace(gx, gz, g.innerW, g.innerD).valid) return null;
      return this._placeMachineHort(type, gx, gz);
    } else {
      // INSIDE A CONTAINER (isolated view)
      if (g.cat === 'machine') return null;
      return this._addChild(this.currentLevelId, type);
    }
  }

  /** Place a machine hort in the world grid. */
  _placeMachineHort(type, gx, gz) {
    const g = GRID[type];
    const def = DEFS[type];
    const id = this._nextId++;
    const mesh = createComponentMesh(type);
    mesh.position.set(gx + g.innerW / 2, 0, gz + g.innerD / 2);
    mesh.userData.componentId = id;

    const label = makeLabel(displayName(type));
    label.position.y = def.h + (def.screen ? 2.8 : 0.9);
    mesh.add(label);
    mesh.scale.set(0, 0, 0);
    this._tweenScale(mesh, 1, 350);
    this.scene.add(mesh);

    this.worldGrid.occupy(id, gx, gz, g.innerW, g.innerD);

    const comp = {
      mesh, type, name: displayName(type),
      children: [], parentId: null,
      gridX: gx, gridZ: gz,
      footW: g.innerW, footD: g.innerD,
      innerW: g.innerW, innerD: g.innerD,
      internalGrid: new InternalGrid(g.innerW, g.innerD),
      relX: 0, relZ: 0,
    };
    this.components.set(id, comp);
    this._checkWorldGrowth();
    this._emitCounts();
    return { id, type, name: comp.name };
  }

  /** Add a child (sub-hort or tool) into a container. */
  _addChild(parentId, type) {
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
        this._rebuildContainerMesh(parentId);
      }
    }

    const id = this._nextId++;
    parent.internalGrid.occupy(id, slot.x, slot.z, fw, fd);
    const mesh = createComponentMesh(type);
    mesh.userData.componentId = id;
    const label = makeLabel(displayName(type));
    label.position.y = def.h + 0.6;
    mesh.add(label);
    mesh.scale.set(0, 0, 0);
    this._tweenScale(mesh, 1, 300);
    this.scene.add(mesh);

    const hasInner = g.cat === 'subhort';
    const comp = {
      mesh, type, name: displayName(type),
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

  /** Rebuild a container's 3D mesh after resize. */
  _rebuildContainerMesh(compId) {
    const comp = this.components.get(compId);
    if (!comp) return;
    const def = DEFS[comp.type];
    const g = GRID[comp.type];
    const wall = g.wall || 0.15;
    const w = comp.innerW + wall * 2;
    const d = comp.innerD + wall * 2;
    const h = def.h;
    const t = 0.08;

    comp.mesh.traverse(c => {
      if (!c.userData?.isWall) return;
      const isZ = Math.abs(c.position.z) > Math.abs(c.position.x);
      c.geometry.dispose();
      if (isZ) {
        c.geometry = new THREE.BoxGeometry(w, h, t);
        c.position.z = Math.sign(c.position.z) * (d / 2 - t / 2);
      } else {
        c.geometry = new THREE.BoxGeometry(t, h, d);
        c.position.x = Math.sign(c.position.x) * (w / 2 - t / 2);
      }
      c.position.y = h / 2 + t;
    });

    if (comp.parentId === null) {
      comp.mesh.position.set(comp.gridX + comp.innerW / 2, 0, comp.gridZ + comp.innerD / 2);
    }
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
    this.worldGrid.vacate(id);
    this.components.delete(id);

    if (this.selectedId === id) { this.selectedId = null; this.cb.onDeselect?.(); }
    this._emitCounts();
  }

  selectComponent(id) {
    if (this.selectedId === id) return;
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

  updateProperty(id, key, value) {
    const comp = this.components.get(id);
    if (!comp) return;
    if (key === 'name') {
      comp.name = value;
      // update label
      comp.mesh.children.forEach(c => {
        if (c.userData?.isLabel) {
          comp.mesh.remove(c);
        }
      });
      const def = DEFS[comp.type];
      const label = makeLabel(value);
      label.position.y = def.h + (def.screen ? 2.8 : 0.9);
      comp.mesh.add(label);
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
    }
    this.components.clear();
    this.selectedId = null;
    this.currentLevelId = null;
    this.levelStack = [];
    this._cancelConnection();
    this._dragging = null;
    this._dragCandidate = null;
    this.worldGrid.clear();
    this.worldSize = 50;
    this._rebuildWorldBorder();
    this.cb.onDeselect?.();
    this._emitCounts();
    this._emitLevelChange();
  }

  loadPreset(preset) {
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
        const data = this._placeMachineHort(c.type, gx, gz);
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
      const data = this._addChild(parentId, c.type);
      if (data) {
        idMap.set(i, data.id);
        const comp = this.components.get(data.id);
        if (comp) comp.name = c.name;
      }
    }

    // 3. connections
    for (const [fi, fp, ti, tp] of preset.connections) {
      const fromId = idMap.get(fi);
      const toId = idMap.get(ti);
      if (fromId == null || toId == null) continue;
      const fromPos = this._portWorldPos(fromId, 'output', fp);
      const toPos = this._portWorldPos(toId, 'input', tp);
      const mesh = createConnectionMesh(fromPos, toPos);
      this.scene.add(mesh);
      this.connections.push({
        id: this._nextConnId++,
        from: { compId: fromId, portType: 'output', portIndex: fp },
        to: { compId: toId, portType: 'input', portIndex: tp },
        mesh,
      });
    }

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

  _startConnection(compId, portType, portIndex) {
    this._connectingFrom = { compId, portType, portIndex };

    // create preview line
    const fromPos = this._portWorldPos(compId, portType, portIndex);
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

  _endConnection(compId, portType, portIndex) {
    if (!this._connectingFrom) return;
    if (this._connectingFrom.compId === compId && this._connectingFrom.portIndex === portIndex) {
      this._cancelConnection();
      return;
    }
    // output → input only
    const from = this._connectingFrom.portType === 'output' ? this._connectingFrom : { compId, portType, portIndex };
    const to = this._connectingFrom.portType === 'output' ? { compId, portType, portIndex } : this._connectingFrom;

    if (from.portType !== 'output' || to.portType !== 'input') {
      this._cancelConnection();
      return;
    }

    const fromPos = this._portWorldPos(from.compId, from.portType, from.portIndex);
    const toPos = this._portWorldPos(to.compId, to.portType, to.portIndex);

    const mesh = createConnectionMesh(fromPos, toPos);
    this.scene.add(mesh);

    this.connections.push({ id: this._nextConnId++, from, to, mesh });
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

  _portWorldPos(compId, portType, portIndex) {
    const comp = this.components.get(compId);
    if (!comp) return new THREE.Vector3();
    const def = DEFS[comp.type];
    const sz = vizSize(comp.type);
    const count = portType === 'input' ? def.ports.in : def.ports.out;
    const x = portType === 'input' ? -sz.w / 2 - 0.2 : sz.w / 2 + 0.2;
    const y = (portIndex + 1) / (count + 1) * def.h + 0.15;
    const local = new THREE.Vector3(x, y, 0);
    comp.mesh.updateMatrixWorld();
    return local.applyMatrix4(comp.mesh.matrixWorld);
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
        c.material.emissiveIntensity = 0.35;
      } else if (c._origEmissive !== undefined) {
        c.material.emissive = new THREE.Color(c._origEmissive);
        c.material.emissiveIntensity = c._origEmissiveI;
      }
    });
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
          if (comp && comp.gridW) {
            // snap to grid
            const gx = Math.round(pos.x + this._dragOffset.x - comp.gridW / 2);
            const gz = Math.round(pos.z + this._dragOffset.z - comp.gridD / 2);
            comp.mesh.position.set(gx + comp.gridW / 2, 0, gz + comp.gridD / 2);
            this._rebuildConnectionsFor(this._dragging);
            // show grid preview
            const content = this.worldGrid.getContentCells(gx, gz, comp.gridW, comp.gridD);
            const gap = this.worldGrid.getGapCells(gx, gz, comp.gridW, comp.gridD);
            const { valid } = this.worldGrid.canPlace(gx, gz, comp.gridW, comp.gridD, this._dragging);
            this._showPreview(content, gap, valid);
            comp._pendingGridX = gx;
            comp._pendingGridZ = gz;
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
        this._hidePreview();

        const comp = this.components.get(id);
        if (comp && comp._pendingGridX !== undefined) {
          const gx = comp._pendingGridX;
          const gz = comp._pendingGridZ;
          delete comp._pendingGridX;
          delete comp._pendingGridZ;

          // try to commit the new position
          if (this.worldGrid.move(id, gx, gz)) {
            comp.gridX = gx;
            comp.gridZ = gz;
            comp.mesh.position.set(gx + comp.gridW / 2, 0, gz + comp.gridD / 2);
          } else {
            // revert to original position
            comp.mesh.position.set(comp.gridX + comp.gridW / 2, 0, comp.gridZ + comp.gridD / 2);
          }
        }
        this._rebuildConnectionsFor(id);
        return;
      }

      this._dragCandidate = null;
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

    // 1. ports → start / end connection
    const portHits = this._raycastPorts();
    if (portHits.length) {
      const hit = portHits[0].object;
      const compMesh = this._findComponentParent(hit);
      if (compMesh) {
        const compId = compMesh.userData.componentId;
        if (this._connectingFrom) {
          this._endConnection(compId, hit.userData.portType, hit.userData.portIndex);
        } else {
          this._startConnection(compId, hit.userData.portType, hit.userData.portIndex);
        }
        return;
      }
    }

    // 2. cancel connection on empty click
    if (this._connectingFrom) { this._cancelConnection(); return; }

    // 3. select
    const compHits = this._raycastComponents();
    if (compHits.length) {
      const compMesh = this._findComponentParent(compHits[0].object);
      if (compMesh) { this.selectComponent(compMesh.userData.componentId); return; }
    }

    // 5. deselect
    this.deselectAll();
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
    for (const p of this._highlightedPorts) p.children[0].scale.set(1, 1, 1);
    this._highlightedPorts = [];

    const mouse = this._ndcFromEvent(e);
    this.raycaster.setFromCamera(mouse, this.camera);
    const hits = this._raycastPorts();
    if (hits.length) {
      const portGroup = hits[0].object.parent;
      portGroup.children[0].scale.set(1.6, 1.6, 1.6);
      this._highlightedPorts.push(portGroup);
      this.renderer.domElement.style.cursor = 'pointer';
    } else if (!this.activeTool && !this._dragging) {
      this.renderer.domElement.style.cursor = '';
    }
  }

  /** Rebuild all connections attached to a component (after it moves). */
  _rebuildConnectionsFor(compId) {
    for (const conn of this.connections) {
      if (conn.from.compId !== compId && conn.to.compId !== compId) continue;
      const fromPos = this._portWorldPos(conn.from.compId, conn.from.portType, conn.from.portIndex);
      const toPos = this._portWorldPos(conn.to.compId, conn.to.portType, conn.to.portIndex);
      // dispose old
      this.scene.remove(conn.mesh);
      conn.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
      // create new
      conn.mesh = createConnectionMesh(fromPos, toPos);
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
    return {
      id, type: comp.type, name: comp.name,
      isContainer: !!comp.internalGrid, children: comp.children.length,
      ports: { ...def.ports },
      innerW: comp.innerW, innerD: comp.innerD,
      footW: comp.footW, footD: comp.footD,
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

    // zoom-independent label sizing
    const labelScale = 1.0 / (this.camera.zoom || 1);
    this.components.forEach(comp => {
      comp.mesh.traverse(c => {
        if (c.userData?.isLabel) {
          c.scale.set(3 * labelScale, 0.75 * labelScale, 1);
        }
      });
    });

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
