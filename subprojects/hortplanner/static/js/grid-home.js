// ═══════════════════════════════════════════════════════════════
//  HortPlanner Home Grid System
//  - WallGrid: edge-based wall storage (25cm x 25cm cells)
//  - FloorData: per-floor walls, furniture, auto-detected rooms
//  - HomeGrid: multi-floor manager
//  - RoomDetector: flood-fill room detection
// ═══════════════════════════════════════════════════════════════

function key(x, z) { return `${x},${z}`; }

// ── Wall segment types ─────────────────────────────────────
//  wall     — solid wall
//  door-s   — small door  (50cm = 2 tiles wide)
//  door-n   — normal door (75cm = 3 tiles wide)
//  window-s — small window (50cm = 2 tiles)
//  window-l — large window (100cm = 4 tiles)

/** Create a wall segment descriptor. */
function wallSegment(type = 'wall', material = 'default') {
  return { type, material };
}

// ── WallGrid ───────────────────────────────────────────────

export class WallGrid {
  constructor() {
    this.hEdges = new Map();  // "x,z" -> WallSegment (horizontal edge)
    this.vEdges = new Map();  // "x,z" -> WallSegment (vertical edge)
    this.dEdges = new Map();  // "x,z,d+|d-" -> WallSegment (diagonal edges: d+ = NE-SW, d- = NW-SE)
  }

  /** Get the edge map for the given orientation. */
  _edges(orientation) {
    if (orientation === 'h') return this.hEdges;
    if (orientation === 'v') return this.vEdges;
    return this.dEdges; // d+ or d-
  }

  _dkey(x, z, o) { return `${x},${z},${o}`; }

  /** Place a wall segment on the edge at (x, z) with orientation 'h', 'v', 'd+', or 'd-'. */
  setWall(x, z, orientation, segment) {
    const k = (orientation === 'd+' || orientation === 'd-') ? this._dkey(x, z, orientation) : key(x, z);
    this._edges(orientation).set(k, segment);
  }

  /** Remove the wall segment at (x, z) with orientation. */
  removeWall(x, z, orientation) {
    const k = (orientation === 'd+' || orientation === 'd-') ? this._dkey(x, z, orientation) : key(x, z);
    this._edges(orientation).delete(k);
  }

  /** Get the wall segment at (x, z) with orientation, or null. */
  getWall(x, z, orientation) {
    const k = (orientation === 'd+' || orientation === 'd-') ? this._dkey(x, z, orientation) : key(x, z);
    return this._edges(orientation).get(k) || null;
  }

  /** Check whether a wall exists at (x, z) with orientation. */
  hasWall(x, z, orientation) {
    const k = (orientation === 'd+' || orientation === 'd-') ? this._dkey(x, z, orientation) : key(x, z);
    return this._edges(orientation).has(k);
  }

  /** Return all walls as an array of { x, z, orientation, segment }. */
  getAllWalls() {
    const walls = [];
    for (const [k, segment] of this.hEdges) {
      const [x, z] = k.split(',').map(Number);
      walls.push({ x, z, orientation: 'h', segment });
    }
    for (const [k, segment] of this.vEdges) {
      const [x, z] = k.split(',').map(Number);
      walls.push({ x, z, orientation: 'v', segment });
    }
    for (const [k, segment] of this.dEdges) {
      const parts = k.split(',');
      const x = Number(parts[0]), z = Number(parts[1]), o = parts[2];
      walls.push({ x, z, orientation: o, segment });
    }
    return walls;
  }

  /** Return walls whose edge coordinates fall within the bounding box [x1..x2, z1..z2]. */
  getWallsInRange(x1, z1, x2, z2) {
    const walls = [];
    for (const [k, segment] of this.hEdges) {
      const [x, z] = k.split(',').map(Number);
      if (x >= x1 && x <= x2 && z >= z1 && z <= z2)
        walls.push({ x, z, orientation: 'h', segment });
    }
    for (const [k, segment] of this.vEdges) {
      const [x, z] = k.split(',').map(Number);
      if (x >= x1 && x <= x2 && z >= z1 && z <= z2)
        walls.push({ x, z, orientation: 'v', segment });
    }
    return walls;
  }
}

// ── RoomDetector ───────────────────────────────────────────

export class RoomDetector {
  /**
   * Flood-fill room detection.
   *
   * Scans all cells in [0..gridW-1] x [0..gridH-1], grouping connected cells
   * (connected = no wall edge between them) into rooms. The exterior region
   * (largest group or any group whose cells touch the grid boundary) is filtered out.
   *
   * @param {WallGrid} wallGrid
   * @param {number} gridW  - grid width in cells
   * @param {number} gridH  - grid height in cells (z-axis)
   * @returns {Array<{id: number, cells: Array<{x: number, z: number}>, bounds: {minX: number, minZ: number, maxX: number, maxZ: number}}>}
   */
  static detectRooms(wallGrid, gridW, gridH) {
    const visited = new Set();
    const rooms = [];
    let nextId = 1;

    for (let z = 0; z < gridH; z++) {
      for (let x = 0; x < gridW; x++) {
        const k = key(x, z);
        if (visited.has(k)) continue;

        // Flood-fill from this cell
        const cells = [];
        const queue = [{ x, z }];
        visited.add(k);

        while (queue.length > 0) {
          const cur = queue.shift();

          cells.push({ x: cur.x, z: cur.z });

          // Try 4 neighbors: +x, -x, +z, -z
          const neighbors = [
            // Moving to (cur.x+1, cur.z): blocked by vEdge at (cur.x+1, cur.z)
            { nx: cur.x + 1, nz: cur.z, wx: cur.x + 1, wz: cur.z, o: 'v' },
            // Moving to (cur.x-1, cur.z): blocked by vEdge at (cur.x, cur.z)
            { nx: cur.x - 1, nz: cur.z, wx: cur.x, wz: cur.z, o: 'v' },
            // Moving to (cur.x, cur.z+1): blocked by hEdge at (cur.x, cur.z+1)
            { nx: cur.x, nz: cur.z + 1, wx: cur.x, wz: cur.z + 1, o: 'h' },
            // Moving to (cur.x, cur.z-1): blocked by hEdge at (cur.x, cur.z)
            { nx: cur.x, nz: cur.z - 1, wx: cur.x, wz: cur.z, o: 'h' },
          ];

          for (const { nx, nz, wx, wz, o } of neighbors) {
            if (nx < 0 || nx >= gridW || nz < 0 || nz >= gridH) continue;
            const nk = key(nx, nz);
            if (visited.has(nk)) continue;
            if (wallGrid.hasWall(wx, wz, o)) continue;
            visited.add(nk);
            queue.push({ x: nx, z: nz });
          }
        }

        // Compute bounding box
        let minX = gridW, minZ = gridH, maxX = 0, maxZ = 0;
        for (const c of cells) {
          if (c.x < minX) minX = c.x;
          if (c.z < minZ) minZ = c.z;
          if (c.x > maxX) maxX = c.x;
          if (c.z > maxZ) maxZ = c.z;
        }

        rooms.push({
          id: nextId++,
          cells,
          bounds: { minX, minZ, maxX, maxZ },
        });
      }
    }

    // Filter out the exterior: the largest room, or any room touching the grid boundary
    const touchesBoundary = (room) =>
      room.cells.some(c => c.x === 0 || c.z === 0 || c.x === gridW - 1 || c.z === gridH - 1);

    // Find the largest boundary-touching room (exterior)
    let exteriorId = -1;
    let exteriorSize = 0;
    for (const room of rooms) {
      if (touchesBoundary(room) && room.cells.length > exteriorSize) {
        exteriorSize = room.cells.length;
        exteriorId = room.id;
      }
    }

    // If no boundary-touching room found, use the largest overall
    if (exteriorId === -1 && rooms.length > 0) {
      let maxSize = 0;
      for (const room of rooms) {
        if (room.cells.length > maxSize) {
          maxSize = room.cells.length;
          exteriorId = room.id;
        }
      }
    }

    return rooms.filter(r => r.id !== exteriorId);
  }
}

// ── FloorData ──────────────────────────────────────────────

export class FloorData {
  /**
   * @param {number} index - Floor index: -1 (basement), 0 (ground), 0.5 (mezzanine), 1, 2, ...
   */
  constructor(index) {
    this.index = index;
    this.walls = new WallGrid();
    this.furniture = new Map();  // id -> { type, x, z, rotation, ... }
    this.rooms = [];             // auto-detected via RoomDetector
    this.yOffset = index * 12;   // 12 tiles = 3m floor height
    this._nextFurnId = 1;
  }

  /** Run room detection and update this.rooms. */
  detectRooms(gridW, gridH) {
    this.rooms = RoomDetector.detectRooms(this.walls, gridW, gridH);
    return this.rooms;
  }

  /**
   * Add furniture to this floor.
   * @param {string} type - furniture type identifier
   * @param {number} x - grid x position
   * @param {number} z - grid z position
   * @param {number} rotation - rotation in degrees (0, 90, 180, 270)
   * @returns {number} furniture id
   */
  addFurniture(type, x, z, rotation = 0) {
    const id = this._nextFurnId++;
    this.furniture.set(id, { type, x, z, rotation });
    return id;
  }

  /** Remove furniture by id. Returns true if removed. */
  removeFurniture(id) {
    return this.furniture.delete(id);
  }
}

// ── HomeGrid ───────────────────────────────────────────────

export class HomeGrid {
  constructor() {
    this.floors = new Map();     // index -> FloorData
    this.activeFloor = 0;
    this._nextFurnId = 1;
    this.addFloor(0);            // start with ground floor
  }

  /** Add a new floor at the given index. No-op if it already exists. */
  addFloor(index) {
    if (this.floors.has(index)) return;
    const floor = new FloorData(index);
    floor._nextFurnId = this._nextFurnId;
    this.floors.set(index, floor);
  }

  /** Remove a floor by index. Cannot remove the last floor. */
  removeFloor(index) {
    if (this.floors.size <= 1) return false;
    const removed = this.floors.delete(index);
    if (removed && this.activeFloor === index) {
      // Switch to nearest floor
      const indices = this.getFloorIndices();
      this.activeFloor = indices[0];
    }
    return removed;
  }

  /** Get the FloorData for a given index, or undefined. */
  getFloor(index) {
    return this.floors.get(index);
  }

  /** Set the active floor index. */
  setActiveFloor(index) {
    if (this.floors.has(index)) {
      this.activeFloor = index;
    }
  }

  /** Get the currently active FloorData. */
  getActiveFloor() {
    return this.floors.get(this.activeFloor);
  }

  /** Get all floor indices, sorted ascending. */
  getFloorIndices() {
    return [...this.floors.keys()].sort((a, b) => a - b);
  }

  /**
   * Add furniture to the active floor. Global ID allocation ensures
   * unique IDs across all floors.
   * @returns {number} furniture id
   */
  addFurniture(type, x, z, rotation = 0) {
    const floor = this.getActiveFloor();
    if (!floor) return -1;
    const id = this._nextFurnId++;
    floor.furniture.set(id, { type, x, z, rotation });
    return id;
  }

  /** Remove furniture by id from any floor. */
  removeFurniture(id) {
    for (const floor of this.floors.values()) {
      if (floor.furniture.delete(id)) return true;
    }
    return false;
  }

  /** Run room detection on all floors. */
  detectAllRooms(gridW, gridH) {
    for (const floor of this.floors.values()) {
      floor.detectRooms(gridW, gridH);
    }
  }
}
