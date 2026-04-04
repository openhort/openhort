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
import { HomeGrid, RoomDetector } from './grid-home.js';
import { HOME_PRESETS } from './presets-home.js';

// ── Furniture definitions ──────────────────────────────────
// w/d in grid cells (25 cm each), h in Three.js units

const FURNITURE_DEFS = {
  // Living
  'sofa':            { w: 3, d: 6, h: 0.8, color: 0x6b7280, label: 'Sofa' },
  'armchair':        { w: 2, d: 2, h: 0.8, color: 0x78716c, label: 'Armchair' },
  'tv':              { w: 4, d: 1, h: 1.5, color: 0x1e293b, label: 'TV' },
  'bookshelf':       { w: 3, d: 1, h: 2.0, color: 0x92400e, label: 'Bookshelf' },
  'coffee-table':    { w: 2, d: 3, h: 0.4, color: 0x78716c, label: 'Coffee Table' },
  // Kitchen
  'counter':         { w: 2, d: 1, h: 0.9, color: 0xd4d4d8, label: 'Counter' },
  'stove':           { w: 2, d: 2, h: 0.9, color: 0x27272a, label: 'Stove' },
  'fridge':          { w: 2, d: 2, h: 2.0, color: 0xd4d4d8, label: 'Fridge' },
  'sink':            { w: 2, d: 1, h: 0.9, color: 0xa8a29e, label: 'Sink' },
  'dining-table':    { w: 3, d: 5, h: 0.75, color: 0x92400e, label: 'Dining Table' },
  'chair':           { w: 1, d: 1, h: 0.9, color: 0x78716c, label: 'Chair' },
  // Bedroom
  'bed-single':      { w: 3, d: 7, h: 0.5, color: 0x60a5fa, label: 'Single Bed' },
  'bed-double':      { w: 6, d: 8, h: 0.5, color: 0x60a5fa, label: 'Double Bed' },
  'wardrobe':        { w: 4, d: 2, h: 2.0, color: 0x78716c, label: 'Wardrobe' },
  'desk':            { w: 3, d: 2, h: 0.75, color: 0x92400e, label: 'Desk' },
  'nightstand':      { w: 1, d: 1, h: 0.5, color: 0x78716c, label: 'Nightstand' },
  // Bathroom
  'toilet':          { w: 2, d: 2, h: 0.4, color: 0xfafaf9, label: 'Toilet' },
  'bathtub':         { w: 3, d: 6, h: 0.6, color: 0xfafaf9, label: 'Bathtub' },
  'shower':          { w: 3, d: 3, h: 0.1, color: 0xe7e5e4, label: 'Shower' },
  'basin':           { w: 2, d: 1, h: 0.8, color: 0xfafaf9, label: 'Basin' },
  // Stairs
  'stairs-straight': { w: 3, d: 8, h: 3.0, color: 0x92400e, label: 'Stairs' },
};

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

const WALL_H       = 2.0;   // wall height (dollhouse look)
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

const WORLD_SIZE = 80;      // 80 tiles = 20 m
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
    this.worldSize = WORLD_SIZE;

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

  _handlePointerDown(e) {
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
      this._rebuildAll();
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
      this._rebuildAll();
      return;
    }

    // ── Furniture placement ────────────────────────────
    if (tool && tool.startsWith('furniture:')) {
      const type = tool.split(':')[1];
      const def = FURNITURE_DEFS[type];
      if (!def) return;
      const snap = this._snapToGrid(pos);
      const id = this.homeGrid.addFurniture(type, snap.x, snap.z, 0);
      this._rebuildAll();
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

  _handlePointerMove(e) {
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
      this._rebuildAll();
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

  _handlePointerUp(e) {
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
      this._rebuildAll();  // re-detect rooms after furniture move
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

    const meshes = [];
    for (const [id, mesh] of this._furnitureMeshes) {
      meshes.push(mesh);
    }
    const hits = this.raycaster.intersectObjects(meshes, false);
    if (hits.length > 0) {
      const mesh = hits[0].object;
      const id = mesh.userData.furnId;
      if (id !== undefined) return { id, mesh };
    }
    return null;
  }

  // ════════════════════════════════════════════════════════
  //  Selection
  // ════════════════════════════════════════════════════════

  _selectFurniture(id) {
    // Deselect previous
    if (this._selectedMesh) {
      this._selectedMesh.material.emissive.setHex(0x000000);
      this._selectedMesh.material.emissiveIntensity = 0;
    }

    this._selectedFurnId = id;
    const mesh = this._furnitureMeshes.get(id);
    if (mesh) {
      this._selectedMesh = mesh;
      mesh.material.emissive.setHex(COLORS.selected);
      mesh.material.emissiveIntensity = 0.4;
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
      this._selectedMesh.material.emissive.setHex(0x000000);
      this._selectedMesh.material.emissiveIntensity = 0;
    }
    this._selectedFurnId = null;
    this._selectedMesh = null;
    if (this.callbacks.onDeselect) this.callbacks.onDeselect();
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

  _rebuildAll() {
    this._rebuildWallMeshes();
    this._rebuildFloorMeshes();
    this._rebuildFurnitureMeshes();
    this._notifyCountChange();
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
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._wallMeshes = [];

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    const walls = floor.walls.getAllWalls();
    const floorY = floor.yOffset;

    // Wall material (shared)
    const wallMat = new THREE.MeshStandardMaterial({
      color: WALL_COLOR,
      roughness: 0.7,
      metalness: 0.05,
      emissive: WALL_EMISSIVE,
      emissiveIntensity: 0.1,
    });

    // Door frame material
    const frameMat = new THREE.MeshStandardMaterial({
      color: DOOR_FRAME_COLOR,
      roughness: 0.5,
      metalness: 0.15,
    });

    // Window glass material
    const glassMat = new THREE.MeshStandardMaterial({
      color: 0x93c5fd,
      roughness: 0.1,
      metalness: 0.3,
      transparent: true,
      opacity: 0.35,
    });

    // Track corner positions for corner posts
    const corners = new Set();

    for (const { x, z, orientation, segment } of walls) {
      const type = segment.type || 'wall';

      if (type === 'wall') {
        this._createWallSegment(x, z, orientation, floorY, WALL_H, wallMat);
        this._registerCorners(x, z, orientation, corners);
      } else if (type === 'door-s' || type === 'door-n') {
        // Door: gap with thin frame on sides
        this._createDoorSegment(x, z, orientation, floorY, frameMat);
      } else if (type === 'window-s' || type === 'window-l') {
        // Window: lower wall + glass gap + upper wall
        this._createWindowSegment(x, z, orientation, floorY, wallMat, glassMat);
      }
    }

    // Corner posts where walls meet
    this._createCornerPosts(corners, floorY, wallMat);
  }

  /** Create a solid wall box for one edge cell. */
  _createWallSegment(x, z, orientation, floorY, h, material) {
    let geo, mesh;
    if (orientation === 'h') {
      // Horizontal edge at (x, z): between cells (x, z-1) and (x, z)
      geo = new THREE.BoxGeometry(1.0, h, WALL_THICK);
      mesh = new THREE.Mesh(geo, material.clone());
      mesh.position.set(x + 0.5, floorY + h / 2, z);
    } else {
      // Vertical edge at (x, z): between cells (x-1, z) and (x, z)
      geo = new THREE.BoxGeometry(WALL_THICK, h, 1.0);
      mesh = new THREE.Mesh(geo, material.clone());
      mesh.position.set(x, floorY + h / 2, z + 0.5);
    }
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    this.scene.add(mesh);
    this._wallMeshes.push(mesh);
  }

  /** Register corner positions for a wall segment. */
  _registerCorners(x, z, orientation, corners) {
    if (orientation === 'h') {
      corners.add(`${x},${z}`);
      corners.add(`${x + 1},${z}`);
    } else {
      corners.add(`${x},${z}`);
      corners.add(`${x},${z + 1}`);
    }
  }

  /** Create a door gap with thin frame posts on the sides. */
  _createDoorSegment(x, z, orientation, floorY, frameMat) {
    // Door frame: two thin vertical posts on each side of the opening,
    // plus a lintel across the top
    const doorH = WALL_H * 0.85;   // door height
    const frameW = 0.04;           // frame post width
    const lintelH = WALL_H - doorH;

    if (orientation === 'h') {
      // Left frame post
      const lgeo = new THREE.BoxGeometry(frameW, doorH, WALL_THICK);
      const lpost = new THREE.Mesh(lgeo, frameMat.clone());
      lpost.position.set(x, floorY + doorH / 2, z);
      this.scene.add(lpost);
      this._wallMeshes.push(lpost);

      // Right frame post
      const rgeo = new THREE.BoxGeometry(frameW, doorH, WALL_THICK);
      const rpost = new THREE.Mesh(rgeo, frameMat.clone());
      rpost.position.set(x + 1, floorY + doorH / 2, z);
      this.scene.add(rpost);
      this._wallMeshes.push(rpost);

      // Lintel above door
      if (lintelH > 0.01) {
        const ltgeo = new THREE.BoxGeometry(1.0, lintelH, WALL_THICK);
        const lintel = new THREE.Mesh(ltgeo, frameMat.clone());
        lintel.position.set(x + 0.5, floorY + doorH + lintelH / 2, z);
        this.scene.add(lintel);
        this._wallMeshes.push(lintel);
      }
    } else {
      // Top frame post
      const tgeo = new THREE.BoxGeometry(WALL_THICK, doorH, frameW);
      const tpost = new THREE.Mesh(tgeo, frameMat.clone());
      tpost.position.set(x, floorY + doorH / 2, z);
      this.scene.add(tpost);
      this._wallMeshes.push(tpost);

      // Bottom frame post
      const bgeo = new THREE.BoxGeometry(WALL_THICK, doorH, frameW);
      const bpost = new THREE.Mesh(bgeo, frameMat.clone());
      bpost.position.set(x, floorY + doorH / 2, z + 1);
      this.scene.add(bpost);
      this._wallMeshes.push(bpost);

      // Lintel
      if (lintelH > 0.01) {
        const ltgeo = new THREE.BoxGeometry(WALL_THICK, lintelH, 1.0);
        const lintel = new THREE.Mesh(ltgeo, frameMat.clone());
        lintel.position.set(x, floorY + doorH + lintelH / 2, z + 0.5);
        this.scene.add(lintel);
        this._wallMeshes.push(lintel);
      }
    }
  }

  /** Create a window: lower wall + glass pane + upper wall strip. */
  _createWindowSegment(x, z, orientation, floorY, wallMat, glassMat) {
    const glassH = WALL_H - WINDOW_SILL_H - WINDOW_HEAD_H;

    if (orientation === 'h') {
      // Sill (lower wall below window)
      if (WINDOW_SILL_H > 0.01) {
        const sgeo = new THREE.BoxGeometry(1.0, WINDOW_SILL_H, WALL_THICK);
        const sill = new THREE.Mesh(sgeo, wallMat.clone());
        sill.position.set(x + 0.5, floorY + WINDOW_SILL_H / 2, z);
        sill.castShadow = true;
        this.scene.add(sill);
        this._wallMeshes.push(sill);
      }
      // Glass pane
      if (glassH > 0.01) {
        const ggeo = new THREE.BoxGeometry(1.0, glassH, WALL_THICK * 0.5);
        const glass = new THREE.Mesh(ggeo, glassMat.clone());
        glass.position.set(x + 0.5, floorY + WINDOW_SILL_H + glassH / 2, z);
        this.scene.add(glass);
        this._wallMeshes.push(glass);
      }
      // Head (upper wall strip above window)
      if (WINDOW_HEAD_H > 0.01) {
        const hgeo = new THREE.BoxGeometry(1.0, WINDOW_HEAD_H, WALL_THICK);
        const head = new THREE.Mesh(hgeo, wallMat.clone());
        head.position.set(x + 0.5, floorY + WALL_H - WINDOW_HEAD_H / 2, z);
        head.castShadow = true;
        this.scene.add(head);
        this._wallMeshes.push(head);
      }
    } else {
      // Vertical orientation
      if (WINDOW_SILL_H > 0.01) {
        const sgeo = new THREE.BoxGeometry(WALL_THICK, WINDOW_SILL_H, 1.0);
        const sill = new THREE.Mesh(sgeo, wallMat.clone());
        sill.position.set(x, floorY + WINDOW_SILL_H / 2, z + 0.5);
        sill.castShadow = true;
        this.scene.add(sill);
        this._wallMeshes.push(sill);
      }
      if (glassH > 0.01) {
        const ggeo = new THREE.BoxGeometry(WALL_THICK * 0.5, glassH, 1.0);
        const glass = new THREE.Mesh(ggeo, glassMat.clone());
        glass.position.set(x, floorY + WINDOW_SILL_H + glassH / 2, z + 0.5);
        this.scene.add(glass);
        this._wallMeshes.push(glass);
      }
      if (WINDOW_HEAD_H > 0.01) {
        const hgeo = new THREE.BoxGeometry(WALL_THICK, WINDOW_HEAD_H, 1.0);
        const head = new THREE.Mesh(hgeo, wallMat.clone());
        head.position.set(x, floorY + WALL_H - WINDOW_HEAD_H / 2, z + 0.5);
        head.castShadow = true;
        this.scene.add(head);
        this._wallMeshes.push(head);
      }
    }
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

  _rebuildFurnitureMeshes() {
    // Clear existing furniture meshes
    for (const [id, mesh] of this._furnitureMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._furnitureMeshes.clear();

    const floor = this.homeGrid.getActiveFloor();
    if (!floor) return;

    const floorY = floor.yOffset;

    for (const [id, furn] of floor.furniture) {
      this._createFurnitureMesh(id, furn, floorY);
    }

    // Re-select if we had a selection
    if (this._selectedFurnId !== null && this._furnitureMeshes.has(this._selectedFurnId)) {
      const mesh = this._furnitureMeshes.get(this._selectedFurnId);
      this._selectedMesh = mesh;
      mesh.material.emissive.setHex(COLORS.selected);
      mesh.material.emissiveIntensity = 0.4;
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

  /** Create a single furniture mesh and add to scene. */
  _createFurnitureMesh(id, furn, floorY) {
    const def = FURNITURE_DEFS[furn.type];
    if (!def) return;

    const { rw, rd } = this._rotatedDims(def, furn.rotation);

    // Special handling for stairs: create stepped geometry
    let mesh;
    if (furn.type === 'stairs-straight') {
      mesh = this._createStairsMesh(def, furn, floorY);
    } else {
      const geo = new THREE.BoxGeometry(rw, def.h, rd);
      const mat = new THREE.MeshStandardMaterial({
        color: def.color,
        roughness: 0.6,
        metalness: 0.1,
      });
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(
        furn.x + rw / 2,
        floorY + def.h / 2,
        furn.z + rd / 2
      );
    }

    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.furnId = id;

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
  loadPreset(preset) {
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

    this._rebuildAll();
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

    // Adjust zoom to fit content
    const spanX = maxX - minX;
    const spanZ = maxZ - minZ;
    const span = Math.max(spanX, spanZ, 10);

    // Calculate zoom needed to fit the span into the view
    const camSize = 28;
    const aspect = this.container.clientWidth / (this.container.clientHeight || 1);
    const viewW = camSize * aspect;
    const viewH = camSize;
    // In isometric view, the diagonal of the content projects differently
    const needed = Math.max(span / viewW, span / viewH) * 1.6;
    const zoom = Math.max(0.2, Math.min(3, 1 / needed));
    this.camera.zoom = zoom;
    this.camera.updateProjectionMatrix();

    // Update camera position to look at new target
    const d = 35;
    this.camera.position.set(cx + d, d, cz + d);
    this.camera.lookAt(this.controls.target);
  }

  // ════════════════════════════════════════════════════════
  //  Floor Management
  // ════════════════════════════════════════════════════════

  /** Switch active floor and rebuild all visuals. */
  setActiveFloor(index) {
    this.homeGrid.setActiveFloor(index);
    this._deselectFurniture();
    this._rebuildAll();
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

  /** Load a home preset from HOME_PRESETS. */
  loadPresetByIndex(index) {
    if (index >= 0 && index < HOME_PRESETS.length) {
      this.loadPreset(HOME_PRESETS[index]);
    }
  }

  /** Clear all data and visuals. */
  clearAll() {
    this._deselectFurniture();

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

    // Clear furniture meshes (including stair groups)
    for (const [id, mesh] of this._furnitureMeshes) {
      if (mesh.userData.stairsGroup) {
        const group = mesh.userData.stairsGroup;
        group.traverse(c => { if (c.geometry) c.geometry.dispose(); });
        this.scene.remove(group);
      }
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
    }
    this._furnitureMeshes.clear();

    this._removeGhostMesh();

    // Reset data model
    this.homeGrid = new HomeGrid();
  }

  /** Remove the currently selected furniture. */
  removeSelected() {
    if (this._selectedFurnId === null) return;
    const id = this._selectedFurnId;

    // Remove mesh
    const mesh = this._furnitureMeshes.get(id);
    if (mesh) {
      if (mesh.userData.stairsGroup) {
        const group = mesh.userData.stairsGroup;
        group.traverse(c => { if (c.geometry) c.geometry.dispose(); });
        this.scene.remove(group);
      }
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
      this._furnitureMeshes.delete(id);
    }

    // Remove from data
    this.homeGrid.removeFurniture(id);
    this._deselectFurniture();
    this._rebuildAll();
  }

  /** Rotate selected furniture by 90 degrees clockwise. */
  rotateSelected() {
    if (this._selectedFurnId === null) return;
    const furn = this._getFurnitureData(this._selectedFurnId);
    if (!furn) return;
    furn.rotation = ((furn.rotation || 0) + 90) % 360;
    this._rebuildFurnitureMeshes();
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
    return HOME_PRESETS;
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
      if (mesh.userData.stairsGroup) {
        mesh.userData.stairsGroup.traverse(c => { if (c.geometry) c.geometry.dispose(); });
      }
      mesh.geometry.dispose();
      if (mesh.material.dispose) mesh.material.dispose();
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
