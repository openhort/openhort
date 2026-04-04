// ═══════════════════════════════════════════════════════════════
//  HortPlanner — Home / Apartment Presets
//
//  Each grid cell = 25 cm.  So 4 m = 16 tiles, 1 m = 4 tiles.
//
//  walls:     [x1, z1, x2, z2]  — line segment (h or v only)
//             Horizontal (z1===z2): h-edges from x1..x2-1
//             Vertical   (x1===x2): v-edges from z1..z2-1
//  doors:     { x, z, o: 'h'|'v', type }
//  windows:   { x, z, o: 'h'|'v', type }
//  furniture: { type, x, z, rot }   (rot in degrees: 0/90/180/270)
//
//  Furniture sizes (approximate tile footprints):
//    bed-double 6×8, bed-single 4×8, wardrobe 6×2, desk 4×2
//    nightstand 2×2, sofa 8×3, armchair 3×3, tv 4×1
//    coffee-table 4×2, bookshelf 4×1, dining-table 4×4, chair 2×2
//    counter 4×2, stove 2×2, fridge 3×3, sink 2×2
//    toilet 2×3, shower 3×3, bathtub 3×7, basin 2×2
//    stairs-straight 4×8
// ═══════════════════════════════════════════════════════════════

export const HOME_PRESETS = [

// ─── 1. Studio Apartment (25 sqm, ~10×10 m = 40×40) ──────
{
  name: 'Studio Apartment',
  desc: '25 sqm open plan, kitchenette, bathroom',
  floors: {
    0: {
      walls: [
        // Outer walls (40×40)
        [0, 0, 40, 0],      // top
        [0, 0, 0, 40],      // left
        [40, 0, 40, 40],    // right
        [0, 40, 40, 40],    // bottom
        // Bathroom partition (top-right corner, 3×2.5 m = 12×10)
        [28, 0, 28, 10],    // bathroom left wall
        [28, 10, 40, 10],   // bathroom bottom wall
      ],
      doors: [
        { x: 4, z: 40, o: 'h', type: 'door-n' },    // entry door (bottom wall)
        { x: 28, z: 4, o: 'v', type: 'door-s' },     // bathroom door
      ],
      windows: [
        { x: 16, z: 0, o: 'h', type: 'window-l' },   // top wall window (living)
        { x: 34, z: 0, o: 'h', type: 'window-s' },    // top wall window (bathroom)
      ],
      furniture: [
        // Bathroom (top-right)
        { type: 'toilet', x: 30, z: 1, rot: 0 },
        { type: 'shower', x: 37, z: 1, rot: 0 },
        { type: 'basin', x: 34, z: 1, rot: 0 },
        // Kitchen (bottom-right)
        { type: 'counter', x: 36, z: 14, rot: 90 },
        { type: 'stove', x: 36, z: 18, rot: 90 },
        { type: 'fridge', x: 37, z: 22, rot: 0 },
        { type: 'sink', x: 36, z: 26, rot: 90 },
        // Living / sleeping
        { type: 'bed-double', x: 2, z: 2, rot: 0 },
        { type: 'nightstand', x: 8, z: 2, rot: 0 },
        { type: 'wardrobe', x: 2, z: 12, rot: 0 },
        { type: 'sofa', x: 12, z: 30, rot: 0 },
        { type: 'coffee-table', x: 14, z: 26, rot: 0 },
        { type: 'tv', x: 14, z: 22, rot: 0 },
        { type: 'dining-table', x: 24, z: 30, rot: 0 },
        { type: 'chair', x: 24, z: 28, rot: 0 },
        { type: 'chair', x: 28, z: 30, rot: 90 },
      ],
    },
  },
},

// ─── 2. 1-Bedroom Apartment (45 sqm, ~9×12 m = 36×48) ────
{
  name: '1-Bedroom Apartment',
  desc: '45 sqm, entry hall, open living/kitchen, bedroom, bathroom',
  floors: {
    0: {
      walls: [
        // Outer walls (36×48)
        [0, 0, 36, 0],
        [0, 0, 0, 48],
        [36, 0, 36, 48],
        [0, 48, 36, 48],
        // Entry hall / hallway bottom partition at z=40
        [0, 40, 14, 40],
        // Bedroom wall (left side, z=0..24)
        [14, 0, 14, 24],
        // Bathroom (bottom-right, 2.5×3 m = 10×12)
        [26, 36, 26, 48],    // bathroom left wall
        [26, 36, 36, 36],    // bathroom top wall
      ],
      doors: [
        { x: 16, z: 48, o: 'h', type: 'door-n' },    // main entry
        { x: 14, z: 10, o: 'v', type: 'door-s' },     // bedroom door
        { x: 26, z: 40, o: 'v', type: 'door-s' },     // bathroom door
        { x: 6, z: 40, o: 'h', type: 'door-n' },      // hall to living
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },     // bedroom window
        { x: 22, z: 0, o: 'h', type: 'window-l' },    // living window
        { x: 36, z: 14, o: 'v', type: 'window-l' },   // kitchen side window
      ],
      furniture: [
        // Bedroom (top-left, 0..14 x 0..24)
        { type: 'bed-double', x: 2, z: 8, rot: 0 },
        { type: 'nightstand', x: 8, z: 8, rot: 0 },
        { type: 'wardrobe', x: 2, z: 18, rot: 0 },
        { type: 'desk', x: 9, z: 18, rot: 0 },
        // Living room (top-right, 14..36 x 0..24)
        { type: 'sofa', x: 16, z: 14, rot: 0 },
        { type: 'coffee-table', x: 18, z: 10, rot: 0 },
        { type: 'tv', x: 18, z: 6, rot: 0 },
        { type: 'bookshelf', x: 16, z: 2, rot: 0 },
        // Kitchen (right side, z=24..36)
        { type: 'counter', x: 32, z: 26, rot: 90 },
        { type: 'stove', x: 32, z: 30, rot: 90 },
        { type: 'sink', x: 32, z: 34, rot: 90 },
        { type: 'fridge', x: 33, z: 24, rot: 0 },
        { type: 'dining-table', x: 20, z: 28, rot: 0 },
        { type: 'chair', x: 20, z: 26, rot: 0 },
        { type: 'chair', x: 24, z: 26, rot: 0 },
        { type: 'chair', x: 20, z: 32, rot: 180 },
        { type: 'chair', x: 24, z: 32, rot: 180 },
        // Bathroom (bottom-right)
        { type: 'toilet', x: 28, z: 38, rot: 0 },
        { type: 'shower', x: 33, z: 38, rot: 0 },
        { type: 'basin', x: 28, z: 44, rot: 0 },
      ],
    },
  },
},

// ─── 3. 2-Bedroom Apartment (70 sqm, ~10×14 m = 40×56) ───
{
  name: '2-Bedroom Apartment',
  desc: '70 sqm, living room, kitchen, 2 bedrooms, bathroom, hallway',
  floors: {
    0: {
      walls: [
        // Outer walls (40×56)
        [0, 0, 40, 0],
        [0, 0, 0, 56],
        [40, 0, 40, 56],
        [0, 56, 40, 56],
        // Hallway spine at x=16 (from z=24 to bottom)
        [16, 24, 16, 56],
        // Bedroom 1 wall (top-left, ends at z=24)
        [0, 24, 16, 24],
        // Bedroom 2 wall (top-right)
        [16, 0, 16, 24],
        [16, 24, 40, 24],
        // Kitchen divider (bottom-left, z=40)
        [0, 40, 16, 40],
        // Bathroom (bottom-right, 2.5×3 m)
        [28, 44, 40, 44],    // bathroom top
        [28, 44, 28, 56],    // bathroom left
      ],
      doors: [
        { x: 20, z: 56, o: 'h', type: 'door-n' },   // main entry
        { x: 8, z: 24, o: 'h', type: 'door-n' },     // bedroom 1
        { x: 16, z: 10, o: 'v', type: 'door-s' },    // bedroom 2
        { x: 8, z: 40, o: 'h', type: 'door-n' },     // kitchen
        { x: 28, z: 48, o: 'v', type: 'door-s' },    // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },    // bedroom 1
        { x: 28, z: 0, o: 'h', type: 'window-l' },   // bedroom 2
        { x: 0, z: 32, o: 'v', type: 'window-l' },   // kitchen
        { x: 0, z: 48, o: 'v', type: 'window-s' },   // living
        { x: 40, z: 32, o: 'v', type: 'window-l' },  // living side
      ],
      furniture: [
        // Bedroom 1 (top-left 0..16 x 0..24)
        { type: 'bed-double', x: 2, z: 2, rot: 0 },
        { type: 'nightstand', x: 8, z: 2, rot: 0 },
        { type: 'wardrobe', x: 2, z: 14, rot: 0 },
        // Bedroom 2 (top-right 16..40 x 0..24)
        { type: 'bed-single', x: 18, z: 2, rot: 0 },
        { type: 'desk', x: 30, z: 2, rot: 0 },
        { type: 'wardrobe', x: 18, z: 14, rot: 0 },
        { type: 'bookshelf', x: 34, z: 2, rot: 90 },
        // Kitchen (bottom-left 0..16 x 40..56)
        { type: 'counter', x: 2, z: 42, rot: 0 },
        { type: 'stove', x: 6, z: 42, rot: 0 },
        { type: 'sink', x: 10, z: 42, rot: 0 },
        { type: 'fridge', x: 13, z: 42, rot: 0 },
        // Living / Dining (bottom center-right)
        { type: 'sofa', x: 18, z: 36, rot: 0 },
        { type: 'coffee-table', x: 20, z: 32, rot: 0 },
        { type: 'tv', x: 20, z: 28, rot: 0 },
        { type: 'dining-table', x: 18, z: 44, rot: 0 },
        { type: 'chair', x: 18, z: 42, rot: 0 },
        { type: 'chair', x: 22, z: 42, rot: 0 },
        { type: 'chair', x: 18, z: 48, rot: 180 },
        { type: 'chair', x: 22, z: 48, rot: 180 },
        // Bathroom (bottom-right 28..40 x 44..56)
        { type: 'toilet', x: 30, z: 46, rot: 0 },
        { type: 'shower', x: 37, z: 46, rot: 0 },
        { type: 'basin', x: 30, z: 52, rot: 0 },
        { type: 'bathtub', x: 34, z: 50, rot: 0 },
      ],
    },
  },
},

// ─── 4. Loft Apartment (80 sqm, ~10×16 m = 40×64) ────────
{
  name: 'Loft Apartment',
  desc: '80 sqm open space, bathroom, mezzanine bedroom',
  floors: {
    0: {
      walls: [
        // Outer walls (40×64)
        [0, 0, 40, 0],
        [0, 0, 0, 64],
        [40, 0, 40, 64],
        [0, 64, 40, 64],
        // Bathroom enclosure (bottom-right, 3×2.5 m = 12×10)
        [28, 54, 28, 64],   // bathroom left
        [28, 54, 40, 54],   // bathroom top
      ],
      doors: [
        { x: 16, z: 64, o: 'h', type: 'door-n' },    // main entry
        { x: 28, z: 58, o: 'v', type: 'door-s' },     // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },
        { x: 16, z: 0, o: 'h', type: 'window-l' },
        { x: 28, z: 0, o: 'h', type: 'window-l' },
        { x: 0, z: 20, o: 'v', type: 'window-l' },
        { x: 40, z: 20, o: 'v', type: 'window-l' },
      ],
      furniture: [
        // Open living area
        { type: 'sofa', x: 4, z: 16, rot: 0 },
        { type: 'coffee-table', x: 6, z: 12, rot: 0 },
        { type: 'tv', x: 6, z: 6, rot: 0 },
        { type: 'armchair', x: 16, z: 14, rot: 270 },
        { type: 'bookshelf', x: 14, z: 2, rot: 0 },
        // Kitchen area (right side, ground floor)
        { type: 'counter', x: 36, z: 4, rot: 90 },
        { type: 'stove', x: 36, z: 8, rot: 90 },
        { type: 'sink', x: 36, z: 12, rot: 90 },
        { type: 'fridge', x: 37, z: 16, rot: 0 },
        // Dining
        { type: 'dining-table', x: 24, z: 24, rot: 0 },
        { type: 'chair', x: 24, z: 22, rot: 0 },
        { type: 'chair', x: 28, z: 22, rot: 0 },
        { type: 'chair', x: 24, z: 28, rot: 180 },
        { type: 'chair', x: 28, z: 28, rot: 180 },
        // Stairs to mezzanine
        { type: 'stairs-straight', x: 2, z: 36, rot: 0 },
        // Bathroom
        { type: 'toilet', x: 30, z: 56, rot: 0 },
        { type: 'shower', x: 37, z: 56, rot: 0 },
        { type: 'basin', x: 34, z: 56, rot: 0 },
      ],
    },
    0.5: {
      walls: [
        // Mezzanine railing (open on one side)
        // Mezzanine covers left half: 0..20 x 32..64 (5×8 m)
        [0, 32, 20, 32],    // railing front
        [20, 32, 20, 64],   // railing right side
        [0, 32, 0, 64],     // left wall (shared with outer)
        [0, 64, 20, 64],    // back wall (shared with outer)
      ],
      doors: [],
      windows: [],
      furniture: [
        { type: 'bed-double', x: 2, z: 36, rot: 0 },
        { type: 'nightstand', x: 8, z: 36, rot: 0 },
        { type: 'nightstand', x: 2, z: 44, rot: 0 },
        { type: 'wardrobe', x: 12, z: 36, rot: 0 },
        { type: 'desk', x: 2, z: 56, rot: 0 },
      ],
    },
  },
},

// ─── 5. Small House (90 sqm, ~10×18 m = 40×72) ───────────
{
  name: 'Small House',
  desc: '90 sqm single floor, living, kitchen, 2 bedrooms, bathroom, hallway',
  floors: {
    0: {
      walls: [
        // Outer walls (40×72)
        [0, 0, 40, 0],
        [0, 0, 0, 72],
        [40, 0, 40, 72],
        [0, 72, 40, 72],
        // Hallway (center spine x=16, from entry z=56 upward)
        [16, 28, 16, 72],
        // Bedroom 1 (top-left, 0..16 x 0..28)
        [0, 28, 16, 28],
        // Bedroom 2 (top-right, 16..40 x 0..28)
        [16, 0, 16, 28],
        [16, 28, 40, 28],
        // Living room (bottom-left, 0..16 x 28..56)
        [0, 56, 16, 56],
        // Kitchen (bottom-right, 16..40 x 28..56)
        [16, 56, 40, 56],
        // Bathroom (bottom-right corner, 28..40 x 56..72)
        [28, 56, 28, 72],
      ],
      doors: [
        { x: 20, z: 72, o: 'h', type: 'door-n' },    // front door
        { x: 8, z: 28, o: 'h', type: 'door-n' },      // bedroom 1
        { x: 16, z: 12, o: 'v', type: 'door-s' },     // bedroom 2
        { x: 8, z: 56, o: 'h', type: 'door-n' },      // living room
        { x: 24, z: 56, o: 'h', type: 'door-n' },     // kitchen from hall
        { x: 28, z: 62, o: 'v', type: 'door-s' },     // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },     // bedroom 1
        { x: 28, z: 0, o: 'h', type: 'window-l' },    // bedroom 2
        { x: 0, z: 38, o: 'v', type: 'window-l' },    // living
        { x: 40, z: 38, o: 'v', type: 'window-l' },   // kitchen
        { x: 0, z: 50, o: 'v', type: 'window-s' },    // living side
      ],
      furniture: [
        // Bedroom 1 (top-left)
        { type: 'bed-double', x: 2, z: 4, rot: 0 },
        { type: 'nightstand', x: 8, z: 4, rot: 0 },
        { type: 'wardrobe', x: 2, z: 16, rot: 0 },
        // Bedroom 2 (top-right)
        { type: 'bed-single', x: 18, z: 4, rot: 0 },
        { type: 'desk', x: 30, z: 4, rot: 0 },
        { type: 'wardrobe', x: 18, z: 16, rot: 0 },
        { type: 'bookshelf', x: 34, z: 4, rot: 90 },
        // Living room (bottom-left)
        { type: 'sofa', x: 2, z: 40, rot: 0 },
        { type: 'coffee-table', x: 4, z: 36, rot: 0 },
        { type: 'tv', x: 4, z: 32, rot: 0 },
        { type: 'armchair', x: 10, z: 38, rot: 270 },
        { type: 'bookshelf', x: 2, z: 30, rot: 0 },
        // Kitchen (bottom-right area)
        { type: 'counter', x: 36, z: 30, rot: 90 },
        { type: 'stove', x: 36, z: 34, rot: 90 },
        { type: 'sink', x: 36, z: 38, rot: 90 },
        { type: 'fridge', x: 37, z: 42, rot: 0 },
        { type: 'dining-table', x: 22, z: 40, rot: 0 },
        { type: 'chair', x: 22, z: 38, rot: 0 },
        { type: 'chair', x: 26, z: 38, rot: 0 },
        { type: 'chair', x: 22, z: 44, rot: 180 },
        { type: 'chair', x: 26, z: 44, rot: 180 },
        // Bathroom (bottom-right corner)
        { type: 'toilet', x: 30, z: 58, rot: 0 },
        { type: 'bathtub', x: 34, z: 58, rot: 0 },
        { type: 'basin', x: 30, z: 66, rot: 0 },
      ],
    },
  },
},

// ─── 6. Two-Story House (130 sqm, ~10×13 m = 40×52 per floor)
{
  name: 'Two-Story House',
  desc: '130 sqm, floor 0: living, kitchen, WC; floor 1: master, 2 kids, bath',
  floors: {
    0: {
      walls: [
        // Outer walls (40×52)
        [0, 0, 40, 0],
        [0, 0, 0, 52],
        [40, 0, 40, 52],
        [0, 52, 40, 52],
        // Living / kitchen divider (z=28)
        [0, 28, 16, 28],
        // Hallway wall (x=16 from z=28 to z=52)
        [16, 28, 16, 52],
        // WC (bottom-right, 2×2 m = 8×8)
        [32, 44, 32, 52],
        [32, 44, 40, 44],
        // Kitchen right partition
        [16, 28, 40, 28],
      ],
      doors: [
        { x: 20, z: 52, o: 'h', type: 'door-n' },     // front door
        { x: 8, z: 28, o: 'h', type: 'door-n' },       // living to hall
        { x: 24, z: 28, o: 'h', type: 'door-n' },      // kitchen to hall
        { x: 32, z: 48, o: 'v', type: 'door-s' },      // WC
      ],
      windows: [
        { x: 8, z: 0, o: 'h', type: 'window-l' },      // living
        { x: 24, z: 0, o: 'h', type: 'window-l' },     // living
        { x: 0, z: 10, o: 'v', type: 'window-l' },     // living side
        { x: 40, z: 10, o: 'v', type: 'window-l' },    // kitchen side
      ],
      furniture: [
        // Living room (0..40 x 0..28)
        { type: 'sofa', x: 8, z: 16, rot: 0 },
        { type: 'coffee-table', x: 10, z: 12, rot: 0 },
        { type: 'tv', x: 10, z: 4, rot: 0 },
        { type: 'armchair', x: 20, z: 14, rot: 270 },
        { type: 'bookshelf', x: 2, z: 2, rot: 0 },
        // Kitchen (16..40 x 28..44)
        { type: 'counter', x: 36, z: 30, rot: 90 },
        { type: 'stove', x: 36, z: 34, rot: 90 },
        { type: 'sink', x: 36, z: 38, rot: 90 },
        { type: 'fridge', x: 37, z: 28, rot: 0 },
        { type: 'dining-table', x: 22, z: 34, rot: 0 },
        { type: 'chair', x: 22, z: 32, rot: 0 },
        { type: 'chair', x: 26, z: 32, rot: 0 },
        { type: 'chair', x: 22, z: 38, rot: 180 },
        { type: 'chair', x: 26, z: 38, rot: 180 },
        // Stairs (hallway, center)
        { type: 'stairs-straight', x: 6, z: 36, rot: 0 },
        // WC
        { type: 'toilet', x: 34, z: 46, rot: 0 },
        { type: 'basin', x: 38, z: 46, rot: 0 },
      ],
    },
    1: {
      walls: [
        // Outer walls (same footprint)
        [0, 0, 40, 0],
        [0, 0, 0, 52],
        [40, 0, 40, 52],
        [0, 52, 40, 52],
        // Central hallway (x=16, z=20..52)
        [16, 20, 16, 52],
        // Master bedroom (top-left, 0..16 x 0..24)
        [0, 24, 16, 24],
        // Kids room 1 (top-right, 16..40 x 0..20)
        [16, 0, 16, 20],
        [16, 20, 40, 20],
        // Kids room 2 (bottom-right, 16..40 x 20..40)
        [16, 40, 40, 40],
        // Bathroom (bottom-left, 0..16 x 40..52)
        [0, 40, 16, 40],
      ],
      doors: [
        { x: 8, z: 24, o: 'h', type: 'door-n' },       // master
        { x: 16, z: 8, o: 'v', type: 'door-s' },        // kids 1
        { x: 16, z: 28, o: 'v', type: 'door-s' },       // kids 2
        { x: 8, z: 40, o: 'h', type: 'door-n' },        // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },       // master
        { x: 28, z: 0, o: 'h', type: 'window-l' },      // kids 1
        { x: 40, z: 30, o: 'v', type: 'window-l' },     // kids 2
        { x: 0, z: 46, o: 'v', type: 'window-s' },      // bathroom
      ],
      furniture: [
        // Master bedroom
        { type: 'bed-double', x: 2, z: 4, rot: 0 },
        { type: 'nightstand', x: 8, z: 4, rot: 0 },
        { type: 'nightstand', x: 2, z: 12, rot: 0 },
        { type: 'wardrobe', x: 2, z: 16, rot: 0 },
        // Kids room 1
        { type: 'bed-single', x: 18, z: 2, rot: 0 },
        { type: 'desk', x: 30, z: 2, rot: 0 },
        { type: 'wardrobe', x: 34, z: 2, rot: 90 },
        // Kids room 2
        { type: 'bed-single', x: 18, z: 22, rot: 0 },
        { type: 'desk', x: 30, z: 22, rot: 0 },
        { type: 'wardrobe', x: 34, z: 22, rot: 90 },
        { type: 'bookshelf', x: 18, z: 34, rot: 0 },
        // Bathroom
        { type: 'bathtub', x: 2, z: 42, rot: 0 },
        { type: 'toilet', x: 10, z: 42, rot: 0 },
        { type: 'basin', x: 10, z: 48, rot: 0 },
        { type: 'shower', x: 2, z: 49, rot: 0 },
        // Stairs landing
        { type: 'stairs-straight', x: 6, z: 30, rot: 180 },
      ],
    },
  },
},

// ─── 7. Split-Level Home (110 sqm, ~10×14 m = 40×56) ─────
{
  name: 'Split-Level Home',
  desc: '110 sqm, floor 0: entry/kitchen, floor 0.5: sunken living, floor 1: bedrooms',
  floors: {
    0: {
      walls: [
        // Outer walls (40×56)
        [0, 0, 40, 0],
        [0, 0, 0, 56],
        [40, 0, 40, 56],
        [0, 56, 40, 56],
        // Kitchen zone (top, 0..40 x 0..24)
        [0, 24, 40, 24],
      ],
      doors: [
        { x: 16, z: 56, o: 'h', type: 'door-n' },    // main entry
        { x: 18, z: 24, o: 'h', type: 'door-n' },    // kitchen to stairwell
      ],
      windows: [
        { x: 8, z: 0, o: 'h', type: 'window-l' },
        { x: 28, z: 0, o: 'h', type: 'window-l' },
        { x: 0, z: 8, o: 'v', type: 'window-l' },
      ],
      furniture: [
        // Kitchen
        { type: 'counter', x: 36, z: 2, rot: 90 },
        { type: 'stove', x: 36, z: 6, rot: 90 },
        { type: 'sink', x: 36, z: 10, rot: 90 },
        { type: 'fridge', x: 37, z: 14, rot: 0 },
        { type: 'dining-table', x: 12, z: 8, rot: 0 },
        { type: 'chair', x: 12, z: 6, rot: 0 },
        { type: 'chair', x: 16, z: 6, rot: 0 },
        { type: 'chair', x: 12, z: 12, rot: 180 },
        { type: 'chair', x: 16, z: 12, rot: 180 },
        // Entry hall / stairs down to living
        { type: 'stairs-straight', x: 16, z: 32, rot: 0 },
        // Stairs up to bedrooms
        { type: 'stairs-straight', x: 28, z: 32, rot: 180 },
      ],
    },
    0.5: {
      walls: [
        // Sunken living (same footprint width, z=24..56)
        [0, 24, 40, 24],
        [0, 24, 0, 56],
        [40, 24, 40, 56],
        [0, 56, 40, 56],
      ],
      doors: [],
      windows: [
        { x: 0, z: 34, o: 'v', type: 'window-l' },
        { x: 40, z: 34, o: 'v', type: 'window-l' },
        { x: 10, z: 56, o: 'h', type: 'window-l' },
        { x: 28, z: 56, o: 'h', type: 'window-l' },
      ],
      furniture: [
        { type: 'sofa', x: 4, z: 34, rot: 0 },
        { type: 'sofa', x: 4, z: 46, rot: 0 },
        { type: 'coffee-table', x: 14, z: 38, rot: 0 },
        { type: 'tv', x: 14, z: 30, rot: 0 },
        { type: 'armchair', x: 28, z: 36, rot: 270 },
        { type: 'bookshelf', x: 24, z: 48, rot: 0 },
      ],
    },
    1: {
      walls: [
        // Upper floor (bedrooms, same footprint)
        [0, 0, 40, 0],
        [0, 0, 0, 24],
        [40, 0, 40, 24],
        [0, 24, 40, 24],
        // Two bedrooms + hallway
        [16, 0, 16, 24],      // center divider
        // Bathroom (right rear, 28..40 x 12..24)
        [28, 12, 28, 24],
        [28, 12, 40, 12],
      ],
      doors: [
        { x: 6, z: 24, o: 'h', type: 'door-n' },     // bedroom 1
        { x: 16, z: 6, o: 'v', type: 'door-s' },     // bedroom 2
        { x: 28, z: 18, o: 'v', type: 'door-s' },    // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },
        { x: 24, z: 0, o: 'h', type: 'window-l' },
      ],
      furniture: [
        // Bedroom 1 (left)
        { type: 'bed-double', x: 2, z: 2, rot: 0 },
        { type: 'nightstand', x: 8, z: 2, rot: 0 },
        { type: 'wardrobe', x: 2, z: 14, rot: 0 },
        // Bedroom 2 (right-top)
        { type: 'bed-single', x: 18, z: 2, rot: 0 },
        { type: 'desk', x: 24, z: 2, rot: 0 },
        // Bathroom (right-bottom)
        { type: 'shower', x: 30, z: 14, rot: 0 },
        { type: 'toilet', x: 34, z: 14, rot: 0 },
        { type: 'basin', x: 37, z: 14, rot: 0 },
      ],
    },
  },
},

// ─── 8. Apartment with Basement (95 sqm, ~10×12 m = 40×48)
{
  name: 'Apartment with Basement',
  desc: '95 sqm, basement: storage/laundry; ground: living, bedroom, kitchen, bath',
  floors: {
    '-1': {
      walls: [
        // Basement (40×48)
        [0, 0, 40, 0],
        [0, 0, 0, 48],
        [40, 0, 40, 48],
        [0, 48, 40, 48],
        // Storage divider (x=20)
        [20, 0, 20, 48],
      ],
      doors: [
        { x: 20, z: 20, o: 'v', type: 'door-s' },    // between storage rooms
      ],
      windows: [
        { x: 8, z: 0, o: 'h', type: 'window-s' },    // small basement window
        { x: 32, z: 0, o: 'h', type: 'window-s' },
      ],
      furniture: [
        // Laundry room (left)
        { type: 'counter', x: 2, z: 4, rot: 0 },     // washer/dryer area
        { type: 'sink', x: 2, z: 12, rot: 0 },
        { type: 'counter', x: 2, z: 20, rot: 0 },    // folding area
        // Storage room (right)
        { type: 'bookshelf', x: 22, z: 2, rot: 0 },  // shelving
        { type: 'bookshelf', x: 26, z: 2, rot: 0 },
        { type: 'bookshelf', x: 30, z: 2, rot: 0 },
        // Stairs up
        { type: 'stairs-straight', x: 8, z: 36, rot: 180 },
      ],
    },
    0: {
      walls: [
        // Ground floor (40×48)
        [0, 0, 40, 0],
        [0, 0, 0, 48],
        [40, 0, 40, 48],
        [0, 48, 40, 48],
        // Hallway (x=16, z=24..48)
        [16, 24, 16, 48],
        // Bedroom (top-left 0..16 x 0..24)
        [0, 24, 16, 24],
        // Living/kitchen zone (top-right 16..40 x 0..24)
        [16, 0, 16, 24],
        // Kitchen divider (bottom-right, z=24..48)
        [16, 24, 40, 24],
        // Bathroom (bottom-left 0..16 x 36..48)
        [0, 36, 16, 36],
      ],
      doors: [
        { x: 20, z: 48, o: 'h', type: 'door-n' },    // main entry
        { x: 8, z: 24, o: 'h', type: 'door-n' },      // bedroom
        { x: 24, z: 24, o: 'h', type: 'door-n' },     // kitchen
        { x: 8, z: 36, o: 'h', type: 'door-n' },      // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },     // bedroom
        { x: 28, z: 0, o: 'h', type: 'window-l' },    // living
        { x: 0, z: 10, o: 'v', type: 'window-l' },    // bedroom side
        { x: 40, z: 10, o: 'v', type: 'window-l' },   // living side
      ],
      furniture: [
        // Bedroom (top-left)
        { type: 'bed-double', x: 2, z: 2, rot: 0 },
        { type: 'nightstand', x: 8, z: 2, rot: 0 },
        { type: 'wardrobe', x: 2, z: 14, rot: 0 },
        // Living area (top-right)
        { type: 'sofa', x: 18, z: 12, rot: 0 },
        { type: 'coffee-table', x: 20, z: 8, rot: 0 },
        { type: 'tv', x: 20, z: 4, rot: 0 },
        // Kitchen (bottom-right)
        { type: 'counter', x: 36, z: 26, rot: 90 },
        { type: 'stove', x: 36, z: 30, rot: 90 },
        { type: 'sink', x: 36, z: 34, rot: 90 },
        { type: 'fridge', x: 37, z: 38, rot: 0 },
        { type: 'dining-table', x: 22, z: 34, rot: 0 },
        { type: 'chair', x: 22, z: 32, rot: 0 },
        { type: 'chair', x: 26, z: 32, rot: 0 },
        { type: 'chair', x: 22, z: 38, rot: 180 },
        // Bathroom (bottom-left)
        { type: 'bathtub', x: 2, z: 38, rot: 0 },
        { type: 'toilet', x: 10, z: 38, rot: 0 },
        { type: 'basin', x: 10, z: 44, rot: 0 },
        // Stairs to basement
        { type: 'stairs-straight', x: 6, z: 28, rot: 0 },
      ],
    },
  },
},

// ─── 9. Open-Plan Penthouse (120 sqm, ~12×20 m = 48×80) ──
{
  name: 'Open-Plan Penthouse',
  desc: '120 sqm, huge living/dining, kitchen island, master suite, guest bath',
  floors: {
    0: {
      walls: [
        // Outer walls (48×80)
        [0, 0, 48, 0],
        [0, 0, 0, 80],
        [48, 0, 48, 80],
        [0, 80, 48, 80],
        // Master suite (right side, 28..48 x 48..80)
        [28, 48, 48, 48],   // master top wall
        [28, 48, 28, 80],   // master left wall
        // En-suite bathroom inside master (36..48 x 64..80)
        [36, 64, 36, 80],   // en-suite left
        [36, 64, 48, 64],   // en-suite top
        // Guest bathroom (left, 0..14 x 60..80)
        [14, 60, 14, 80],   // guest bath right
        [0, 60, 14, 60],    // guest bath top
      ],
      doors: [
        { x: 20, z: 80, o: 'h', type: 'door-n' },     // main entry
        { x: 34, z: 48, o: 'h', type: 'door-n' },      // master suite
        { x: 36, z: 70, o: 'v', type: 'door-s' },      // en-suite
        { x: 6, z: 60, o: 'h', type: 'door-n' },       // guest bath
      ],
      windows: [
        { x: 8, z: 0, o: 'h', type: 'window-l' },     // panoramic
        { x: 22, z: 0, o: 'h', type: 'window-l' },
        { x: 36, z: 0, o: 'h', type: 'window-l' },
        { x: 0, z: 16, o: 'v', type: 'window-l' },    // side glass
        { x: 48, z: 16, o: 'v', type: 'window-l' },
        { x: 0, z: 40, o: 'v', type: 'window-l' },
        { x: 48, z: 56, o: 'v', type: 'window-l' },   // master
      ],
      furniture: [
        // Living area (open, top-left)
        { type: 'sofa', x: 4, z: 14, rot: 0 },
        { type: 'sofa', x: 16, z: 20, rot: 270 },
        { type: 'coffee-table', x: 10, z: 10, rot: 0 },
        { type: 'tv', x: 10, z: 4, rot: 0 },
        { type: 'armchair', x: 22, z: 10, rot: 270 },
        { type: 'bookshelf', x: 2, z: 2, rot: 0 },
        { type: 'bookshelf', x: 6, z: 2, rot: 0 },
        // Kitchen island (center-right)
        { type: 'counter', x: 30, z: 10, rot: 0 },
        { type: 'counter', x: 34, z: 10, rot: 0 },
        { type: 'stove', x: 38, z: 10, rot: 0 },
        { type: 'sink', x: 30, z: 12, rot: 0 },
        { type: 'fridge', x: 44, z: 4, rot: 0 },
        // Dining area
        { type: 'dining-table', x: 16, z: 32, rot: 0 },
        { type: 'chair', x: 14, z: 32, rot: 270 },
        { type: 'chair', x: 16, z: 30, rot: 0 },
        { type: 'chair', x: 20, z: 30, rot: 0 },
        { type: 'chair', x: 16, z: 36, rot: 180 },
        { type: 'chair', x: 20, z: 36, rot: 180 },
        { type: 'chair', x: 22, z: 32, rot: 90 },
        // Master bedroom (right, 28..48 x 48..64)
        { type: 'bed-double', x: 30, z: 50, rot: 0 },
        { type: 'nightstand', x: 36, z: 50, rot: 0 },
        { type: 'nightstand', x: 30, z: 58, rot: 0 },
        { type: 'wardrobe', x: 42, z: 50, rot: 90 },
        // En-suite (36..48 x 64..80)
        { type: 'shower', x: 38, z: 66, rot: 0 },
        { type: 'bathtub', x: 42, z: 66, rot: 0 },
        { type: 'toilet', x: 38, z: 74, rot: 0 },
        { type: 'basin', x: 42, z: 74, rot: 0 },
        // Guest bathroom (0..14 x 60..80)
        { type: 'toilet', x: 2, z: 62, rot: 0 },
        { type: 'basin', x: 6, z: 62, rot: 0 },
        { type: 'shower', x: 10, z: 62, rot: 0 },
      ],
    },
  },
},

// ─── 10. Tiny House (30 sqm, ~6×10 m = 24×40) ────────────
{
  name: 'Tiny House',
  desc: '30 sqm compact, entry, kitchen-living combo, bathroom, lofted sleeping',
  floors: {
    0: {
      walls: [
        // Outer walls (24×40)
        [0, 0, 24, 0],
        [0, 0, 0, 40],
        [24, 0, 24, 40],
        [0, 40, 24, 40],
        // Bathroom (bottom-right, 2×2.5 m = 8×10)
        [16, 30, 16, 40],   // bathroom left
        [16, 30, 24, 30],   // bathroom top
      ],
      doors: [
        { x: 4, z: 40, o: 'h', type: 'door-n' },      // main entry
        { x: 16, z: 34, o: 'v', type: 'door-s' },      // bathroom
      ],
      windows: [
        { x: 4, z: 0, o: 'h', type: 'window-l' },     // front window
        { x: 16, z: 0, o: 'h', type: 'window-s' },
        { x: 0, z: 16, o: 'v', type: 'window-s' },    // side window
        { x: 24, z: 16, o: 'v', type: 'window-s' },
      ],
      furniture: [
        // Kitchen (along right wall, top area)
        { type: 'counter', x: 20, z: 2, rot: 90 },
        { type: 'stove', x: 20, z: 6, rot: 90 },
        { type: 'sink', x: 20, z: 10, rot: 90 },
        { type: 'fridge', x: 21, z: 14, rot: 0 },
        // Living area
        { type: 'sofa', x: 2, z: 14, rot: 0 },
        { type: 'coffee-table', x: 4, z: 10, rot: 0 },
        { type: 'tv', x: 4, z: 4, rot: 0 },
        // Small dining
        { type: 'dining-table', x: 4, z: 22, rot: 0 },
        { type: 'chair', x: 4, z: 20, rot: 0 },
        { type: 'chair', x: 8, z: 20, rot: 0 },
        // Stairs to loft
        { type: 'stairs-straight', x: 2, z: 30, rot: 0 },
        // Bathroom
        { type: 'toilet', x: 18, z: 32, rot: 0 },
        { type: 'shower', x: 21, z: 32, rot: 0 },
        { type: 'basin', x: 18, z: 37, rot: 0 },
      ],
    },
    0.5: {
      walls: [
        // Loft sleeping area (above bathroom + partial, 0..24 x 24..40)
        [0, 24, 24, 24],    // railing / front edge
        [0, 24, 0, 40],     // left wall (outer)
        [24, 24, 24, 40],   // right wall (outer)
        [0, 40, 24, 40],    // back wall (outer)
      ],
      doors: [],
      windows: [
        { x: 8, z: 40, o: 'h', type: 'window-s' },    // loft window
      ],
      furniture: [
        { type: 'bed-double', x: 4, z: 28, rot: 0 },
        { type: 'nightstand', x: 10, z: 28, rot: 0 },
        { type: 'wardrobe', x: 16, z: 28, rot: 0 },
      ],
    },
  },
},

];
