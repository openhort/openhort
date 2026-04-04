// ═══════════════════════════════════════════════════════════════
//  HomePlannerEngine — Three.js Isometric Home / Apartment Editor
//
//  Draws walls on grid edges, places doors/windows/furniture,
//  detects rooms via flood-fill, supports multi-floor buildings.
//  Shares scene setup with engine-base.js.
// ═══════════════════════════════════════════════════════════════

import { THREE, OrbitControls, createScene, createGrid, createDotGrid,
         makeHtmlLabel, tweenScale, updateGridUniforms, projectToScreen,
         COLORS, getParticleGlowTexture } from './engine-base.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { HomeGrid, RoomDetector } from './grid-home.js';

// ── GLB model cache and loader ────────────────────────────

const _glbCache = new Map(); // type -> THREE.Group (template)
const _glbLoader = new GLTFLoader();

/** Load a GLB model, clone from cache if already loaded. Returns a THREE.Group. */
async function loadModel(type) {
    if (_glbCache.has(type)) {
        return _glbCache.get(type).clone();
    }
    try {
        const gltf = await _glbLoader.loadAsync(`/static/models/glb/${type}.glb`);
        const model = gltf.scene;
        _glbCache.set(type, model);
        return model.clone();
    } catch (e) {
        console.warn(`GLB not found for ${type}, using fallback box`);
        return null;
    }
}

// ── Furniture definitions (loaded from manifest-home.json) ──

let FURNITURE_DEFS = {};
let _manifestLoaded = false;
let _presetCache = []; // loaded from individual JSON files

/** Load the home manifest and preset index. */
async function loadHomeManifest(basePath = '/static') {
  if (_manifestLoaded) return;
  try {
    const res = await fetch(`${basePath}/models/manifest-home.json`);
    const data = await res.json();
    // Convert manifest components to FURNITURE_DEFS format
    for (const [key, comp] of Object.entries(data.components || {})) {
      if (!comp.body?.width) continue; // skip door/window catalog entries without dimensions
      FURNITURE_DEFS[key] = {
        w: comp.body.width,
        d: comp.body.depth || comp.body.width,
        h: comp.body.height || 1,
        color: parseInt((comp.material?.color || '#888888').replace('#', ''), 16),
        label: comp.displayName || key,
        shape: comp.body.shape || 'box',
        icon: comp.icon || 'widgets',
        category: comp.category || 'other',
        features: comp.features || {},
        animations: comp.animations || {},
      };
    }
  } catch (e) { console.warn('manifest-home.json load failed, using defaults', e); }
  // Load preset index
  try {
    const presetFiles = [
      '01-studio-apartment', '02-one-bedroom', '03-two-bedroom',
      '04-loft-apartment', '05-small-house', '06-two-story-house',
      '07-split-level-home', '08-apartment-basement',
      '09-open-plan-penthouse', '10-tiny-house',
    ];
    _presetCache = await Promise.all(
      presetFiles.map(f => fetch(`${basePath}/presets/home/${f}.json`).then(r => r.json()).catch(() => null))
    );
    _presetCache = _presetCache.filter(Boolean);
  } catch (e) { console.warn('preset load failed', e); }
  _manifestLoaded = true;
}

// ── Room floor colors ──────────────────────────────────────

const ROOM_COLORS = [
  0xfaf5ef, // warm cream
  0xf0ebe3, // beige
  0xe8e4df, // light taupe
  0xd4e4d9, // sage green
  0xd6e4f0, // light blue
  0xf0e4d7, // peach
  0xe8ddd4, // warm gray
  0xd4d8e4, // lavender gray
];

// ── Wall constants ─────────────────────────────────────────

const WALL_H       = 5.0;   // wall height (dollhouse look — taller than all furniture)
const WALL_THICK   = 0.12;  // wall thickness
const WALL_COLOR   = 0xd4d4d8;
const WALL_EMISSIVE = 0x222222;
const CORNER_SIZE  = WALL_THICK + 0.02;
const DOOR_FRAME_COLOR = 0x78716c;
const WINDOW_SILL_H = 0.6;  // height of sill below window
const WINDOW_HEAD_H = 0.2;  // height of strip above window

// ── Opening widths (in cells) ──────────────────────────────

const OPENING_WIDTHS = {
  'door-s':   2,
  'door-n':   3,
  'window-s': 2,
  'window-l': 4,
};

// ── Grid sizing ────────────────────────────────────────────

const WORLD_SIZE_MIN = 20;  // minimum world size
const GRID_CELLS = 80;      // detect rooms within this extent

// ════════════════════════════════════════════════════════════
//  HomePlannerEngine
// ════════════════════════════════════════════════════════════

export class HomePlannerEngine {

  /**
   * @param {HTMLElement} container - DOM element to render into
   * @param {Object} callbacks - { onSelect, onDeselect, onCountChange, onFloorChange }
   * @param {HTMLElement|null} labelOverlay - overlay div for HTML labels
   */
  constructor(container, callbacks = {}, labelOverlay = null) {
    this.container = container;
    this.callbacks = callbacks;
    this.labelOverlay = labelOverlay;
    this.worldSize = WORLD_SIZE_MIN;

    // ── Data model ──────────────────────────────────────
    this.homeGrid = new HomeGrid();

    // ── Tool state ──────────────────────────────────────
    this._activeTool = null;     // 'wall', 'door-s', 'door-n', 'window-s', 'window-l', 'select', 'furniture:<type>', or null
    this._viewMode = 'isometric';

    // ── Selection ───────────────────────────────────────
    this._selectedFurnId = null;
    this._selectedMesh = null;
    this._dragOffset = null;
    this._isDragging = false;

    // ── Wall drawing state ──────────────────────────────
    this._isDrawingWall = false;
    this._wallDrawMode = null;   // 'add' or 'remove' — set on first click
    this._lastDrawnEdge = null;

    // ── Mesh registries ─────────────────────────────────
    this._wallMeshes = [];       // all wall-related meshes (walls, corners, frames)
    this._floorMeshes = [];      // room floor planes
    this._furnitureMeshes = new Map();  // furnId -> THREE.Mesh
    this._floorGroups = new Map();      // floorIndex -> THREE.Group

    // ── Hover preview ───────────────────────────────────
    this._hoverLine = null;
    this._ghostMesh = null;      // furniture placement ghost

    // ── Three.js setup via engine-base ──────────────────
    const setup = createScene(container);
    this.scene    = setup.scene;
    this.camera   = setup.camera;
    this.renderer = setup.renderer;
    this.composer = setup.composer;
    this.controls = setup.controls;
    this.raycaster = setup.raycaster;
    this._groundPlane = setup.groundPlane;

    // Grid and dot grid
    const { gridMesh, groundFill } = createGrid(this.scene, this.worldSize);
    this.gridMesh    = gridMesh;
    this._groundFill = groundFill;
    this.dotGridMesh = createDotGrid(this.scene);

    // Hover preview line (reusable, hidden by default)
    this._createHoverLine();

    // Events
    this._bindEvents();

    // Resize observer
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.container);

    // Clock and animation loop
    this._clock = new THREE.Clock();
    this._rafId = null;
    // Load manifest (presets + furniture defs) then start rendering
    this._ready = loadHomeManifest();
    this._animate();
  }

  // ════════════════════════════════════════════════════════
  //  Hover Preview Line
  // ════════════════════════════════════════════════════════

  _createHoverLine() {
    const geo = new THREE.BoxGeometry(1, 0.06, 1);
    const mat = new THREE.MeshBasicMaterial({
      color: 0x22c55e,
      transparent: true,
      opacity: 0.6,
      depthTest: true,
    });
    this._hoverLine = new THREE.Mesh(geo, mat);
    this._hoverLine.visible = false;
    this.scene.add(this._hoverLine);
  }

  // ════════════════════════════════════════════════════════
  //  Event Binding
  // ════════════════════════════════════════════════════════

  _bindEvents() {
    const el = this.renderer.domElement;
    this._onPointerDown = (e) => this._handlePointerDown(e);
    this._onPointerMove = (e) => this._handlePointerMove(e);
    this._onPointerUp   = (e) => this._handlePointerUp(e);
    el.addEventListener('pointerdown', this._onPointerDown);
    el.addEventListener('pointermove', this._onPointerMove);
    el.addEventListener('pointerup',   this._onPointerUp);
  }

  // ── Ground hit from pointer ──────────────────────────

  _groundHit(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(mouse, this.camera);
    const target = new THREE.Vector3();
    const hit = this.raycaster.ray.intersectPlane(this._groundPlane, target);
    return hit ? target : null;
  }

  // ── Nearest grid edge from world position ────────────

  _nearestEdge(groundPos) {
    const x = groundPos.x;
    const z = groundPos.z;

    // Nearest horizontal edge: z rounds to integer, x rounds to cell
    const hz = Math.round(z);
    const hx = Math.floor(x);
    const hDist = Math.abs(z - hz);

    // Nearest vertical edge: x rounds to integer, z rounds to cell
    const vx = Math.round(x);
    const vz = Math.floor(z);
    const vDist = Math.abs(x - vx);

    if (hDist < vDist) {
      return { x: hx, z: hz, o: 'h', dist: hDist };
    } else {
      return { x: vx, z: vz, o: 'v', dist: vDist };
    }
  }

  // ── Snap position to grid cell ───────────────────────

  _snapToGrid(pos) {
    return {
      x: Math.round(pos.x),
      z: Math.round(pos.z),
    };
  }

  // ════════════════════════════════════════════════════════
  //  Pointer Handlers
  // ════════════════════════════════════════════════════════

  async _handlePointerDown(e) {
    if (e.button !== 0) return;  // left-click only for tools
    const pos = this._groundHit(e);
    if (!pos) return;

    const tool = this._activeTool;

    // ── Wall tool ──────────────────────────────────────
    if (tool === 'wall') {
      const edge = this._nearestEdge(pos);
      if (edge.dist > 0.45) return;  // too far from any edge
      const floor = this.homeGrid.getActiveFloor();
      if (!floor) return;

      const existing = floor.walls.hasWall(edge.x, edge.z, edge.o);
      this._wallDrawMode = existing ? 'remove' : 'add';
      this._isDrawingWall = true;
      this._lastDrawnEdge = `${edge.x},${edge.z},${edge.o}`;

      if (existing) {
        floor.walls.removeWall(edge.x, edge.z, edge.o);
      } else {
        floor.walls.setWall(edge.x, edge.z, edge.o, { type: 'wall' });
      }
      await this._rebuildAll();
      this.controls.enabled = false;  // prevent pan while drawing walls
      return;
    }

    // ── Door / window tools ────────────────────────────
    if (tool && (tool.startsWith('door-') || tool.startsWith('window-'))) {
      const edge = this._nearestEdge(pos);
      if (edge.dist > 0.45) return;
      const floor = this.homeGrid.getActiveFloor();
      if (!floor) return;

      const width = OPENING_WIDTHS[tool] || 2;
      // Place the opening across `width` consecutive edge cells
      for (let i = 0; i < width; i++) {
        const ex = edge.o === 'h' ? edge.x + i : edge.x;
        const ez = edge.o === 'v' ? edge.z + i : edge.z;
        floor.walls.setWall(ex, ez, edge.o, { type: tool });
      }
      await this._rebuildAll();
      return;
    }

    // ── Furniture placement ────────────────────────────
    if (tool && tool.startsWith('furniture:')) {
      const type = tool.split(':')[1];
      const def = FURNITURE_DEFS[type];
      if (!def) return;
      const snap = this._snapToGrid(pos);
      const id = this.homeGrid.addFurniture(type, snap.x, snap.z, 0);
      await this._rebuildAll();
      this._selectFurniture(id);
      return;
    }

    // ── Select tool or no tool: pick furniture ─────────
    if (tool === 'select' || tool === null) {
      const picked = this._pickFurniture(e);
      if (picked) {
        this._selectFurniture(picked.id);
        // Start drag
        const furn = this._getFurnitureData(picked.id);
        if (furn) {
          this._isDragging = true;
          this._dragOffset = { x: pos.x - furn.x, z: pos.z - furn.z };
          this.controls.enabled = false;
        }
      } else {
        this._deselectFurniture();
      }
    }
  }

  async _handlePointerMove(e) {
    const pos = this._groundHit(e);
    if (!pos) return;

    const tool = this._activeTool;

    // ── Wall drag drawing ──────────────────────────────
    if (this._isDrawingWall && tool === 'wall') {
      const edge = this._nearestEdge(pos);
      if (edge.dist > 0.45) return;
      const edgeKey = `${edge.x},${edge.z},${edge.o}`;
      if (edgeKey === this._lastDrawnEdge) return;
      this._lastDrawnEdge = edgeKey;

      const floor = this.homeGrid.getActiveFloor();
      if (!floor) return;

      if (this._wallDrawMode === 'remove') {
        floor.walls.removeWall(edge.x, edge.z, edge.o);
      } else {
        floor.walls.setWall(edge.x, edge.z, edge.o, { type: 'wall' });
      }
      await this._rebuildAll();
      return;
    }

    // ── Furniture drag ─────────────────────────────────
    if (this._isDragging && this._selectedFurnId !== null) {
      const furn = this._getFurnitureData(this._selectedFurnId);
      if (furn) {
        const snap = this._snapToGrid({
          x: pos.x - this._dragOffset.x,
          z: pos.z - this._dragOffset.z,
        });
        furn.x = snap.x;
        furn.z = snap.z;
        this._updateFurnitureMeshPosition(this._selectedFurnId);
      }
      return;
    }

    // ── Edge hover preview for wall/door/window tools ──
    if (tool === 'wall' || (tool && (tool.startsWith('door-') || tool.startsWith('window-')))) {
      this._updateHoverPreview(pos);
      return;
    }

    // ── Furniture ghost preview ─────────────────────────
    if (tool && tool.startsWith('furniture:')) {
      this._updateGhostPreview(pos, tool.split(':')[1]);
      return;
    }

    // Hide previews when no relevant tool active
    if (this._hoverLine) this._hoverLine.visible = false;
    this._removeGhostMesh();
  }

  async _handlePointerUp(e) {
    if (this._isDrawingWall) {
      this._isDrawingWall = false;
      this._wallDrawMode = null;
      this._lastDrawnEdge = null;
      this.controls.enabled = true;
    }
    if (this._isDragging) {
      this._isDragging = false;
      this._dragOffset = null;
      this.controls.enabled = true;
      await this._rebuildAll();  // re-detect rooms after furniture move
    }
  }

  // ════════════════════════════════════════════════════════
  //  Hover Preview (edge highlight)
  // ════════════════════════════════════════════════════════

  _updateHoverPreview(pos) {
    const edge = this._nearestEdge(pos);
    if (edge.dist > 0.45) {
      this._hoverLine.visible = false;
      return;
    }

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;
    const floorY = floor.yOffset;

    const existing = floor.walls.hasWall(edge.x, edge.z, edge.o);

    // Color: red if would remove, green if would add
    if (this._activeTool === 'wall') {
      this._hoverLine.material.color.setHex(existing ? 0xef4444 : 0x22c55e);
    } else {
      // Door/window tools: always green (placing onto edge)
      this._hoverLine.material.color.setHex(0x38bdf8);
    }

    // Position and scale the hover indicator
    if (edge.o === 'h') {
      const width = (this._activeTool !== 'wall' && OPENING_WIDTHS[this._activeTool])
        ? OPENING_WIDTHS[this._activeTool] : 1;
      this._hoverLine.scale.set(width, 1, WALL_THICK * 2);
      this._hoverLine.position.set(edge.x + width / 2, floorY + 0.04, edge.z);
    } else {
      const width = (this._activeTool !== 'wall' && OPENING_WIDTHS[this._activeTool])
        ? OPENING_WIDTHS[this._activeTool] : 1;
      this._hoverLine.scale.set(WALL_THICK * 2, 1, width);
      this._hoverLine.position.set(edge.x, floorY + 0.04, edge.z + width / 2);
    }
    this._hoverLine.visible = true;
  }

  // ════════════════════════════════════════════════════════
  //  Ghost Preview (furniture placement)
  // ════════════════════════════════════════════════════════

  _updateGhostPreview(pos, type) {
    const def = FURNITURE_DEFS[type];
    if (!def) return;

    const snap = this._snapToGrid(pos);
    const floor = this.homeGrid.getActiveFloor();
    const floorY = floor ? floor.yOffset : 0;

    if (!this._ghostMesh || this._ghostMesh.userData.furnType !== type) {
      this._removeGhostMesh();
      const geo = new THREE.BoxGeometry(def.w, def.h, def.d);
      const mat = new THREE.MeshStandardMaterial({
        color: def.color,
        transparent: true,
        opacity: 0.4,
        depthWrite: false,
      });
      this._ghostMesh = new THREE.Mesh(geo, mat);
      this._ghostMesh.userData.furnType = type;
      this.scene.add(this._ghostMesh);
    }

    this._ghostMesh.position.set(
      snap.x + def.w / 2,
      floorY + def.h / 2,
      snap.z + def.d / 2
    );
    this._ghostMesh.visible = true;
  }

  _removeGhostMesh() {
    if (this._ghostMesh) {
      this.scene.remove(this._ghostMesh);
      this._ghostMesh.geometry.dispose();
      this._ghostMesh.material.dispose();
      this._ghostMesh = null;
    }
  }

  // ════════════════════════════════════════════════════════
  //  Furniture Picking
  // ════════════════════════════════════════════════════════

  _pickFurniture(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(mouse, this.camera);

    const targets = [...this._furnitureMeshes.values()];
    const hits = this.raycaster.intersectObjects(targets, true);
    if (hits.length > 0) {
      // Walk up parent chain to find the root furniture object with furnId
      let obj = hits[0].object;
      while (obj) {
        if (obj.userData.furnId !== undefined) return { id: obj.userData.furnId, mesh: obj };
        obj = obj.parent;
      }
    }
    return null;
  }

  // ════════════════════════════════════════════════════════
  //  Selection
  // ════════════════════════════════════════════════════════

  _selectFurniture(id) {
    // Deselect previous
    if (this._selectedMesh) {
      this._setFurnGlow(this._selectedMesh, false);
    }

    this._selectedFurnId = id;
    const mesh = this._furnitureMeshes.get(id);
    if (mesh) {
      this._selectedMesh = mesh;
      this._setFurnGlow(mesh, true);
    }

    // Resolve furniture data for callback
    const furn = this._getFurnitureData(id);
    if (furn && this.callbacks.onSelect) {
      const def = FURNITURE_DEFS[furn.type] || {};
      this.callbacks.onSelect({
        id,
        type: furn.type,
        label: def.label || furn.type,
        x: furn.x,
        z: furn.z,
        rotation: furn.rotation,
      });
    }
  }

  _deselectFurniture() {
    if (this._selectedMesh) {
      this._setFurnGlow(this._selectedMesh, false);
    }
    this._selectedFurnId = null;
    this._selectedMesh = null;
    if (this.callbacks.onDeselect) this.callbacks.onDeselect();
  }

  /** Safely set/clear selection glow on a furniture mesh (handles groups + missing emissive). */
  _setFurnGlow(obj, on) {
    const traverse = (o) => {
      if (o.isMesh && o.material) {
        if (!o.material.emissive) return;
        if (on) {
          o._origEmissive = o.material.emissive.getHex();
          o._origEmissiveI = o.material.emissiveIntensity;
          o.material = o.material.clone();
          o.material.emissive.setHex(COLORS.selected);
          o.material.emissiveIntensity = 0.4;
        } else if (o._origEmissive !== undefined) {
          o.material.emissive.setHex(o._origEmissive);
          o.material.emissiveIntensity = o._origEmissiveI;
          delete o._origEmissive;
          delete o._origEmissiveI;
        }
      }
      if (o.children) o.children.forEach(traverse);
    };
    traverse(obj);
  }

  /** Get furniture data by id (searches active floor). */
  _getFurnitureData(id) {
    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return null;
    return floor.furniture.get(id) || null;
  }

  /** Update a single furniture mesh's position after drag. */
  _updateFurnitureMeshPosition(id) {
    const mesh = this._furnitureMeshes.get(id);
    const furn = this._getFurnitureData(id);
    if (!mesh || !furn) return;

    const def = FURNITURE_DEFS[furn.type];
    if (!def) return;

    const floor = this.homeGrid.getActiveFloor();
    const floorY = floor ? floor.yOffset : 0;

    // Compute rotated dimensions
    const { rw, rd } = this._rotatedDims(def, furn.rotation);

    mesh.position.set(
      furn.x + rw / 2,
      floorY + def.h / 2,
      furn.z + rd / 2
    );
  }

  // ════════════════════════════════════════════════════════
  //  Rebuild All Visuals
  // ════════════════════════════════════════════════════════

  async _rebuildAll() {
    this._rebuildWallMeshes();
    this._rebuildFloorMeshes();
    await this._rebuildFurnitureMeshes();
    this._fitWorldToContent();
    this._notifyCountChange();
  }

  /** Fit the world grid tightly around all wall content + padding. */
  _fitWorldToContent() {
    const pad = 3; // tight padding around content
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    for (const [, floor] of this.homeGrid.floors) {
      for (const w of floor.walls.getAllWalls()) {
        minX = Math.min(minX, w.x);
        maxX = Math.max(maxX, w.x + 1);
        minZ = Math.min(minZ, w.z);
        maxZ = Math.max(maxZ, w.z + 1);
      }
    }
    if (!isFinite(minX)) { this.worldSize = WORLD_SIZE_MIN; return; }
    const needHalfW = Math.max(Math.abs(minX - pad), Math.abs(maxX + pad));
    const needHalfD = Math.max(Math.abs(minZ - pad), Math.abs(maxZ + pad));
    this.worldSize = Math.max(WORLD_SIZE_MIN, Math.ceil(Math.max(needHalfW, needHalfD) * 2));

    // Update grass ground plane
    this._updateGrass(minX - 2, minZ - 2, maxX + 2, maxZ + 2);
  }

  /** Green grass ground around the building footprint (F0 only). */
  _updateGrass(minX, minZ, maxX, maxZ) {
    if (this._grassMesh) { this.scene.remove(this._grassMesh); this._grassMesh.geometry.dispose(); }
    if (this.homeGrid.activeFloor !== 0) return; // grass only on ground floor
    const w = maxX - minX, d = maxZ - minZ;
    if (w <= 0 || d <= 0) return;
    const geo = new THREE.PlaneGeometry(w + 8, d + 8);
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({
      color: 0x4a7c59, roughness: 0.9, metalness: 0.0,
    });
    this._grassMesh = new THREE.Mesh(geo, mat);
    this._grassMesh.position.set((minX + maxX) / 2, -0.02, (minZ + maxZ) / 2);
    this._grassMesh.receiveShadow = true;
    this._grassMesh.renderOrder = -2;
    this.scene.add(this._grassMesh);
  }

  _notifyCountChange() {
    if (!this.callbacks.onCountChange) return;
    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;
    const wallCount = floor.walls.getAllWalls().length;
    const furnCount = floor.furniture.size;
    this.callbacks.onCountChange(wallCount, furnCount);
  }

  // ════════════════════════════════════════════════════════
  //  Wall Mesh Generation
  // ════════════════════════════════════════════════════════

  _rebuildWallMeshes() {
    // Clear existing wall meshes
    for (const mesh of this._wallMeshes) {
      this.scene.remove(mesh);
      mesh.traverse(c => { if (c.geometry) c.geometry.dispose(); if (c.material?.dispose) c.material.dispose(); });
    }
    this._wallMeshes = [];

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    const allWalls = floor.walls.getAllWalls();
    const floorY = floor.yOffset;

    // Materials (shared instances — no cloning)
    const wallMat = new THREE.MeshStandardMaterial({
      color: WALL_COLOR, roughness: 0.7, metalness: 0.05,
      emissive: WALL_EMISSIVE, emissiveIntensity: 0.1,
    });
    const frameMat = new THREE.MeshStandardMaterial({
      color: 0x6b5b4f, roughness: 0.4, metalness: 0.1,
    });
    const doorMat = new THREE.MeshStandardMaterial({
      color: 0xa0845c, roughness: 0.5, metalness: 0.05,
    });
    const glassMat = new THREE.MeshStandardMaterial({
      color: 0x93c5fd, roughness: 0.1, metalness: 0.3,
      transparent: true, opacity: 0.35, side: THREE.DoubleSide,
    });
    const arcMat = new THREE.MeshBasicMaterial({
      color: 0xa0845c, transparent: true, opacity: 0.18, side: THREE.DoubleSide,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    });

    // ── Step 1: Merge consecutive wall segments into runs ──
    // Group by (orientation, perpendicular coordinate)
    const hGroups = new Map(); // z -> [{x, type}]
    const vGroups = new Map(); // x -> [{z, type}]

    for (const { x, z, orientation, segment } of allWalls) {
      const type = segment.type || 'wall';
      if (orientation === 'h') {
        if (!hGroups.has(z)) hGroups.set(z, []);
        hGroups.get(z).push({ pos: x, type });
      } else {
        if (!vGroups.has(x)) vGroups.set(x, []);
        vGroups.get(x).push({ pos: z, type });
      }
    }

    const corners = new Set();

    // ── Step 2: Build merged wall runs ──
    const buildRuns = (groups, orient) => {
      for (const [perp, segments] of groups) {
        segments.sort((a, b) => a.pos - b.pos);
        let runStart = null, runType = null, runLen = 0;

        const flushRun = () => {
          if (runStart === null) return;
          if (runType === 'wall') {
            this._addMergedWall(runStart, perp, runLen, orient, floorY, wallMat, corners);
          }
          runStart = null; runLen = 0;
        };

        for (let i = 0; i < segments.length; i++) {
          const s = segments[i];
          if (s.type === 'wall') {
            if (runStart === null || runType !== 'wall' || s.pos !== runStart + runLen) {
              flushRun();
              runStart = s.pos; runType = 'wall'; runLen = 1;
            } else {
              runLen++;
            }
          } else {
            flushRun();
            // Merge consecutive same-type door/window segments into one opening
            let spanLen = 1;
            while (i + spanLen < segments.length &&
                   segments[i + spanLen].type === s.type &&
                   segments[i + spanLen].pos === s.pos + spanLen) {
              spanLen++;
            }
            if (s.type.startsWith('door-')) {
              this._addDoor(s.pos, perp, spanLen, orient, floorY, frameMat, doorMat, arcMat);
            } else if (s.type.startsWith('window-')) {
              this._addWindow(s.pos, perp, spanLen, orient, floorY, wallMat, glassMat);
            }
            i += spanLen - 1; // skip merged segments
          }
        }
        flushRun();
      }
    };

    buildRuns(hGroups, 'h');
    buildRuns(vGroups, 'v');

    // ── Step 3: Corner posts ──
    this._createCornerPosts(corners, floorY, wallMat);
  }

  /** Create a single merged wall box spanning `len` segments. */
  _addMergedWall(start, perp, len, orient, floorY, mat, corners) {
    const t = WALL_THICK;
    let geo, mesh;
    if (orient === 'h') {
      geo = new THREE.BoxGeometry(len, WALL_H, t);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(start + len / 2, floorY + WALL_H / 2, perp);
      corners.add(`${start},${perp}`);
      corners.add(`${start + len},${perp}`);
    } else {
      geo = new THREE.BoxGeometry(t, WALL_H, len);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(perp, floorY + WALL_H / 2, start + len / 2);
      corners.add(`${perp},${start}`);
      corners.add(`${perp},${start + len}`);
    }
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    this.scene.add(mesh);
    this._wallMeshes.push(mesh);
  }

  /** Create a door spanning `width` edge segments, with frame, leaf, and swing arc. */
  _addDoor(pos, perp, width, orient, floorY, frameMat, doorMat, arcMat) {
    const doorH = WALL_H * 0.82;
    const lintelH = WALL_H - doorH;
    const leafThick = 0.04;
    const w = width;
    const leafW = w - 0.06;
    const group = new THREE.Group();

    if (orient === 'h') {
      const cx = pos + w / 2, cz = perp;
      // Lintel
      if (lintelH > 0.01) {
        const lt = new THREE.Mesh(new THREE.BoxGeometry(w, lintelH, WALL_THICK), frameMat);
        lt.position.set(cx, floorY + doorH + lintelH / 2, cz);
        group.add(lt);
      }
      // Door leaf — hinge at left edge of opening, swings into +z
      const leafGeo = new THREE.BoxGeometry(leafW, doorH, leafThick);
      leafGeo.translate(leafW / 2, 0, 0); // pivot at x=0 (hinge side)
      const leaf = new THREE.Mesh(leafGeo, doorMat);
      leaf.position.set(pos + 0.03, floorY + doorH / 2, cz);
      leaf.rotation.y = -0.4;
      group.add(leaf);
      // Swing arc — slightly above floor, no depth write
      const arcGeo = new THREE.RingGeometry(0.05, leafW, 24, 1, 0, Math.PI / 2);
      const arc = new THREE.Mesh(arcGeo, arcMat);
      arc.rotation.x = -Math.PI / 2;
      arc.position.set(pos + 0.03, floorY + 0.03, cz);
      arc.renderOrder = 1;
      group.add(arc);
    } else {
      const cx = perp, cz = pos + w / 2;
      if (lintelH > 0.01) {
        const lt = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICK, lintelH, w), frameMat);
        lt.position.set(cx, floorY + doorH + lintelH / 2, cz);
        group.add(lt);
      }
      // Door leaf — hinge at top edge, swings into +x
      const leafGeo = new THREE.BoxGeometry(leafThick, doorH, leafW);
      leafGeo.translate(0, 0, leafW / 2);
      const leaf = new THREE.Mesh(leafGeo, doorMat);
      leaf.position.set(cx, floorY + doorH / 2, pos + 0.03);
      leaf.rotation.y = 0.4;
      group.add(leaf);
      const arcGeo = new THREE.RingGeometry(0.05, leafW, 24, 1, 0, Math.PI / 2);
      const arc = new THREE.Mesh(arcGeo, arcMat);
      arc.rotation.x = -Math.PI / 2;
      arc.rotation.z = Math.PI / 2;
      arc.position.set(cx, floorY + 0.03, pos + 0.03);
      arc.renderOrder = 1;
      group.add(arc);
    }

    group.traverse(c => { if (c.isMesh) { c.castShadow = true; c.receiveShadow = true; } });
    this.scene.add(group);
    this._wallMeshes.push(group);
  }

  /** Create a window spanning `width` segments with sill, glass pane, and head strip. */
  _addWindow(pos, perp, width, orient, floorY, wallMat, glassMat) {
    const w = width;
    const glassH = WALL_H - WINDOW_SILL_H - WINDOW_HEAD_H;
    const group = new THREE.Group();
    const fr = new THREE.MeshStandardMaterial({ color: 0xd4d4d8, roughness: 0.3, metalness: 0.2 });

    if (orient === 'h') {
      const cx = pos + w / 2, cz = perp;
      if (WINDOW_SILL_H > 0.01) {
        const s = new THREE.Mesh(new THREE.BoxGeometry(w, WINDOW_SILL_H, WALL_THICK), wallMat);
        s.position.set(cx, floorY + WINDOW_SILL_H / 2, cz);
        group.add(s);
      }
      if (glassH > 0.01) {
        const g = new THREE.Mesh(new THREE.BoxGeometry(w - 0.08, glassH, 0.03), glassMat);
        g.position.set(cx, floorY + WINDOW_SILL_H + glassH / 2, cz);
        group.add(g);
        const top = new THREE.Mesh(new THREE.BoxGeometry(w, 0.04, WALL_THICK * 0.7), fr);
        top.position.set(cx, floorY + WINDOW_SILL_H + glassH, cz);
        group.add(top);
        const bot = new THREE.Mesh(new THREE.BoxGeometry(w, 0.06, WALL_THICK * 0.8), fr);
        bot.position.set(cx, floorY + WINDOW_SILL_H, cz);
        group.add(bot);
      }
      // Head strip
      if (WINDOW_HEAD_H > 0.01) {
        const h = new THREE.Mesh(new THREE.BoxGeometry(1.0, WINDOW_HEAD_H, WALL_THICK), wallMat);
        h.position.set(cx, floorY + WALL_H - WINDOW_HEAD_H / 2, cz);
        group.add(h);
      }
    } else {
      const cx = perp, cz = pos + w / 2;
      if (WINDOW_SILL_H > 0.01) {
        const s = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICK, WINDOW_SILL_H, w), wallMat);
        s.position.set(cx, floorY + WINDOW_SILL_H / 2, cz);
        group.add(s);
      }
      if (glassH > 0.01) {
        const g = new THREE.Mesh(new THREE.BoxGeometry(0.03, glassH, w - 0.08), glassMat);
        g.position.set(cx, floorY + WINDOW_SILL_H + glassH / 2, cz);
        group.add(g);
        const top = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICK * 0.7, 0.04, w), fr);
        top.position.set(cx, floorY + WINDOW_SILL_H + glassH, cz);
        group.add(top);
        const bot = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICK * 0.8, 0.06, w), fr);
        bot.position.set(cx, floorY + WINDOW_SILL_H, cz);
        group.add(bot);
      }
      if (WINDOW_HEAD_H > 0.01) {
        const h = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICK, WINDOW_HEAD_H, w), wallMat);
        h.position.set(cx, floorY + WALL_H - WINDOW_HEAD_H / 2, cz);
        group.add(h);
      }
    }

    group.traverse(c => { if (c.isMesh) { c.castShadow = true; c.receiveShadow = true; } });
    this.scene.add(group);
    this._wallMeshes.push(group);
  }

  /** Create corner posts where walls meet. */
  _createCornerPosts(corners, floorY, wallMat) {
    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    for (const key of corners) {
      const [cx, cz] = key.split(',').map(Number);

      // Only add a corner post if at least two walls meet here
      const adjacent = this._countAdjacentWalls(floor, cx, cz);
      if (adjacent < 2) continue;

      const geo = new THREE.BoxGeometry(CORNER_SIZE, WALL_H, CORNER_SIZE);
      const mesh = new THREE.Mesh(geo, wallMat.clone());
      mesh.position.set(cx, floorY + WALL_H / 2, cz);
      mesh.castShadow = true;
      this.scene.add(mesh);
      this._wallMeshes.push(mesh);
    }
  }

  /** Count how many wall edges meet at a corner point (cx, cz). */
  _countAdjacentWalls(floor, cx, cz) {
    let count = 0;
    // h-edge at (cx, cz): runs from cx to cx+1 along z
    if (floor.walls.hasWall(cx, cz, 'h')) count++;
    // h-edge ending here: at (cx-1, cz)
    if (floor.walls.hasWall(cx - 1, cz, 'h')) count++;
    // v-edge at (cx, cz): runs from cz to cz+1 along x
    if (floor.walls.hasWall(cx, cz, 'v')) count++;
    // v-edge ending here: at (cx, cz-1)
    if (floor.walls.hasWall(cx, cz - 1, 'v')) count++;
    return count;
  }

  // ════════════════════════════════════════════════════════
  //  Room Floor Mesh Generation
  // ════════════════════════════════════════════════════════

  _rebuildFloorMeshes() {
    // Clear existing floor meshes
    for (const mesh of this._floorMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._floorMeshes = [];

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    // Detect rooms
    const rooms = floor.detectRooms(GRID_CELLS, GRID_CELLS);
    const floorY = floor.yOffset;

    // Create floor planes for each room
    for (let ri = 0; ri < rooms.length; ri++) {
      const room = rooms[ri];
      const color = ROOM_COLORS[ri % ROOM_COLORS.length];

      // Create individual cell planes for the room
      // (Merging into a single mesh per room would be more efficient
      //  but per-cell is simpler and fine for home-scale grids)
      for (const cell of room.cells) {
        const geo = new THREE.PlaneGeometry(1, 1);
        geo.rotateX(-Math.PI / 2);
        const mat = new THREE.MeshStandardMaterial({
          color,
          roughness: 0.8,
          metalness: 0.02,
          side: THREE.DoubleSide,
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(cell.x + 0.5, floorY + 0.01, cell.z + 0.5);
        mesh.receiveShadow = true;
        this.scene.add(mesh);
        this._floorMeshes.push(mesh);
      }
    }
  }

  // ════════════════════════════════════════════════════════
  //  Furniture Mesh Generation
  // ════════════════════════════════════════════════════════

  async _rebuildFurnitureMeshes() {
    // Clear existing furniture meshes (safely handle groups)
    for (const [id, mesh] of this._furnitureMeshes) {
      this.scene.remove(mesh);
      mesh.traverse(c => {
        if (c.geometry) c.geometry.dispose();
        if (c.material?.dispose) c.material.dispose();
      });
    }
    this._furnitureMeshes.clear();

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    const floorY = floor.yOffset;
    const promises = [];
    for (const [id, furn] of floor.furniture) {
      promises.push(this._createFurnitureMesh(id, furn, floorY));
    }
    await Promise.all(promises);

    // Re-select if we had a selection
    if (this._selectedFurnId !== null && this._furnitureMeshes.has(this._selectedFurnId)) {
      const mesh = this._furnitureMeshes.get(this._selectedFurnId);
      this._selectedMesh = mesh;
      this._setFurnGlow(mesh, true);
    } else {
      this._selectedFurnId = null;
      this._selectedMesh = null;
    }
  }

  /** Compute rotated width/depth for furniture. */
  _rotatedDims(def, rotation) {
    const rot = ((rotation % 360) + 360) % 360;
    if (rot === 90 || rot === 270) {
      return { rw: def.d, rd: def.w };
    }
    return { rw: def.w, rd: def.d };
  }

  /** Create a single furniture mesh and add to scene (loads GLB, falls back to box). */
  async _createFurnitureMesh(id, furn, floorY) {
    const def = FURNITURE_DEFS[furn.type];
    if (!def) return;

    const { rw, rd } = this._rotatedDims(def, furn.rotation);
    const cx = furn.x + rw / 2;
    const cz = furn.z + rd / 2;

    // Try to load GLB model
    let mesh = await loadModel(furn.type);

    if (!mesh) {
      // Fallback: simple box
      const geo = new THREE.BoxGeometry(rw, def.h, rd);
      const mat = new THREE.MeshStandardMaterial({ color: def.color, roughness: 0.6, metalness: 0.1 });
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(cx, floorY + def.h / 2, cz);
    } else {
      // GLB loaded — scale footprint to match def, height proportionally (preserves shape)
      const box = new THREE.Box3().setFromObject(mesh);
      const gs = box.getSize(new THREE.Vector3());
      if (gs.x > 0.01 && gs.z > 0.01) {
        const sx = def.w / gs.x;
        const sz = def.d / gs.z;
        const sy = (sx + sz) / 2; // proportional height — keeps backrests, legs, etc. correct
        mesh.scale.set(sx, sy, sz);
      }
      mesh.position.set(cx, floorY, cz);
    }

    // Apply rotation
    const rot = ((furn.rotation || 0) % 360 + 360) % 360;
    if (rot !== 0) {
      mesh.rotation.y = -rot * Math.PI / 180;
    }

    mesh.userData.furnId = id;
    mesh.traverse(c => { if (c.isMesh) { c.castShadow = true; c.receiveShadow = true; } });

    this.scene.add(mesh);
    this._furnitureMeshes.set(id, mesh);
  }

  /** Create a stepped stairs mesh. */
  _createStairsMesh(def, furn, floorY) {
    const { rw, rd } = this._rotatedDims(def, furn.rotation);
    const stepCount = 8;
    const stepH = def.h / stepCount;
    const stepD = rd / stepCount;

    const group = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({
      color: def.color,
      roughness: 0.5,
      metalness: 0.15,
    });

    const rot = ((furn.rotation % 360) + 360) % 360;

    for (let i = 0; i < stepCount; i++) {
      const geo = new THREE.BoxGeometry(rw, stepH, stepD);
      const step = new THREE.Mesh(geo, mat.clone());

      // Position steps going "forward" in the depth direction
      let stepX = 0;
      let stepZ = 0;
      if (rot === 0 || rot === 180) {
        stepZ = (rot === 0) ? i * stepD + stepD / 2 : rd - i * stepD - stepD / 2;
      } else {
        stepX = (rot === 90) ? i * stepD + stepD / 2 : rd - i * stepD - stepD / 2;
      }

      step.position.set(stepX, (i + 0.5) * stepH, stepZ);
      step.castShadow = true;
      group.add(step);
    }

    group.position.set(
      furn.x + rw / 2,
      floorY,
      furn.z + rd / 2
    );

    // Wrap in a regular Mesh-like object for raycasting
    // We use the group's children for hit testing
    const wrapGeo = new THREE.BoxGeometry(rw, def.h, rd);
    const wrapMat = new THREE.MeshBasicMaterial({ visible: false });
    const wrapper = new THREE.Mesh(wrapGeo, wrapMat);
    wrapper.position.copy(group.position);
    wrapper.position.y += def.h / 2;

    // Add group and invisible wrapper for picking
    this.scene.add(group);
    this._wallMeshes.push(...group.children); // managed for cleanup via _wallMeshes reuse
    // Actually, let's not mix them. The group children are part of the stairs.
    // Instead, return the wrapper, and we'll clean up the group via userData.
    wrapper.userData.stairsGroup = group;

    return wrapper;
  }

  // ════════════════════════════════════════════════════════
  //  Preset Loading
  // ════════════════════════════════════════════════════════

  /**
   * Load a home preset. Clears existing data and rebuilds.
   * @param {Object} preset - A preset from HOME_PRESETS
   */
  async loadPreset(preset) {
    await this._ready; // ensure manifest + presets loaded
    this.clearAll();

    for (const [floorIdx, floorData] of Object.entries(preset.floors)) {
      const idx = parseFloat(floorIdx);
      this.homeGrid.addFloor(idx);
      const floor = this.homeGrid.getFloor(idx);
      if (!floor) continue;

      // ── Walls: line segments [x1, z1, x2, z2] ──────
      for (const [x1, z1, x2, z2] of floorData.walls) {
        if (z1 === z2) {
          // Horizontal wall line
          const [a, b] = x1 < x2 ? [x1, x2] : [x2, x1];
          for (let x = a; x < b; x++) {
            floor.walls.setWall(x, z1, 'h', { type: 'wall' });
          }
        } else {
          // Vertical wall line
          const [a, b] = z1 < z2 ? [z1, z2] : [z2, z1];
          for (let z = a; z < b; z++) {
            floor.walls.setWall(x1, z, 'v', { type: 'wall' });
          }
        }
      }

      // ── Doors ───────────────────────────────────────
      for (const d of (floorData.doors || [])) {
        const width = OPENING_WIDTHS[d.type] || 2;
        for (let i = 0; i < width; i++) {
          const ex = d.o === 'h' ? d.x + i : d.x;
          const ez = d.o === 'v' ? d.z + i : d.z;
          floor.walls.setWall(ex, ez, d.o, { type: d.type });
        }
      }

      // ── Windows ─────────────────────────────────────
      for (const w of (floorData.windows || [])) {
        const width = OPENING_WIDTHS[w.type] || 2;
        for (let i = 0; i < width; i++) {
          const ex = w.o === 'h' ? w.x + i : w.x;
          const ez = w.o === 'v' ? w.z + i : w.z;
          floor.walls.setWall(ex, ez, w.o, { type: w.type });
        }
      }

      // ── Furniture ───────────────────────────────────
      for (const f of (floorData.furniture || [])) {
        floor.addFurniture(f.type, f.x, f.z, f.rot || 0);
      }
    }

    // Activate first floor
    const indices = this.homeGrid.getFloorIndices();
    if (indices.length > 0) {
      this.homeGrid.setActiveFloor(indices[0]);
    }

    await this._rebuildAll();
    this._centerCameraOnContent();

    if (this.callbacks.onFloorChange) {
      this.callbacks.onFloorChange(this.homeGrid.activeFloor);
    }
  }

  // ════════════════════════════════════════════════════════
  //  Camera Centering
  // ════════════════════════════════════════════════════════

  /** Center the camera on the bounding box of all content on the active floor. */
  _centerCameraOnContent() {
    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    const walls = floor.walls.getAllWalls();
    if (walls.length === 0 && floor.furniture.size === 0) return;

    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;

    for (const w of walls) {
      if (w.orientation === 'h') {
        minX = Math.min(minX, w.x);
        maxX = Math.max(maxX, w.x + 1);
        minZ = Math.min(minZ, w.z);
        maxZ = Math.max(maxZ, w.z);
      } else {
        minX = Math.min(minX, w.x);
        maxX = Math.max(maxX, w.x);
        minZ = Math.min(minZ, w.z);
        maxZ = Math.max(maxZ, w.z + 1);
      }
    }

    for (const [, furn] of floor.furniture) {
      const def = FURNITURE_DEFS[furn.type];
      if (!def) continue;
      const { rw, rd } = this._rotatedDims(def, furn.rotation);
      minX = Math.min(minX, furn.x);
      maxX = Math.max(maxX, furn.x + rw);
      minZ = Math.min(minZ, furn.z);
      maxZ = Math.max(maxZ, furn.z + rd);
    }

    if (!isFinite(minX)) return;

    const cx = (minX + maxX) / 2;
    const cz = (minZ + maxZ) / 2;

    this.controls.target.set(cx, 0, cz);

    // Adjust zoom to fit content — orthographic zoom = frustumSize / contentSpan
    const spanX = maxX - minX;
    const spanZ = maxZ - minZ;
    const span = Math.max(spanX, spanZ, 10);
    const frustumH = this.camera.top - this.camera.bottom; // 28
    // In isometric, the ground diagonal takes ~1.4× more screen space
    this.camera.zoom = Math.max(0.3, frustumH / (span * 1.5));
    this.camera.updateProjectionMatrix();

    // Update camera position to look at new target
    const d = Math.max(span * 0.5, 20);
    this.camera.position.set(cx + d, d, cz + d);
    this.camera.lookAt(this.controls.target);
  }

  // ════════════════════════════════════════════════════════
  //  Floor Management
  // ════════════════════════════════════════════════════════

  /** Switch active floor and rebuild all visuals. */
  async setActiveFloor(index) {
    this.homeGrid.setActiveFloor(index);
    this._deselectFurniture();
    await this._rebuildAll();
    if (this.callbacks.onFloorChange) {
      this.callbacks.onFloorChange(index);
    }
  }

  /** Get the list of floor indices. */
  getFloorIndices() {
    return this.homeGrid.getFloorIndices();
  }

  /** Add a new floor. */
  addFloor(index) {
    this.homeGrid.addFloor(index);
  }

  /** Remove a floor. */
  removeFloor(index) {
    return this.homeGrid.removeFloor(index);
  }

  // ════════════════════════════════════════════════════════
  //  Public API
  // ════════════════════════════════════════════════════════

  /** Set the current active tool. */
  setActiveTool(type) {
    // Clean up previous tool state
    if (this._hoverLine) this._hoverLine.visible = false;
    this._removeGhostMesh();

    if (type && FURNITURE_DEFS[type]) {
      this._activeTool = `furniture:${type}`;
    } else {
      this._activeTool = type;   // 'wall', 'door-s', 'select', null, etc.
    }

    // Adjust controls: allow pan when no tool or select tool
    if (type === null || type === 'select') {
      this.controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
    } else {
      // Tool active: left-click is for tool, right-click for pan
      this.controls.mouseButtons.LEFT = null;
    }
  }

  /** Set view mode ('isometric' or 'flat'). */
  setViewMode(mode) {
    this._viewMode = mode;
    if (mode === 'flat') {
      // Top-down view
      const target = this.controls.target;
      this.camera.position.set(target.x, 50, target.z + 0.01);
      this.camera.lookAt(target);
      if (this.gridMesh) this.gridMesh.visible = false;
      if (this.dotGridMesh) this.dotGridMesh.visible = true;
    } else {
      // Isometric view
      const target = this.controls.target;
      const d = 35;
      this.camera.position.set(target.x + d, d, target.z + d);
      this.camera.lookAt(target);
      if (this.gridMesh) this.gridMesh.visible = true;
      if (this.dotGridMesh) this.dotGridMesh.visible = false;
    }
    this.camera.updateProjectionMatrix();
  }

  /** Load a home preset by index from cached presets. */
  async loadPresetByIndex(index) {
    await this._ready;
    if (index >= 0 && index < _presetCache.length) {
      await this.loadPreset(_presetCache[index]);
    }
  }

  /** Clear all data and visuals. */
  clearAll() {
    this._deselectFurniture();
    if (this._grassMesh) { this.scene.remove(this._grassMesh); this._grassMesh.geometry.dispose(); this._grassMesh = null; }

    // Clear wall meshes
    for (const mesh of this._wallMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._wallMeshes = [];

    // Clear floor meshes
    for (const mesh of this._floorMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._floorMeshes = [];

    // Clear furniture meshes (handles both single meshes and GLB groups)
    for (const [id, mesh] of this._furnitureMeshes) {
      this.scene.remove(mesh);
      mesh.traverse(c => {
        if (c.geometry) c.geometry.dispose();
        if (c.material?.dispose) c.material.dispose();
      });
    }
    this._furnitureMeshes.clear();

    this._removeGhostMesh();

    // Reset data model
    this.homeGrid = new HomeGrid();
  }

  /** Remove the currently selected furniture. */
  async removeSelected() {
    if (this._selectedFurnId === null) return;
    const id = this._selectedFurnId;

    // Remove mesh
    const mesh = this._furnitureMeshes.get(id);
    if (mesh) {
      this.scene.remove(mesh);
      mesh.traverse(c => {
        if (c.geometry) c.geometry.dispose();
        if (c.material?.dispose) c.material.dispose();
      });
      this._furnitureMeshes.delete(id);
    }

    // Remove from data
    this.homeGrid.removeFurniture(id);
    this._deselectFurniture();
    await this._rebuildAll();
  }

  /** Rotate selected furniture by 90 degrees clockwise. */
  async rotateSelected() {
    if (this._selectedFurnId === null) return;
    const furn = this._getFurnitureData(this._selectedFurnId);
    if (!furn) return;
    furn.rotation = ((furn.rotation || 0) + 90) % 360;
    await this._rebuildFurnitureMeshes();
    if (this.callbacks.onSelect) {
      const def = FURNITURE_DEFS[furn.type] || {};
      this.callbacks.onSelect({ id: this._selectedFurnId, type: furn.type, label: def.label || furn.type, x: furn.x, z: furn.z, rotation: furn.rotation });
    }
  }

  /** Flip the selected furniture's facing (mirror: 0↔180, 90↔270). */
  async flipSelected() {
    if (this._selectedFurnId === null) return;
    const furn = this._getFurnitureData(this._selectedFurnId);
    if (!furn) return;
    furn.rotation = ((furn.rotation || 0) + 180) % 360;
    await this._rebuildFurnitureMeshes();
    // Re-notify UI with updated data
    if (this.callbacks.onSelect) {
      const def = FURNITURE_DEFS[furn.type] || {};
      this.callbacks.onSelect({ id: this._selectedFurnId, type: furn.type, label: def.label || furn.type, x: furn.x, z: furn.z, rotation: furn.rotation });
    }
  }

  /** Get the palette catalog for the UI. */
  getCatalog() {
    return [
      {
        label: 'Structure', icon: 'domain', items: [
          { type: 'wall', label: 'Wall', icon: 'border_all', color: '#d4d4d8', desc: 'Draw walls' },
          { type: 'door-s', label: 'Small Door', icon: 'door_front', color: '#a16207', desc: '50cm door' },
          { type: 'door-n', label: 'Door', icon: 'door_front', color: '#a16207', desc: '75cm door' },
          { type: 'window-s', label: 'Window', icon: 'window', color: '#38bdf8', desc: '50cm window' },
          { type: 'window-l', label: 'Large Window', icon: 'window', color: '#38bdf8', desc: '100cm window' },
          { type: 'stairs-straight', label: 'Stairs', icon: 'stairs', color: '#92400e', desc: 'Straight stairs' },
        ]
      },
      {
        label: 'Living Room', icon: 'weekend', items: [
          { type: 'sofa', label: 'Sofa', icon: 'weekend', color: '#6b7280', desc: 'Three-seater sofa' },
          { type: 'armchair', label: 'Armchair', icon: 'chair', color: '#78716c', desc: 'Single armchair' },
          { type: 'tv', label: 'TV', icon: 'tv', color: '#1e293b', desc: 'Television' },
          { type: 'bookshelf', label: 'Bookshelf', icon: 'menu_book', color: '#92400e', desc: 'Tall bookshelf' },
          { type: 'coffee-table', label: 'Coffee Table', icon: 'table_bar', color: '#78716c', desc: 'Low coffee table' },
        ]
      },
      {
        label: 'Kitchen', icon: 'kitchen', items: [
          { type: 'counter', label: 'Counter', icon: 'countertops', color: '#d4d4d8', desc: 'Kitchen counter' },
          { type: 'stove', label: 'Stove', icon: 'local_fire_department', color: '#27272a', desc: 'Cooking stove' },
          { type: 'fridge', label: 'Fridge', icon: 'kitchen', color: '#d4d4d8', desc: 'Refrigerator' },
          { type: 'sink', label: 'Sink', icon: 'water_drop', color: '#a8a29e', desc: 'Kitchen sink' },
          { type: 'dining-table', label: 'Dining Table', icon: 'table_restaurant', color: '#92400e', desc: 'Dining table' },
          { type: 'chair', label: 'Chair', icon: 'chair_alt', color: '#78716c', desc: 'Dining chair' },
        ]
      },
      {
        label: 'Bedroom', icon: 'bed', items: [
          { type: 'bed-single', label: 'Single Bed', icon: 'single_bed', color: '#60a5fa', desc: 'Single bed' },
          { type: 'bed-double', label: 'Double Bed', icon: 'bed', color: '#60a5fa', desc: 'Double bed' },
          { type: 'wardrobe', label: 'Wardrobe', icon: 'checkroom', color: '#78716c', desc: 'Clothing wardrobe' },
          { type: 'desk', label: 'Desk', icon: 'desk', color: '#92400e', desc: 'Work desk' },
          { type: 'nightstand', label: 'Nightstand', icon: 'nightlight', color: '#78716c', desc: 'Bedside table' },
        ]
      },
      {
        label: 'Bathroom', icon: 'bathtub', items: [
          { type: 'toilet', label: 'Toilet', icon: 'wc', color: '#fafaf9', desc: 'Toilet' },
          { type: 'bathtub', label: 'Bathtub', icon: 'bathtub', color: '#fafaf9', desc: 'Full bathtub' },
          { type: 'shower', label: 'Shower', icon: 'shower', color: '#e7e5e4', desc: 'Shower tray' },
          { type: 'basin', label: 'Basin', icon: 'wash', color: '#fafaf9', desc: 'Wash basin' },
        ]
      },
    ];
  }

  /** Get all available presets. */
  getPresets() {
    return _presetCache;
  }

  /** Get the active floor index. */
  getActiveFloor() {
    return this.homeGrid.activeFloor;
  }

  /** Get information about all rooms on the active floor. */
  getRooms() {
    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return [];
    return floor.rooms.map(r => ({
      id: r.id,
      cellCount: r.cells.length,
      bounds: { ...r.bounds },
      areaSqm: r.cells.length * 0.0625,  // 25cm x 25cm = 0.0625 sqm per cell
    }));
  }

  /** Export the current layout as a preset-compatible object. */
  exportLayout() {
    const result = { floors: {} };

    for (const [idx, floor] of this.homeGrid.floors) {
      const floorData = { walls: [], doors: [], windows: [], furniture: [] };

      // Group wall segments into line segments by type
      // For simplicity, export individual segments
      const allWalls = floor.walls.getAllWalls();

      // Separate by type
      const solidWalls = allWalls.filter(w => w.segment.type === 'wall');
      const doors = allWalls.filter(w => w.segment.type.startsWith('door-'));
      const windows = allWalls.filter(w => w.segment.type.startsWith('window-'));

      // Convert solid walls to line segments (merge consecutive)
      floorData.walls = this._mergeWallSegments(solidWalls);

      // Group doors/windows by position (consecutive segments of same type)
      floorData.doors = this._groupOpenings(doors);
      floorData.windows = this._groupOpenings(windows);

      // Furniture
      for (const [, furn] of floor.furniture) {
        floorData.furniture.push({
          type: furn.type,
          x: furn.x,
          z: furn.z,
          rot: furn.rotation || 0,
        });
      }

      result.floors[idx] = floorData;
    }

    return result;
  }

  /** Merge consecutive wall edge segments into line segments. */
  _mergeWallSegments(walls) {
    const lines = [];

    // Group by orientation and shared axis
    const hByZ = new Map();  // z -> sorted x values
    const vByX = new Map();  // x -> sorted z values

    for (const w of walls) {
      if (w.orientation === 'h') {
        if (!hByZ.has(w.z)) hByZ.set(w.z, []);
        hByZ.get(w.z).push(w.x);
      } else {
        if (!vByX.has(w.x)) vByX.set(w.x, []);
        vByX.get(w.x).push(w.z);
      }
    }

    // Merge horizontal segments
    for (const [z, xs] of hByZ) {
      xs.sort((a, b) => a - b);
      let start = xs[0];
      let end = xs[0] + 1;
      for (let i = 1; i < xs.length; i++) {
        if (xs[i] === end) {
          end = xs[i] + 1;
        } else {
          lines.push([start, z, end, z]);
          start = xs[i];
          end = xs[i] + 1;
        }
      }
      lines.push([start, z, end, z]);
    }

    // Merge vertical segments
    for (const [x, zs] of vByX) {
      zs.sort((a, b) => a - b);
      let start = zs[0];
      let end = zs[0] + 1;
      for (let i = 1; i < zs.length; i++) {
        if (zs[i] === end) {
          end = zs[i] + 1;
        } else {
          lines.push([x, start, x, end]);
          start = zs[i];
          end = zs[i] + 1;
        }
      }
      lines.push([x, start, x, end]);
    }

    return lines;
  }

  /** Group opening segments (doors/windows) into placement objects. */
  _groupOpenings(segments) {
    if (segments.length === 0) return [];

    // Group by type + orientation + axis value
    const groups = new Map();
    for (const s of segments) {
      const axis = s.orientation === 'h' ? s.z : s.x;
      const key = `${s.segment.type}:${s.orientation}:${axis}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }

    const openings = [];
    for (const [, group] of groups) {
      // Sort by position along the non-axis direction
      const o = group[0].orientation;
      group.sort((a, b) => (o === 'h' ? a.x - b.x : a.z - b.z));

      // Find consecutive runs
      let runStart = 0;
      for (let i = 1; i <= group.length; i++) {
        const prev = group[i - 1];
        const cur = group[i];
        const consecutive = cur && (
          o === 'h' ? (cur.x === prev.x + 1 && cur.z === prev.z) :
                      (cur.z === prev.z + 1 && cur.x === prev.x)
        );

        if (!consecutive) {
          const first = group[runStart];
          openings.push({
            x: first.x,
            z: first.z,
            o: first.orientation,
            type: first.segment.type,
          });
          runStart = i;
        }
      }
    }

    return openings;
  }

  // ════════════════════════════════════════════════════════
  //  Resize & Dispose
  // ════════════════════════════════════════════════════════

  resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w < 10 || h < 10) return;

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

    // Remove event listeners
    const el = this.renderer.domElement;
    el.removeEventListener('pointerdown', this._onPointerDown);
    el.removeEventListener('pointermove', this._onPointerMove);
    el.removeEventListener('pointerup',   this._onPointerUp);

    // Dispose all managed meshes
    for (const mesh of this._wallMeshes) {
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    for (const mesh of this._floorMeshes) {
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    for (const [, mesh] of this._furnitureMeshes) {
      mesh.traverse(c => {
        if (c.geometry) c.geometry.dispose();
        if (c.material?.dispose) c.material.dispose();
      });
    }
    this._removeGhostMesh();
  }

  // ════════════════════════════════════════════════════════
  //  Animation Loop
  // ════════════════════════════════════════════════════════

  _animate() {
    this._rafId = requestAnimationFrame(() => this._animate());

    const dt = this._clock.getDelta();
    const t  = this._clock.getElapsedTime();

    // Update grid uniforms (position, scale, time)
    updateGridUniforms(
      this.gridMesh, this.dotGridMesh, this._groundFill,
      t, this.worldSize, this.controls, this.camera
    );

    this.controls.update();

    // Skip render when container is collapsed
    if (this.container.clientWidth > 10 && this.container.clientHeight > 10) {
      this.composer.render();
    }
  }
}
