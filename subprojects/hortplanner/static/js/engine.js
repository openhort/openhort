// ═══════════════════════════════════════════════════════════════
//  HortPlanner Engine — Three.js Isometric Infrastructure Designer
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

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

const DEFS = {
  'mac-mini':     { w: 5,   h: 1.0, d: 5,   color: C.macMini, container: true,  metal: 0.85, rough: 0.20, ports: { in: 2, out: 2 } },
  'macbook':      { w: 5,   h: 0.8, d: 4,   color: C.macBook, container: true,  metal: 0.80, rough: 0.25, ports: { in: 2, out: 2 }, screen: true },
  'rpi':          { w: 3.5, h: 0.5, d: 4,   color: C.rpi,     container: true,  metal: 0.30, rough: 0.70, ports: { in: 1, out: 1 } },
  'cloud-vm':     { w: 5,   h: 1.5, d: 5,   color: C.cloudVM, container: true,  metal: 0.10, rough: 0.90, ports: { in: 2, out: 2 }, opacity: 0.55 },
  'docker':       { w: 2.0, h: 1.2, d: 2.0, color: C.docker,  container: true,  metal: 0.40, rough: 0.50, ports: { in: 1, out: 1 } },
  'virtual-hort': { w: 2.0, h: 1.0, d: 2.0, color: C.virtual, container: false, metal: 0.10, rough: 0.90, ports: { in: 1, out: 1 }, opacity: 0.45 },
  'mcp-server':   { w: 1.0, h: 1.1, d: 1.0, color: C.mcp,     container: false, metal: 0.60, rough: 0.30, ports: { in: 1, out: 1 }, shape: 'hex' },
  'llming':       { w: 1.0, h: 1.0, d: 1.0, color: C.llming,  container: false, metal: 0.30, rough: 0.50, ports: { in: 2, out: 1 }, shape: 'ico' },
  'program':      { w: 1.0, h: 1.0, d: 1.0, color: C.program, container: false, metal: 0.50, rough: 0.40, ports: { in: 1, out: 1 }, shape: 'box' },
};

// ── Shaders ─────────────────────────────────────────────────

const GRID_VS = `
varying vec3 vWorld;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

const GRID_FS = `
uniform float uTime;
uniform vec3 uMinor;
uniform vec3 uMajor;
varying vec3 vWorld;

void main() {
  vec2 c = vWorld.xz;

  // minor grid (every 1 unit)
  vec2 g1 = abs(fract(c - 0.5) - 0.5) / fwidth(c);
  float minor = 1.0 - min(min(g1.x, g1.y), 1.0);

  // major grid (every 5 units)
  vec2 g5 = abs(fract(c / 5.0 - 0.5) - 0.5) / fwidth(c / 5.0);
  float major = 1.0 - min(min(g5.x, g5.y), 1.0);

  // fade at edges
  float dist = length(c) / 35.0;
  float fade = 1.0 - smoothstep(0.4, 1.0, dist);

  // subtle pulse
  float pulse = 0.93 + 0.07 * sin(uTime * 0.4);

  vec3 col = uMinor * minor * 0.35 + uMajor * major * 0.55;
  float a = (minor * 0.12 + major * 0.30) * fade * pulse;

  gl_FragColor = vec4(col * fade, a);
}`;

// ── Factory: labels ─────────────────────────────────────────

function makeLabel(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 512; canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.font = 'bold 44px -apple-system, "Segoe UI", Roboto, sans-serif';
  ctx.fillStyle = '#e2e8f0';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 256, 64);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
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

// ── Factory: open-top container ─────────────────────────────

function makeContainer(def) {
  const { w, h, d, color, metal, rough } = def;
  const t = 0.08;
  const group = new THREE.Group();

  const mat = new THREE.MeshStandardMaterial({
    color, metalness: metal, roughness: rough, side: THREE.DoubleSide,
    transparent: !!def.opacity, opacity: def.opacity ?? 1,
  });

  // floor
  const floor = new THREE.Mesh(new THREE.BoxGeometry(w, t, d), mat);
  floor.position.y = t / 2;
  floor.receiveShadow = true;
  group.add(floor);

  // walls — front / back
  for (const zSign of [1, -1]) {
    const wall = new THREE.Mesh(new THREE.BoxGeometry(w, h, t), mat);
    wall.position.set(0, h / 2 + t, zSign * (d / 2 - t / 2));
    wall.castShadow = true;
    wall.userData.isWall = true;
    group.add(wall);
  }
  // walls — left / right
  for (const xSign of [-1, 1]) {
    const wall = new THREE.Mesh(new THREE.BoxGeometry(t, h, d), mat);
    wall.position.set(xSign * (w / 2 - t / 2), h / 2 + t, 0);
    wall.castShadow = true;
    wall.userData.isWall = true;
    group.add(wall);
  }

  // dark interior floor
  const inner = new THREE.Mesh(
    new THREE.PlaneGeometry(w - t * 4, d - t * 4),
    new THREE.MeshStandardMaterial({ color: C.floor, roughness: 0.95 })
  );
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = t + 0.005;
  inner.receiveShadow = true;
  group.add(inner);

  // LED indicator on front face
  const led = new THREE.Mesh(
    new THREE.SphereGeometry(0.06, 8, 8),
    new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: 0x22c55e, emissiveIntensity: 3 })
  );
  led.position.set(0, h * 0.35, d / 2 + 0.01);
  group.add(led);

  return group;
}

// ── Factory: screen (MacBook) ───────────────────────────────

function addScreen(group, def) {
  const { w, h, d } = def;
  const screenH = 2.2, screenT = 0.06;

  const hinge = new THREE.Group();
  hinge.position.set(0, h + 0.08, -d / 2 + 0.04);
  hinge.rotation.x = 0.18; // lean back slightly

  const shell = new THREE.Mesh(
    new THREE.BoxGeometry(w, screenH, screenT),
    new THREE.MeshStandardMaterial({ color: def.color, metalness: 0.8, roughness: 0.25 })
  );
  shell.position.y = screenH / 2;
  shell.castShadow = true;
  hinge.add(shell);

  const display = new THREE.Mesh(
    new THREE.PlaneGeometry(w - 0.3, screenH - 0.3),
    new THREE.MeshStandardMaterial({ color: 0x111827, emissive: 0x0a1628, emissiveIntensity: 0.5 })
  );
  display.position.set(0, screenH / 2, screenT / 2 + 0.002);
  hinge.add(display);

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
  let group;

  if (def.container) {
    group = makeContainer(def);
    if (def.screen) addScreen(group, def);
  } else if (def.shape === 'hex') {
    group = makeHexPrism(def);
  } else if (def.shape === 'ico') {
    group = makeIcosphere(def);
  } else {
    group = makeBox(def);
  }

  addPorts(group, def);
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

    this._init();
  }

  // ── Setup ───────────────────────────────────────────────

  _init() {
    // ensure container has size (Quasar layout may not have rendered yet)
    let w = this.container.clientWidth || 800;
    let h = this.container.clientHeight || 600;

    // scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(C.bg);
    this.scene.fog = new THREE.FogExp2(C.bg, 0.012);

    // camera (orthographic for true isometric)
    const size = 28;
    const aspect = w / h;
    this.camera = new THREE.OrthographicCamera(
      -size * aspect / 2, size * aspect / 2,
      size / 2, -size / 2, 0.1, 500
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

    // lighting
    this.scene.add(new THREE.AmbientLight(0x404060, 0.7));

    const dir = new THREE.DirectionalLight(0xffffff, 1.3);
    dir.position.set(15, 30, 20);
    dir.castShadow = true;
    dir.shadow.mapSize.set(2048, 2048);
    const sc = dir.shadow.camera;
    sc.near = 1; sc.far = 80;
    sc.left = sc.bottom = -25; sc.right = sc.top = 25;
    this.scene.add(dir);

    this.scene.add(new THREE.HemisphereLight(0x3b82f6, 0x0f172a, 0.4));

    // grid
    this._createGrid();

    // ambient particles
    this._createParticles();

    // controls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI / 2.1;
    this.controls.minZoom = 0.25;
    this.controls.maxZoom = 5;
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
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
    const geo = new THREE.PlaneGeometry(120, 120);
    geo.rotateX(-Math.PI / 2);
    this.gridMesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
      vertexShader: GRID_VS,
      fragmentShader: GRID_FS,
      uniforms: {
        uTime: { value: 0 },
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

  _createParticles() {
    const count = 300;
    const positions = new Float32Array(count * 3);
    const spread = 60;
    for (let i = 0; i < count; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * spread;
      positions[i * 3 + 1] = Math.random() * 18;
      positions[i * 3 + 2] = (Math.random() - 0.5) * spread;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.particleSystem = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0x3b82f6, size: 0.08, transparent: true, opacity: 0.35,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    this.scene.add(this.particleSystem);
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
      this.controls.enableRotate = false;
      this._tweenCamera(new THREE.Vector3(0.01, 45, 0.01));
    } else {
      this.controls.enableRotate = true;
      const d = 35;
      this._tweenCamera(new THREE.Vector3(d, d, d));
    }
  }

  handleDrop(type, clientX, clientY) {
    if (!DEFS[type]) return null;
    const pos = this._screenToGround(clientX, clientY);
    if (!pos) return null;
    pos.x = Math.round(pos.x);
    pos.z = Math.round(pos.z);
    return this.addComponent(type, pos);
  }

  addComponent(type, worldPos, name) {
    const id = this._nextId++;
    const def = DEFS[type];
    const mesh = createComponentMesh(type);
    mesh.position.copy(worldPos);
    mesh.userData.componentId = id;

    // label
    const label = makeLabel(name || type.replace(/-/g, ' '));
    label.position.y = def.h + (def.screen ? 2.8 : 0.9);
    mesh.add(label);

    // entrance animation
    mesh.scale.set(0, 0, 0);
    this._tweenScale(mesh, 1, 350);

    this.scene.add(mesh);
    const comp = { mesh, type, name: name || type.replace(/-/g, ' '), children: [], parentId: null };
    this.components.set(id, comp);

    // check if placed inside a container
    this._tryNestInContainer(id, worldPos);

    this._emitCounts();
    return { id, type, name: comp.name };
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

    // unparent
    if (comp.parentId !== null) {
      const parent = this.components.get(comp.parentId);
      if (parent) parent.children = parent.children.filter(c => c !== id);
    }

    this.scene.remove(comp.mesh);
    comp.mesh.traverse(o => { if (o.geometry) o.geometry.dispose(); });
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
    if (!comp || !DEFS[comp.type].container) return;

    // push current level
    this.levelStack.push({ id: this.currentLevelId, name: this.currentLevelId ? this.components.get(this.currentLevelId)?.name ?? '?' : 'Infrastructure' });
    this.currentLevelId = id;

    // hide siblings, show only this container's children
    this._applyVisibility();

    // zoom camera to the component
    const target = comp.mesh.position.clone();
    this.controls.target.copy(target);
    const d = 18;
    this._tweenCamera(target.clone().add(new THREE.Vector3(d, d, d)));

    this.deselectAll();
    this._emitLevelChange();
  }

  exitLevel() {
    if (!this.levelStack.length) return;
    const prev = this.levelStack.pop();
    this.currentLevelId = prev.id;
    this._applyVisibility();
    this.controls.target.set(0, 0, 0);
    const d = 35;
    this._tweenCamera(new THREE.Vector3(d, d, d));
    this._emitLevelChange();
  }

  navigateToRoot() {
    while (this.levelStack.length) this.exitLevel();
  }

  navigateToLevel(id) {
    // pop stack until we reach the desired level
    while (this.levelStack.length && this.currentLevelId !== id) this.exitLevel();
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
    this.cb.onDeselect?.();
    this._emitCounts();
    this._emitLevelChange();
  }

  loadPreset(preset) {
    this.clearAll();
    const idMap = new Map();

    // 1. create all components
    for (let i = 0; i < preset.components.length; i++) {
      const c = preset.components[i];
      const pos = new THREE.Vector3(c.x, 0, c.z);
      const data = this.addComponent(c.type, pos, c.name);
      idMap.set(i, data.id);
    }

    // 2. parent-child relationships
    for (let i = 0; i < preset.components.length; i++) {
      const c = preset.components[i];
      if (c.parent === undefined) continue;
      const childId = idMap.get(i);
      const parentId = idMap.get(c.parent);
      const child = this.components.get(childId);
      const parent = this.components.get(parentId);
      if (child && parent) {
        child.parentId = parentId;
        parent.children.push(childId);
      }
    }
    // grow containers after all children are assigned
    const grownSet = new Set();
    for (let i = 0; i < preset.components.length; i++) {
      const c = preset.components[i];
      if (c.parent !== undefined) {
        const pid = idMap.get(c.parent);
        if (!grownSet.has(pid)) { grownSet.add(pid); this._growContainer(pid); }
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
    this._applyVisibility();
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

  // ── Nesting ───────────────────────────────────────────────

  _tryNestInContainer(childId, worldPos) {
    const child = this.components.get(childId);
    if (!child) return;

    // find best container at worldPos (largest first to prefer top-level)
    let bestId = null;
    let bestArea = -1;
    this.components.forEach((comp, cid) => {
      if (cid === childId) return;
      const def = DEFS[comp.type];
      if (!def.container) return;
      const p = comp.mesh.position;
      const hw = def.w / 2 - 0.2, hd = def.d / 2 - 0.2;
      if (worldPos.x > p.x - hw && worldPos.x < p.x + hw &&
          worldPos.z > p.z - hd && worldPos.z < p.z + hd) {
        const area = def.w * def.d;
        if (area > bestArea) { bestArea = area; bestId = cid; }
      }
    });

    if (bestId !== null) {
      child.parentId = bestId;
      this.components.get(bestId).children.push(childId);
      // grow container walls if needed
      this._growContainer(bestId);
    }
  }

  _growContainer(containerId) {
    const comp = this.components.get(containerId);
    if (!comp) return;
    const def = DEFS[comp.type];
    const baseH = def.h;

    // find tallest child
    let maxTop = 0;
    for (const cid of comp.children) {
      const ch = this.components.get(cid);
      if (!ch) continue;
      const chDef = DEFS[ch.type];
      const localY = ch.mesh.position.y - comp.mesh.position.y;
      maxTop = Math.max(maxTop, localY + chDef.h + 0.4);
    }

    const newH = Math.max(baseH, maxTop);
    if (Math.abs(newH - baseH) < 0.01) return;

    // update walls
    comp.mesh.traverse(c => {
      if (!c.userData?.isWall) return;
      // determine if it's a front/back or left/right wall
      const isXWall = Math.abs(c.position.x) > 0.5;
      if (isXWall) {
        c.geometry.dispose();
        c.geometry = new THREE.BoxGeometry(0.08, newH, def.d);
      } else {
        c.geometry.dispose();
        c.geometry = new THREE.BoxGeometry(def.w, newH, 0.08);
      }
      c.position.y = newH / 2 + 0.08;
    });

    // update label position
    comp.mesh.children.forEach(c => {
      if (c.userData?.isLabel) c.position.y = newH + (def.screen ? 2.8 : 0.9);
    });
  }

  // ── Visibility for multi-layer ────────────────────────────

  _applyVisibility() {
    this.components.forEach((comp, id) => {
      if (this.currentLevelId === null) {
        // top level: show only root components (no parent)
        comp.mesh.visible = comp.parentId === null;
      } else {
        // inside a container: show the container itself + its children
        comp.mesh.visible = id === this.currentLevelId || comp.parentId === this.currentLevelId;
      }
    });

    // also show/hide connections
    this.connections.forEach(conn => {
      const fromVis = this.components.get(conn.from.compId)?.mesh.visible;
      const toVis = this.components.get(conn.to.compId)?.mesh.visible;
      conn.mesh.visible = fromVis && toVis;
    });
  }

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
    const count = portType === 'input' ? def.ports.in : def.ports.out;
    const x = portType === 'input' ? -def.w / 2 - 0.2 : def.w / 2 + 0.2;
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
          if (comp) {
            comp.mesh.position.x = Math.round(pos.x + this._dragOffset.x);
            comp.mesh.position.z = Math.round(pos.z + this._dragOffset.z);
            this._rebuildConnectionsFor(this._dragging);
          }
        }
        return; // don't run port highlight while dragging
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
        // re-check nesting
        const comp = this.components.get(id);
        if (comp) {
          // un-parent first
          if (comp.parentId !== null) {
            const parent = this.components.get(comp.parentId);
            if (parent) parent.children = parent.children.filter(c => c !== id);
            comp.parentId = null;
          }
          this._tryNestInContainer(id, comp.mesh.position);
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

    // drag & drop — must attach directly to the <canvas> AND the container
    for (const target of [el, this.container]) {
      target.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
      target.addEventListener('drop', e => {
        e.preventDefault();
        e.stopPropagation(); // prevent double-fire from bubbling
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
        if (comp && DEFS[comp.type].container) this.enterComponent(id);
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
      isContainer: def.container, children: comp.children.length,
      ports: { ...def.ports },
    };
  }

  _emitCounts() {
    this.cb.onCountChange?.(this.components.size, this.connections.length);
  }

  _emitLevelChange() {
    const stack = this.levelStack.map(l => ({
      id: l.id,
      name: l.name,
    }));
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

    // grid time
    if (this.gridMesh) this.gridMesh.material.uniforms.uTime.value = t;

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

    // ambient particles drift upward
    if (this.particleSystem) {
      const pos = this.particleSystem.geometry.attributes.position.array;
      for (let i = 1; i < pos.length; i += 3) {
        pos[i] += dt * 0.08;
        if (pos[i] > 18) pos[i] = 0;
      }
      this.particleSystem.geometry.attributes.position.needsUpdate = true;
    }

    this.controls.update();
    // skip render when container is collapsed (avoids zero-size framebuffer errors)
    if (this.container.clientWidth > 10 && this.container.clientHeight > 10) {
      this.composer.render();
    }
  }
}
