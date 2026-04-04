// ═══════════════════════════════════════════════════════════════
//  HortPlanner Grid System
//  - WorldGrid: machine hort placement with 1-cell gap
//  - InternalGrid: per-container child placement (relative coords)
// ═══════════════════════════════════════════════════════════════

// ── Component grid definitions ──────────────────────────────

export const GRID = {
  // Machine Horts — world level (generous defaults for spacious layouts)
  'mac-mini':     { cat: 'machine', innerW: 6, innerD: 6, wall: 0.15 },
  'macbook':      { cat: 'machine', innerW: 7, innerD: 5, wall: 0.15 },
  'rpi':          { cat: 'machine', innerW: 5, innerD: 5, wall: 0.12 },
  'cloud-vm':     { cat: 'machine', innerW: 6, innerD: 6, wall: 0.15 },
  // Sub-Horts — inside machine horts
  'docker':       { cat: 'subhort', footW: 2, footD: 2, innerW: 5, innerD: 5, minInner: 2 },
  'virtual-hort': { cat: 'subhort', footW: 2, footD: 2, innerW: 5, innerD: 5, minInner: 2 },
  // Tools — leaf nodes
  'mcp-server':   { cat: 'tool', footW: 1, footD: 1 },
  'llming':       { cat: 'tool', footW: 1, footD: 1 },
  'program':      { cat: 'tool', footW: 1, footD: 1 },
  // Security
  'agent':        { cat: 'tool', footW: 1, footD: 1 },
  'fence':        { cat: 'tool', footW: 2, footD: 2 },
};

function key(x, z) { return `${x},${z}`; }

// ── World Occupation Map ────────────────────────────────────

export class WorldGrid {
  constructor() {
    this.cells = new Map();      // "x,z" → { compId, layer: 'content'|'gap' }
    this.compRects = new Map();  // compId → { x, z, w, d }
  }

  occupy(compId, x, z, w, d) {
    for (let cx = x; cx < x + w; cx++)
      for (let cz = z; cz < z + d; cz++)
        this.cells.set(key(cx, cz), { compId, layer: 'content' });
    for (let cx = x - 1; cx <= x + w; cx++)
      for (let cz = z - 1; cz <= z + d; cz++) {
        const k = key(cx, cz);
        if (!this.cells.has(k))
          this.cells.set(k, { compId, layer: 'gap' });
      }
    this.compRects.set(compId, { x, z, w, d });
  }

  vacate(compId) {
    for (const [k, v] of this.cells)
      if (v.compId === compId) this.cells.delete(k);
    this.compRects.delete(compId);
  }

  canPlace(x, z, w, d, ignoreId = null) {
    const conflicts = [];
    for (let cx = x - 1; cx <= x + w; cx++)
      for (let cz = z - 1; cz <= z + d; cz++) {
        const cell = this.cells.get(key(cx, cz));
        if (cell && cell.compId !== ignoreId)
          conflicts.push({ x: cx, z: cz, compId: cell.compId, layer: cell.layer });
      }
    return { valid: conflicts.length === 0, conflicts };
  }

  move(compId, newX, newZ) {
    const rect = this.compRects.get(compId);
    if (!rect) return false;
    this.vacate(compId);
    if (!this.canPlace(newX, newZ, rect.w, rect.d).valid) {
      this.occupy(compId, rect.x, rect.z, rect.w, rect.d);
      return false;
    }
    this.occupy(compId, newX, newZ, rect.w, rect.d);
    return true;
  }

  /** Check if world position (float) hits a machine hort content cell. */
  hortAt(wx, wz) {
    const cell = this.cells.get(key(Math.floor(wx), Math.floor(wz)));
    if (cell && cell.layer === 'content') return cell.compId;
    return null;
  }

  getContentCells(x, z, w, d) {
    const out = [];
    for (let cx = x; cx < x + w; cx++)
      for (let cz = z; cz < z + d; cz++) out.push({ x: cx, z: cz });
    return out;
  }

  getGapCells(x, z, w, d) {
    const out = [];
    for (let cx = x - 1; cx <= x + w; cx++)
      for (let cz = z - 1; cz <= z + d; cz++) {
        if (cx >= x && cx < x + w && cz >= z && cz < z + d) continue;
        out.push({ x: cx, z: cz });
      }
    return out;
  }

  clear() { this.cells.clear(); this.compRects.clear(); }
}

// ── Internal Grid (per container) ───────────────────────────

export class InternalGrid {
  constructor(w, d) {
    this.w = w;
    this.d = d;
    this.cells = new Map();      // "x,z" → { id: childId, layer: 'content'|'gap' }
    this.childRects = new Map(); // childId → { x, z, w, d }
  }

  canPlace(x, z, fw, fd) {
    for (let cx = x; cx < x + fw; cx++)
      for (let cz = z; cz < z + fd; cz++) {
        if (cx < 0 || cx >= this.w || cz < 0 || cz >= this.d) return false;
        if (this.cells.has(key(cx, cz))) return false;
      }
    return true;
  }

  occupy(childId, x, z, fw, fd) {
    // content cells
    for (let cx = x; cx < x + fw; cx++)
      for (let cz = z; cz < z + fd; cz++)
        this.cells.set(key(cx, cz), { id: childId, layer: 'content' });
    // 1-cell gap border (prevents adjacent placement)
    for (let cx = x - 1; cx <= x + fw; cx++)
      for (let cz = z - 1; cz <= z + fd; cz++) {
        const k = key(cx, cz);
        if (!this.cells.has(k))
          this.cells.set(k, { id: childId, layer: 'gap' });
      }
    this.childRects.set(childId, { x, z, w: fw, d: fd });
  }

  vacate(childId) {
    for (const [k, v] of this.cells)
      if (v.id === childId) this.cells.delete(k);
    this.childRects.delete(childId);
  }

  /** Find first position where (fw × fd) fits, scanning left→right, top→bottom. */
  findSpace(fw, fd) {
    for (let z = 0; z <= this.d - fd; z++)
      for (let x = 0; x <= this.w - fw; x++)
        if (this.canPlace(x, z, fw, fd)) return { x, z };
    return null;
  }

  /** Move a child within this grid. Returns false if collision. */
  move(childId, newX, newZ) {
    const rect = this.childRects.get(childId);
    if (!rect) return false;
    this.vacate(childId);
    if (!this.canPlace(newX, newZ, rect.w, rect.d)) {
      this.occupy(childId, rect.x, rect.z, rect.w, rect.d);
      return false;
    }
    this.occupy(childId, newX, newZ, rect.w, rect.d);
    return true;
  }

  /** Grow the grid (only expand, never shrink). */
  grow(newW, newD) {
    this.w = Math.max(this.w, newW);
    this.d = Math.max(this.d, newD);
  }

  /** Find minimum bounding box of occupied cells. */
  boundingBox() {
    let minX = this.w, minZ = this.d, maxX = 0, maxZ = 0;
    for (const [, rect] of this.childRects) {
      minX = Math.min(minX, rect.x);
      minZ = Math.min(minZ, rect.z);
      maxX = Math.max(maxX, rect.x + rect.w);
      maxZ = Math.max(maxZ, rect.z + rect.d);
    }
    return { minX, minZ, maxX, maxZ, w: maxX - minX, d: maxZ - minZ };
  }
}
