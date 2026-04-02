# HortPlanner Grid System — Design Specification

## 1. Core Concept: Relative Grids with Isolated Views

Every container (machine hort, sub-hort) has its own **internal grid** — a private
coordinate space where its children live. Children are positioned using **relative
coordinates** within the parent's internal grid.

In the parent's view, a container occupies a small **footprint** (e.g., 2×2 cells).
Its children are rendered at miniature scale (`footprint / internalSize`). To see
the full detail, the user **double-clicks** the container to enter an **isolated view**
(like Blender's "isolate selection"), which shows the container's internal grid at
full size.

```
World View                         Isolated View (Mac Mini)
┌─────────────────────┐           ┌───────────────────────┐
│ ┌─Mac Mini──┐       │  dblclk  │  Mac Mini internal 4×4 │
│ │ [vm][vm]  │       │  ──────► │ ┌──Docker──┐ ┌─VM──┐  │
│ │ [mcp]     │       │          │ │ [nginx]  │ │[app]│  │
│ └───────────┘       │          │ │ [redis]  │ │     │  │
│        ┌─RPi──┐     │          │ └──────────┘ └─────┘  │
│        │[sens]│     │          │ [mcp-server] [llming]  │
│        └──────┘     │          └───────────────────────┘
└─────────────────────┘
  ↑ children are tiny              ↑ children at full size
```

## 2. Grid Units

- **1 grid cell = 1 Three.js unit = 25 cm × 25 cm**
- All positions snap to integer grid coordinates `(x, z)`
- Y axis = height (not part of the grid)

## 3. Component Model

Every component has:

| Field | Description |
|-------|------------|
| `footW × footD` | Footprint in **parent's** grid (cells this component occupies) |
| `innerW × innerD` | Internal grid dimensions (only for containers, min 2×2) |
| `relX, relZ` | Position in parent's internal grid (top-left cell) |
| `gridX, gridZ` | Absolute world position (only for top-level machine horts) |

### Categories

| Category | Where it lives | Footprint in parent | Has internal grid |
|----------|---------------|--------------------|--------------------|
| `machine` | Main world | N/A (world grid) | Yes (4×4 default) |
| `subhort` | Inside machine hort | 2×2 default (resizable) | Yes (4×4 default, min 2×2) |
| `tool` | Inside any container | 1×1 | No |

### Concrete Sizes

**Machine Horts (world level):**

| Type | World footprint | Internal grid | Visual wall |
|------|----------------|--------------|-------------|
| Mac Mini | 4×4 | 4×4 | 0.15 |
| MacBook Pro | 5×3 | 5×3 | 0.15 |
| Raspberry Pi | 3×3 | 3×3 | 0.12 |
| Cloud VM | 4×4 | 4×4 | 0.15 |

**Sub-Horts (inside machine horts):**

| Type | Default footprint | Default internal | Min internal |
|------|------------------|-----------------|-------------|
| Docker | 2×2 | 4×4 | 2×2 |
| Virtual Hort | 2×2 | 4×4 | 2×2 |

**Tools (leaf nodes):**

| Type | Footprint | Internal grid |
|------|----------|--------------|
| MCP Server | 1×1 | None |
| LLMing | 1×1 | None |
| Program | 1×1 | None |

## 4. Rendering: Scale-Relative

When viewing a level, children inside sub-containers are rendered at miniature scale.

**Scale formula:**
```
scaleX = container.footW / container.innerW
scaleZ = container.footD / container.innerD
```

**Child world position (in parent view):**
```
childWorldX = parentWorldX + child.relX × scaleX
childWorldZ = parentWorldZ + child.relZ × scaleZ
```

**Example:** A Docker container in a Mac Mini:
- Docker footprint in Mac Mini = 2×2
- Docker internal grid = 4×4
- Scale = 2/4 = 0.5
- A tool at relative (1, 2) inside Docker renders at parent offset (0.5, 1.0)
- The tool mesh is scaled to 50%

In the **isolated view** of the Docker, everything renders at 1:1 scale.

## 5. Navigation (Isolated View)

The view system works like a stack:

```
Level 0: World          (machine horts on infinite grid)
Level 1: Machine Hort   (sub-horts + tools in hort's internal grid)
Level 2: Sub-Hort       (tools in sub-hort's internal grid)
```

**Enter:** Double-click a container → push to stack, show isolated view
**Exit:** Click breadcrumb or press Escape → pop from stack

When entering a container:
1. Camera smoothly zooms into the container
2. All other components at the current level become hidden
3. The container's internal grid is shown as the new ground plane
4. Children are rendered at full size (1:1 scale)
5. Breadcrumb updates: `World > Mac Mini > Docker`

When exiting:
1. Camera zooms back out
2. Parent level components become visible again
3. Children return to miniature scale

## 6. Sizing & Resize Rules

### No Auto-Resize
- Containers do **not** auto-grow when children are added
- Instead, children are placed in the **first available position** in the internal grid
- If no space is available, the drop is rejected (or the user is warned)

### Exception: Minimal Growth
- If a user drops a component and it literally cannot fit in ANY position, the
  container grows by +1 in the minimal dimension needed to fit
- The container **never auto-shrinks**

### Manual Resize
- The user can manually resize any container (machine hort or sub-hort) by:
  - Selecting it → Properties panel → resize controls
  - Or (future) dragging resize handles
- Resize is in **fixed grid steps** (+1/−1 in width and/or depth)
- Cannot shrink below the minimum (2×2 internal) or below the bounding box of current children
- Growing a machine hort checks world-level collision

### Footprint Resize
- Sub-horts can also have their **footprint** resized in the parent grid
- This changes how large they appear in the parent view
- But the internal grid stays the same (or can be resized independently)

## 6.5 Visual Overflow & Blocked Neighbors

### Visual Overflow
Machine horts may render their 3D model **larger than their grid footprint**,
extending into the mandatory 1-cell gap around them (up to 40% of neighboring cells).

- **SnackMini**: visual width/depth = `innerW + 0.7` (0.35 per side into the gap)
- **SnackBook Pro**: visual extends + the tilted screen blocks 1 additional row behind
- **Strawberry Pi**: slight visual overflow for the PCB edge

This is purely cosmetic — the **grid footprint** determines collision and placement.
The 1-cell gap between horts provides the space for this visual overflow.

### Blocked Neighbor Cells (Screen / Accessories)
Some hort types may **block additional grid cells** beyond their footprint:

| Type | Extra blocked cells | Reason |
|------|-------------------|--------|
| SnackBook Pro | 1 row behind | Tilted screen extends backward |

Blocked cells are marked as `gap` in the world grid and prevent other horts
from being placed there, but are not part of the hort's own footprint.

### Tool Visual Sizing
Tools (MCP Server, LLMing, Program) render at **80% of their grid cell** size,
leaving a visible 10% border on each side. This prevents wall-on-wall contact
with the container they're inside and improves readability.

### Text Labels
- Rendered as white text with a 1.5px dark stroke for contrast
- **Zoom-independent**: labels maintain constant screen size regardless of camera zoom
- No bloom/glow effect on text (prevents flickering)

### Z-Fighting Prevention
Transparent containers (Cloud VM, Virtual Hort) use special material settings
to prevent z-fighting between coplanar faces:

- `side: FrontSide` (not DoubleSide — avoids front/back face overlap)
- `depthWrite: false` (transparent objects don't write to depth buffer)
- `polygonOffset: true` with `factor: 1, units: 1` (nudges depth slightly)

Opaque containers use `DoubleSide` + `depthWrite: true` (no z-fighting risk).
This is critical for nested containers where inner walls overlap parent walls.

## 7. World-Level Placement Rules

### Only Machine Horts
- Only `machine` category components can exist in the main world
- Dragging a sub-hort or tool onto empty world → rejected
- Dragging a sub-hort or tool onto a machine hort → placed inside it

### 1-Cell Gap
- Machine horts must have 1 cell of free space between them in every direction
- This is enforced by the world occupation map

### Snap-to-Grid
- While dragging, components snap to integer grid positions
- Preview shows green (valid) / red (collision) cells

## 8. Inside-Container Placement

### Auto-Find Position
When dropping a component into a container:
1. Scan the container's internal grid left-to-right, top-to-bottom
2. Find the first position where the component fits (no overlap)
3. Place it there
4. If no position found and growth is possible, grow minimally then retry

### Manual Repositioning
Inside the isolated view, the user can drag children to reposition them
(snap to internal grid).

### No Spacing Requirement Inside
Inside containers, components can be placed adjacent (no gap required).
This keeps internal layouts compact.

## 9. Visual Design

### World View (Isometric)
- Fixed SimCity angle, no rotation
- Left-click pan, scroll zoom
- Dark blue infinite grid (subtle animated pulse)
- Machine horts as open-top 3D boxes
- Children visible as miniatures inside

### Isolated View (Isometric)
- Same fixed angle
- Grid matches the container's internal dimensions
- Highlighted border showing the container boundary
- Children at full size
- Back button / breadcrumb to exit

### Flat (2D) View
- Top-down orthographic
- n8n-style dot grid
- Same navigation stack (isolated views work in 2D too)

## 10. Implementation Architecture

### Component Data
```javascript
{
  id: number,
  type: string,
  name: string,

  // Position in parent's grid (or world grid for machine horts)
  gridX: number,          // world X (machine horts only)
  gridZ: number,          // world Z (machine horts only)
  relX: number,           // relative X in parent's internal grid
  relZ: number,           // relative Z in parent's internal grid

  // Size
  footW: number,          // footprint width in parent's grid
  footD: number,          // footprint depth in parent's grid
  innerW: number | null,  // internal grid width (containers only)
  innerD: number | null,  // internal grid depth (containers only)

  // Hierarchy
  parentId: number | null,
  children: number[],

  // Internal occupation grid (containers only)
  internalGrid: InternalGrid | null,

  // Three.js
  mesh: THREE.Group,
}
```

### World Occupation Map
```
GridManager.cells: Map<"x,z", { compId, layer: 'content'|'gap' }>
```
Only tracks machine hort positions in the world.

### Internal Occupation Grid
```
InternalGrid {
  w, d: number              // grid dimensions
  cells: Map<"x,z", childId>  // occupied cells
  canPlace(x, z, fw, fd): boolean
  findSpace(fw, fd): {x, z} | null
  occupy(childId, x, z, fw, fd)
  vacate(childId)
}
```
One per container component. Tracks children within that container.

### View Stack
```
levelStack: [{ id, name }]
currentLevelId: number | null   // null = world
```

### Rendering Update
```
_updateLevelView():
  for each component:
    if currentLevel is null:
      show machine horts at world positions
      show their immediate children at miniature scale
      hide deeper descendants
    else:
      show children of currentLevel at full size in internal grid
      show their sub-children at miniature scale
      hide everything else
```
