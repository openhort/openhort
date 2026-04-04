// ═══════════════════════════════════════════════════════════════
//  HortPlanner — Undo/Redo History + YAML State Serialization
//
//  Every mutation to the world is an Action. Actions are recorded
//  in a stack and can be undone/redone. The world state can be
//  serialized to YAML-compatible JSON at any time.
// ═══════════════════════════════════════════════════════════════

/**
 * Action types:
 *   place     — place a machine hort in the world
 *   addChild  — add a sub-hort or tool inside a container
 *   remove    — remove a component (and its children)
 *   move      — move a machine hort to a new grid position
 *   connect   — create a connection between two ports
 *   disconnect — remove a connection
 *   resize    — resize a container's internal grid
 */

export class ActionHistory {
  constructor() {
    this.undoStack = [];
    this.redoStack = [];
    this._onChange = null; // callback: () => void
  }

  /** Register a callback for state changes (undo/redo availability). */
  onChange(fn) { this._onChange = fn; }

  /** Record and execute an action. Clears redo stack. */
  push(action) {
    this.undoStack.push(action);
    this.redoStack = [];
    this._notify();
  }

  /** Undo the last action. Returns the action or null. */
  undo() {
    if (this.undoStack.length === 0) return null;
    const action = this.undoStack.pop();
    this.redoStack.push(action);
    this._notify();
    return action;
  }

  /** Redo the last undone action. Returns the action or null. */
  redo() {
    if (this.redoStack.length === 0) return null;
    const action = this.redoStack.pop();
    this.undoStack.push(action);
    this._notify();
    return action;
  }

  get canUndo() { return this.undoStack.length > 0; }
  get canRedo() { return this.redoStack.length > 0; }

  clear() {
    this.undoStack = [];
    this.redoStack = [];
    this._notify();
  }

  _notify() { this._onChange?.(); }
}

// ── World State Serialization ───────────────────────────────

/**
 * Serialize the engine's world state to a YAML-compatible plain object.
 * Can be converted to YAML with js-yaml or JSON.stringify.
 */
export function serializeWorld(engine) {
  const components = [];
  const idToIndex = new Map();

  // first pass: assign indices to all components
  let idx = 0;
  engine.components.forEach((comp, id) => {
    idToIndex.set(id, idx++);
  });

  // second pass: serialize
  engine.components.forEach((comp, id) => {
    const entry = {
      type: comp.type,
      name: comp.name,
    };

    if (comp.parentId === null) {
      // world-level component
      entry.gridX = comp.gridX;
      entry.gridZ = comp.gridZ;
    } else {
      entry.parent = idToIndex.get(comp.parentId);
      entry.relX = comp.relX;
      entry.relZ = comp.relZ;
    }

    entry.footW = comp.footW;
    entry.footD = comp.footD;

    if (comp.innerW != null) {
      entry.innerW = comp.innerW;
      entry.innerD = comp.innerD;
    }

    components.push(entry);
  });

  const connections = engine.connections.map(conn => ({
    from: { component: idToIndex.get(conn.from.compId), port: conn.from.portIndex },
    to: { component: idToIndex.get(conn.to.compId), port: conn.to.portIndex },
  }));

  return {
    version: 1,
    worldSize: engine.worldSize,
    components,
    connections,
  };
}

/**
 * Deserialize a world state back into the engine.
 * This is equivalent to loading a preset but from saved state.
 */
export async function deserializeWorld(engine, state) {
  engine.clearAll();
  engine.worldSize = state.worldSize || 50;

  // Convert to preset format and use loadPreset
  const preset = {
    components: state.components.map(c => ({
      type: c.type,
      name: c.name,
      x: c.gridX ?? 0,
      z: c.gridZ ?? 0,
      parent: c.parent,
    })),
    connections: state.connections.map(c => [
      c.from.component, c.from.port,
      c.to.component, c.to.port,
    ]),
  };

  await engine.loadPreset(preset);
}
