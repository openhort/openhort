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
//  Furniture sizes (width × depth in tiles, 1 tile = 25cm):
//    sofa 4×8, armchair 3×3, tv 5×1, bookshelf 4×1
//    coffee-table 3×5, counter 3×2, stove 3×3, fridge 3×3
//    sink 3×2, dining-table 4×6, chair 2×2, bed-single 4×8
//    bed-double 7×8, wardrobe 5×2, desk 4×3, nightstand 2×2
//    toilet 2×3, bathtub 4×7, shower 4×4, basin 2×2
//    stairs-straight 4×10
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
        // Bathroom (top-right, 28..40 x 0..10)
        // toilet 2×3 at (29,1) occupies 29..31 x 1..4
        { type: 'toilet', x: 29, z: 1, rot: 0 },
        // shower 4×4 at (35,1) occupies 35..39 x 1..5
        { type: 'shower', x: 35, z: 1, rot: 0 },
        // basin 2×2 at (33,1) occupies 33..35 x 1..3  -- but 35 overlaps shower
        // basin 2×2 at (29,5) occupies 29..31 x 5..7
        { type: 'basin', x: 29, z: 5, rot: 0 },

        // Kitchen (right wall, z=12 downward)
        // counter rot=90: 2×3, at (37,12) occupies 37..39 x 12..15
        { type: 'counter', x: 37, z: 12, rot: 90 },
        // stove rot=90: 3×3, at (37,15) occupies 37..40... too wide
        // stove 3×3 at rot=0: (37,15) occupies 37..40 x 15..18 — 40 is wall
        // stove 3×3 at rot=0: (36,15) occupies 36..39 x 15..18
        { type: 'stove', x: 37, z: 15, rot: 90 },
        // fridge 3×3 at (37,18) occupies 37..40 — on wall
        // fridge 3×3 at (36,18) occupies 36..39 x 18..21
        { type: 'fridge', x: 36, z: 18, rot: 0 },
        // sink rot=90: 2×3, at (37,21) occupies 37..39 x 21..24
        { type: 'sink', x: 37, z: 21, rot: 90 },

        // Bed (top-left against top wall)
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },

        // wardrobe 5×2 at (1,11) occupies 1..6 x 11..13
        { type: 'wardrobe', x: 1, z: 11, rot: 0 },

        // Living area
        // sofa 4×8 at (1,28) occupies 1..5 x 28..36
        { type: 'sofa', x: 1, z: 28, rot: 0 },
        // tv 5×1 at (1,22) occupies 1..6 x 22..23
        { type: 'tv', x: 1, z: 22, rot: 0 },
        // coffee-table 3×5 at (1,24) occupies 1..4 x 24..29 — overlaps sofa at z=28
        // coffee-table 3×5 at (1,23) occupies 1..4 x 23..28 — ok
        { type: 'coffee-table', x: 1, z: 23, rot: 0 },

        // Dining area (center-right)
        // dining-table 4×6 at (20,30) occupies 20..24 x 30..36
        { type: 'dining-table', x: 20, z: 30, rot: 0 },
        // chair above: x=21, z=27, rot=0 — 21..23 x 27..29
        { type: 'chair', x: 21, z: 27, rot: 0 },
        // chair below: x=21, z=37, rot=180 — 21..23 x 37..39
        { type: 'chair', x: 21, z: 37, rot: 180 },
        // chair right: x=25, z=32, rot=90 — 25..27 x 32..34
        { type: 'chair', x: 25, z: 32, rot: 90 },
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
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // wardrobe 5×2 at (1,11) occupies 1..6 x 11..13
        { type: 'wardrobe', x: 1, z: 11, rot: 0 },
        // desk 4×3 at (8,11) occupies 8..12 x 11..14
        { type: 'desk', x: 8, z: 11, rot: 0 },

        // Living room (top-right, 14..36 x 0..24)
        // bookshelf 4×1 at (15,1) occupies 15..19 x 1..2
        { type: 'bookshelf', x: 15, z: 1, rot: 0 },
        // tv 5×1 at (15,4) occupies 15..20 x 4..5
        { type: 'tv', x: 15, z: 4, rot: 0 },
        // coffee-table 3×5 at (15,7) occupies 15..18 x 7..12
        { type: 'coffee-table', x: 15, z: 7, rot: 0 },
        // sofa 4×8 at (15,14) occupies 15..19 x 14..22
        { type: 'sofa', x: 15, z: 14, rot: 0 },

        // Kitchen (right side, 14..36 x 24..36) — appliances along top wall
        // counter 3×2 at (15,25) occupies 15..18 x 25..27
        { type: 'counter', x: 15, z: 25, rot: 0 },
        // stove 3×3 at (19,25) occupies 19..22 x 25..28
        { type: 'stove', x: 19, z: 25, rot: 0 },
        // sink 3×2 at (23,25) occupies 23..26 x 25..27
        { type: 'sink', x: 23, z: 25, rot: 0 },
        // fridge 3×3 at (27,25) occupies 27..30 x 25..28
        { type: 'fridge', x: 27, z: 25, rot: 0 },

        // Dining table in kitchen area
        // dining-table 4×6 at (20,32) occupies 20..24 x 32..38
        { type: 'dining-table', x: 20, z: 32, rot: 0 },
        // chair above: x=21, z=29, rot=0 — 21..23 x 29..31
        { type: 'chair', x: 21, z: 29, rot: 0 },
        // chair below: x=21, z=39, rot=180 — 21..23 x 39..41
        { type: 'chair', x: 21, z: 39, rot: 180 },
        // chair left: x=17, z=34, rot=270 — 17..19 x 34..36
        { type: 'chair', x: 17, z: 34, rot: 270 },
        // chair right: x=25, z=34, rot=90 — 25..27 x 34..36
        { type: 'chair', x: 25, z: 34, rot: 90 },

        // Bathroom (bottom-right, 26..36 x 36..48)
        // toilet 2×3 at (27,37) occupies 27..29 x 37..40
        { type: 'toilet', x: 27, z: 37, rot: 0 },
        // shower 4×4 at (31,37) occupies 31..35 x 37..41
        { type: 'shower', x: 31, z: 37, rot: 0 },
        // basin 2×2 at (27,42) occupies 27..29 x 42..44
        { type: 'basin', x: 27, z: 42, rot: 0 },
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
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // wardrobe 5×2 at (1,12) occupies 1..6 x 12..14
        { type: 'wardrobe', x: 1, z: 12, rot: 0 },

        // Bedroom 2 (top-right 16..40 x 0..24)
        // bed-single 4×8 at (17,1) occupies 17..21 x 1..9
        { type: 'bed-single', x: 17, z: 1, rot: 0 },
        // desk 4×3 at (23,1) occupies 23..27 x 1..4
        { type: 'desk', x: 23, z: 1, rot: 0 },
        // wardrobe 5×2 at (17,12) occupies 17..22 x 12..14
        { type: 'wardrobe', x: 17, z: 12, rot: 0 },
        // bookshelf rot=90: 1×4 at (39,1) occupies 39..40... on wall
        // bookshelf 4×1 at (35,1) occupies 35..39 x 1..2
        { type: 'bookshelf', x: 35, z: 1, rot: 0 },

        // Kitchen (bottom-left 0..16 x 40..56)
        // counter 3×2 at (1,41) occupies 1..4 x 41..43
        { type: 'counter', x: 1, z: 41, rot: 0 },
        // stove 3×3 at (5,41) occupies 5..8 x 41..44
        { type: 'stove', x: 5, z: 41, rot: 0 },
        // sink 3×2 at (9,41) occupies 9..12 x 41..43
        { type: 'sink', x: 9, z: 41, rot: 0 },
        // fridge 3×3 at (12,41) occupies 12..15 x 41..44
        { type: 'fridge', x: 12, z: 41, rot: 0 },

        // Living / Dining (right side, 16..40 x 24..44)
        // tv 5×1 at (18,26) occupies 18..23 x 26..27
        { type: 'tv', x: 18, z: 26, rot: 0 },
        // coffee-table 3×5 at (18,29) occupies 18..21 x 29..34
        { type: 'coffee-table', x: 18, z: 29, rot: 0 },
        // sofa 4×8 at (17,35) occupies 17..21 x 35..43
        { type: 'sofa', x: 17, z: 35, rot: 0 },

        // dining-table 4×6 at (26,30) occupies 26..30 x 30..36
        { type: 'dining-table', x: 26, z: 30, rot: 0 },
        // chair above: x=27, z=27, rot=0 — 27..29 x 27..29
        { type: 'chair', x: 27, z: 27, rot: 0 },
        // chair below: x=27, z=37, rot=180 — 27..29 x 37..39
        { type: 'chair', x: 27, z: 37, rot: 180 },
        // chair left: x=23, z=32, rot=270 — 23..25 x 32..34
        { type: 'chair', x: 23, z: 32, rot: 270 },
        // chair right: x=31, z: 32, rot=90 — 31..33 x 32..34
        { type: 'chair', x: 31, z: 32, rot: 90 },

        // Bathroom (bottom-right 28..40 x 44..56)
        // toilet 2×3 at (29,45) occupies 29..31 x 45..48
        { type: 'toilet', x: 29, z: 45, rot: 0 },
        // shower 4×4 at (33,45) occupies 33..37 x 45..49
        { type: 'shower', x: 33, z: 45, rot: 0 },
        // bathtub 4×7 at (29,49) occupies 29..33 x 49..56 — 56 is on wall, OK flush
        { type: 'bathtub', x: 29, z: 49, rot: 0 },
        // basin 2×2 at (35,50) occupies 35..37 x 50..52
        { type: 'basin', x: 35, z: 50, rot: 0 },
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
        // Open living area (top-left)
        // bookshelf 4×1 at (1,1) occupies 1..5 x 1..2
        { type: 'bookshelf', x: 1, z: 1, rot: 0 },
        // tv 5×1 at (1,5) occupies 1..6 x 5..6
        { type: 'tv', x: 1, z: 5, rot: 0 },
        // coffee-table 3×5 at (1,9) occupies 1..4 x 9..14
        { type: 'coffee-table', x: 1, z: 9, rot: 0 },
        // sofa 4×8 at (1,16) occupies 1..5 x 16..24
        { type: 'sofa', x: 1, z: 16, rot: 0 },
        // armchair 3×3 at (8,16) occupies 8..11 x 16..19
        { type: 'armchair', x: 8, z: 16, rot: 0 },

        // Kitchen area (right side, flush to right wall)
        // counter rot=90: 2×3 at (37,1) occupies 37..39 x 1..4
        { type: 'counter', x: 37, z: 1, rot: 90 },
        // stove rot=90: 3×3 at (37,4) occupies 37..40... too wide
        // stove 3×3 at (36,4) occupies 36..39 x 4..7
        { type: 'stove', x: 37, z: 4, rot: 90 },
        // sink rot=90: 2×3 at (37,7) occupies 37..39 x 7..10
        { type: 'sink', x: 37, z: 7, rot: 90 },
        // fridge 3×3 at (36,10) occupies 36..39 x 10..13
        { type: 'fridge', x: 36, z: 10, rot: 0 },

        // Dining (center)
        // dining-table 4×6 at (18,8) occupies 18..22 x 8..14
        { type: 'dining-table', x: 18, z: 8, rot: 0 },
        // chair above: x=19, z=5, rot=0 — 19..21 x 5..7
        { type: 'chair', x: 19, z: 5, rot: 0 },
        // chair below: x=19, z=15, rot=180 — 19..21 x 15..17
        { type: 'chair', x: 19, z: 15, rot: 180 },
        // chair left: x=15, z=10, rot=270 — 15..17 x 10..12
        { type: 'chair', x: 15, z: 10, rot: 270 },
        // chair right: x=23, z=10, rot=90 — 23..25 x 10..12
        { type: 'chair', x: 23, z: 10, rot: 90 },

        // Stairs to mezzanine
        // stairs-straight 4×10 at (1,36) occupies 1..5 x 36..46
        { type: 'stairs-straight', x: 1, z: 36, rot: 0 },

        // Bathroom (28..40 x 54..64)
        // toilet 2×3 at (29,55) occupies 29..31 x 55..58
        { type: 'toilet', x: 29, z: 55, rot: 0 },
        // shower 4×4 at (35,55) occupies 35..39 x 55..59
        { type: 'shower', x: 35, z: 55, rot: 0 },
        // basin 2×2 at (29,59) occupies 29..31 x 59..61
        { type: 'basin', x: 29, z: 59, rot: 0 },
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
        // bed-double 7×8 at (1,34) occupies 1..8 x 34..42
        { type: 'bed-double', x: 1, z: 34, rot: 0 },
        // nightstand 2×2 at (9,34) occupies 9..11 x 34..36
        { type: 'nightstand', x: 9, z: 34, rot: 0 },
        // nightstand 2×2 at (9,40) occupies 9..11 x 40..42
        { type: 'nightstand', x: 9, z: 40, rot: 0 },
        // wardrobe 5×2 at (13,34) occupies 13..18 x 34..36
        { type: 'wardrobe', x: 13, z: 34, rot: 0 },
        // desk 4×3 at (1,46) occupies 1..5 x 46..49
        { type: 'desk', x: 1, z: 46, rot: 0 },
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
        // Bedroom 1 (top-left, 0..16 x 0..28)
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // wardrobe 5×2 at (1,14) occupies 1..6 x 14..16
        { type: 'wardrobe', x: 1, z: 14, rot: 0 },

        // Bedroom 2 (top-right, 16..40 x 0..28)
        // bed-single 4×8 at (17,1) occupies 17..21 x 1..9
        { type: 'bed-single', x: 17, z: 1, rot: 0 },
        // desk 4×3 at (23,1) occupies 23..27 x 1..4
        { type: 'desk', x: 23, z: 1, rot: 0 },
        // wardrobe 5×2 at (17,12) occupies 17..22 x 12..14
        { type: 'wardrobe', x: 17, z: 12, rot: 0 },
        // bookshelf 4×1 at (35,1) occupies 35..39 x 1..2
        { type: 'bookshelf', x: 35, z: 1, rot: 0 },

        // Living room (bottom-left, 0..16 x 28..56)
        // bookshelf 4×1 at (1,29) occupies 1..5 x 29..30
        { type: 'bookshelf', x: 1, z: 29, rot: 0 },
        // tv 5×1 at (1,32) occupies 1..6 x 32..33
        { type: 'tv', x: 1, z: 32, rot: 0 },
        // coffee-table 3×5 at (1,35) occupies 1..4 x 35..40
        { type: 'coffee-table', x: 1, z: 35, rot: 0 },
        // sofa 4×8 at (1,42) occupies 1..5 x 42..50
        { type: 'sofa', x: 1, z: 42, rot: 0 },
        // armchair 3×3 at (8,42) occupies 8..11 x 42..45
        { type: 'armchair', x: 8, z: 42, rot: 0 },

        // Kitchen (bottom-right, 16..40 x 28..56)
        // counter rot=90: 2×3 at (37,29) occupies 37..39 x 29..32
        { type: 'counter', x: 37, z: 29, rot: 90 },
        // stove rot=90: 3×3 at (37,32) occupies 37..40... stove 3×3 at rot=90 is still 3×3
        // Let's use rot=0 flush right: stove 3×3 at (36,32) occupies 36..39 x 32..35
        { type: 'stove', x: 37, z: 32, rot: 90 },
        // sink rot=90: 2×3 at (37,35) occupies 37..39 x 35..38
        { type: 'sink', x: 37, z: 35, rot: 90 },
        // fridge 3×3 at (36,38) occupies 36..39 x 38..41
        { type: 'fridge', x: 36, z: 38, rot: 0 },

        // dining-table 4×6 at (20,38) occupies 20..24 x 38..44
        { type: 'dining-table', x: 20, z: 38, rot: 0 },
        // chair above: x=21, z=35, rot=0 — 21..23 x 35..37
        { type: 'chair', x: 21, z: 35, rot: 0 },
        // chair below: x=21, z=45, rot=180 — 21..23 x 45..47
        { type: 'chair', x: 21, z: 45, rot: 180 },
        // chair left: x=17, z=40, rot=270 — 17..19 x 40..42
        { type: 'chair', x: 17, z: 40, rot: 270 },
        // chair right: x=25, z=40, rot=90 — 25..27 x 40..42
        { type: 'chair', x: 25, z: 40, rot: 90 },

        // Bathroom (bottom-right corner, 28..40 x 56..72)
        // toilet 2×3 at (29,57) occupies 29..31 x 57..60
        { type: 'toilet', x: 29, z: 57, rot: 0 },
        // bathtub 4×7 at (29,62) occupies 29..33 x 62..69
        { type: 'bathtub', x: 29, z: 62, rot: 0 },
        // basin 2×2 at (35,57) occupies 35..37 x 57..59
        { type: 'basin', x: 35, z: 57, rot: 0 },
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
        // Living room (0..40 x 0..28) — full width but furniture on left side
        // bookshelf 4×1 at (1,1) occupies 1..5 x 1..2
        { type: 'bookshelf', x: 1, z: 1, rot: 0 },
        // tv 5×1 at (1,5) occupies 1..6 x 5..6
        { type: 'tv', x: 8, z: 5, rot: 0 },
        // coffee-table 3×5 at (8,9) occupies 8..11 x 9..14
        { type: 'coffee-table', x: 8, z: 9, rot: 0 },
        // sofa 4×8 at (7,16) occupies 7..11 x 16..24
        { type: 'sofa', x: 7, z: 16, rot: 0 },
        // armchair 3×3 at (14,16) occupies 14..17 x 16..19
        { type: 'armchair', x: 14, z: 16, rot: 0 },

        // Kitchen (16..40 x 28..44)
        // counter rot=90: 2×3 at (37,29) occupies 37..39 x 29..32
        { type: 'counter', x: 37, z: 29, rot: 90 },
        // stove rot=90: 3×3 at (37,32) occupies 37..40... 3×3 square is same at any rot
        { type: 'stove', x: 37, z: 32, rot: 90 },
        // sink rot=90: 2×3 at (37,35) occupies 37..39 x 35..38
        { type: 'sink', x: 37, z: 35, rot: 90 },
        // fridge 3×3 at (36,38) occupies 36..39 x 38..41
        { type: 'fridge', x: 36, z: 38, rot: 0 },

        // dining-table 4×6 at (20,32) occupies 20..24 x 32..38
        { type: 'dining-table', x: 20, z: 32, rot: 0 },
        // chair above: x=21, z=29, rot=0 — 21..23 x 29..31
        { type: 'chair', x: 21, z: 29, rot: 0 },
        // chair below: x=21, z=39, rot=180 — 21..23 x 39..41
        { type: 'chair', x: 21, z: 39, rot: 180 },
        // chair left: x=17, z=34, rot=270 — 17..19 x 34..36
        { type: 'chair', x: 17, z: 34, rot: 270 },
        // chair right: x=25, z=34, rot=90 — 25..27 x 34..36
        { type: 'chair', x: 25, z: 34, rot: 90 },

        // Stairs (hallway, 0..16 x 28..52)
        // stairs-straight 4×10 at (2,34) occupies 2..6 x 34..44
        { type: 'stairs-straight', x: 2, z: 34, rot: 0 },

        // WC (32..40 x 44..52)
        // toilet 2×3 at (33,45) occupies 33..35 x 45..48
        { type: 'toilet', x: 33, z: 45, rot: 0 },
        // basin 2×2 at (37,45) occupies 37..39 x 45..47
        { type: 'basin', x: 37, z: 45, rot: 0 },
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
        // Master bedroom (0..16 x 0..24)
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // nightstand 2×2 at (9,7) occupies 9..11 x 7..9
        { type: 'nightstand', x: 9, z: 7, rot: 0 },
        // wardrobe 5×2 at (1,12) occupies 1..6 x 12..14
        { type: 'wardrobe', x: 1, z: 12, rot: 0 },

        // Kids room 1 (16..40 x 0..20)
        // bed-single 4×8 at (17,1) occupies 17..21 x 1..9
        { type: 'bed-single', x: 17, z: 1, rot: 0 },
        // desk 4×3 at (23,1) occupies 23..27 x 1..4
        { type: 'desk', x: 23, z: 1, rot: 0 },
        // wardrobe 5×2 at (34,1) occupies 34..39 x 1..3
        { type: 'wardrobe', x: 34, z: 1, rot: 0 },

        // Kids room 2 (16..40 x 20..40)
        // bed-single 4×8 at (17,22) occupies 17..21 x 22..30
        { type: 'bed-single', x: 17, z: 22, rot: 0 },
        // desk 4×3 at (23,22) occupies 23..27 x 22..25
        { type: 'desk', x: 23, z: 22, rot: 0 },
        // wardrobe 5×2 at (34,22) occupies 34..39 x 22..24
        { type: 'wardrobe', x: 34, z: 22, rot: 0 },
        // bookshelf 4×1 at (17,33) occupies 17..21 x 33..34
        { type: 'bookshelf', x: 17, z: 33, rot: 0 },

        // Bathroom (0..16 x 40..52)
        // bathtub 4×7 at (1,41) occupies 1..5 x 41..48
        { type: 'bathtub', x: 1, z: 41, rot: 0 },
        // toilet 2×3 at (7,41) occupies 7..9 x 41..44
        { type: 'toilet', x: 7, z: 41, rot: 0 },
        // basin 2×2 at (7,46) occupies 7..9 x 46..48
        { type: 'basin', x: 7, z: 46, rot: 0 },
        // shower 4×4 at (11,41) occupies 11..15 x 41..45
        { type: 'shower', x: 11, z: 41, rot: 0 },

        // Stairs landing
        // stairs-straight 4×10 at (2,30) occupies 2..6 x 30..40
        { type: 'stairs-straight', x: 2, z: 30, rot: 180 },
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
        // Kitchen (0..40 x 0..24)
        // counter rot=90: 2×3 at (37,1) occupies 37..39 x 1..4
        { type: 'counter', x: 37, z: 1, rot: 90 },
        // stove rot=90: 3×3 at (37,4) occupies 37..40... square so same
        { type: 'stove', x: 37, z: 4, rot: 90 },
        // sink rot=90: 2×3 at (37,7) occupies 37..39 x 7..10
        { type: 'sink', x: 37, z: 7, rot: 90 },
        // fridge 3×3 at (36,10) occupies 36..39 x 10..13
        { type: 'fridge', x: 36, z: 10, rot: 0 },

        // dining-table 4×6 at (10,6) occupies 10..14 x 6..12
        { type: 'dining-table', x: 10, z: 6, rot: 0 },
        // chair above: x=11, z=3, rot=0 — 11..13 x 3..5
        { type: 'chair', x: 11, z: 3, rot: 0 },
        // chair below: x=11, z=13, rot=180 — 11..13 x 13..15
        { type: 'chair', x: 11, z: 13, rot: 180 },
        // chair left: x=7, z=8, rot=270 — 7..9 x 8..10
        { type: 'chair', x: 7, z: 8, rot: 270 },
        // chair right: x=15, z=8, rot=90 — 15..17 x 8..10
        { type: 'chair', x: 15, z: 8, rot: 90 },

        // Entry hall / stairs
        // stairs down to living: 4×10 at (8,32) occupies 8..12 x 32..42
        { type: 'stairs-straight', x: 8, z: 32, rot: 0 },
        // stairs up to bedrooms: 4×10 at (24,32) occupies 24..28 x 32..42
        { type: 'stairs-straight', x: 24, z: 32, rot: 180 },
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
        // Two sofas in L arrangement
        // sofa 4×8 at (2,30) occupies 2..6 x 30..38
        { type: 'sofa', x: 2, z: 30, rot: 0 },
        // sofa 4×8 at (2,42) occupies 2..6 x 42..50
        { type: 'sofa', x: 2, z: 42, rot: 0 },
        // coffee-table 3×5 at (8,34) occupies 8..11 x 34..39
        { type: 'coffee-table', x: 8, z: 34, rot: 0 },
        // tv 5×1 at (14,30) occupies 14..19 x 30..31
        { type: 'tv', x: 14, z: 30, rot: 0 },
        // armchair 3×3 at (14,34) occupies 14..17 x 34..37
        { type: 'armchair', x: 14, z: 34, rot: 0 },
        // bookshelf 4×1 at (24,48) occupies 24..28 x 48..49
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
        // Bedroom 1 (left, 0..16 x 0..24)
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // wardrobe 5×2 at (1,12) occupies 1..6 x 12..14
        { type: 'wardrobe', x: 1, z: 12, rot: 0 },

        // Bedroom 2 (right-top, 16..28 x 0..12)
        // bed-single 4×8 at (17,1) occupies 17..21 x 1..9
        { type: 'bed-single', x: 17, z: 1, rot: 0 },
        // desk 4×3 at (23,1) occupies 23..27 x 1..4
        { type: 'desk', x: 23, z: 1, rot: 0 },

        // Bathroom (right-bottom, 28..40 x 12..24)
        // shower 4×4 at (29,13) occupies 29..33 x 13..17
        { type: 'shower', x: 29, z: 13, rot: 0 },
        // toilet 2×3 at (35,13) occupies 35..37 x 13..16
        { type: 'toilet', x: 35, z: 13, rot: 0 },
        // basin 2×2 at (35,18) occupies 35..37 x 18..20
        { type: 'basin', x: 35, z: 18, rot: 0 },
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
        // Laundry room (left, 0..20 x 0..48)
        // counter 3×2 at (1,2) occupies 1..4 x 2..4
        { type: 'counter', x: 1, z: 2, rot: 0 },     // washer/dryer area
        // sink 3×2 at (1,6) occupies 1..4 x 6..8
        { type: 'sink', x: 1, z: 6, rot: 0 },
        // counter 3×2 at (1,10) occupies 1..4 x 10..12
        { type: 'counter', x: 1, z: 10, rot: 0 },    // folding area

        // Storage room (right, 20..40 x 0..48)
        // bookshelf 4×1 at (22,1) occupies 22..26 x 1..2
        { type: 'bookshelf', x: 22, z: 1, rot: 0 },  // shelving
        // bookshelf 4×1 at (28,1) occupies 28..32 x 1..2
        { type: 'bookshelf', x: 28, z: 1, rot: 0 },
        // bookshelf 4×1 at (34,1) occupies 34..38 x 1..2
        { type: 'bookshelf', x: 34, z: 1, rot: 0 },

        // Stairs up: 4×10 at (8,36) occupies 8..12 x 36..46
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
        // Bedroom (top-left, 0..16 x 0..24)
        // bed-double 7×8 at (1,1) occupies 1..8 x 1..9
        { type: 'bed-double', x: 1, z: 1, rot: 0 },
        // nightstand 2×2 at (9,1) occupies 9..11 x 1..3
        { type: 'nightstand', x: 9, z: 1, rot: 0 },
        // wardrobe 5×2 at (1,12) occupies 1..6 x 12..14
        { type: 'wardrobe', x: 1, z: 12, rot: 0 },

        // Living area (top-right, 16..40 x 0..24)
        // tv 5×1 at (17,1) occupies 17..22 x 1..2
        { type: 'tv', x: 17, z: 1, rot: 0 },
        // coffee-table 3×5 at (17,5) occupies 17..20 x 5..10
        { type: 'coffee-table', x: 17, z: 5, rot: 0 },
        // sofa 4×8 at (17,12) occupies 17..21 x 12..20
        { type: 'sofa', x: 17, z: 12, rot: 0 },

        // Kitchen (bottom-right, 16..40 x 24..48)
        // counter rot=90: 2×3 at (37,25) occupies 37..39 x 25..28
        { type: 'counter', x: 37, z: 25, rot: 90 },
        // stove rot=90: 3×3 at (37,28) occupies 37..40...
        { type: 'stove', x: 37, z: 28, rot: 90 },
        // sink rot=90: 2×3 at (37,31) occupies 37..39 x 31..34
        { type: 'sink', x: 37, z: 31, rot: 90 },
        // fridge 3×3 at (36,34) occupies 36..39 x 34..37
        { type: 'fridge', x: 36, z: 34, rot: 0 },

        // dining-table 4×6 at (20,32) occupies 20..24 x 32..38
        { type: 'dining-table', x: 20, z: 32, rot: 0 },
        // chair above: x=21, z=29, rot=0 — 21..23 x 29..31
        { type: 'chair', x: 21, z: 29, rot: 0 },
        // chair below: x=21, z=39, rot=180 — 21..23 x 39..41
        { type: 'chair', x: 21, z: 39, rot: 180 },
        // chair right: x=25, z=34, rot=90 — 25..27 x 34..36
        { type: 'chair', x: 25, z: 34, rot: 90 },

        // Bathroom (bottom-left, 0..16 x 36..48)
        // bathtub 4×7 at (1,37) occupies 1..5 x 37..44
        { type: 'bathtub', x: 1, z: 37, rot: 0 },
        // toilet 2×3 at (7,37) occupies 7..9 x 37..40
        { type: 'toilet', x: 7, z: 37, rot: 0 },
        // basin 2×2 at (7,42) occupies 7..9 x 42..44
        { type: 'basin', x: 7, z: 42, rot: 0 },

        // Stairs to basement: 4×10 at (2,26) occupies 2..6 x 26..36
        { type: 'stairs-straight', x: 2, z: 26, rot: 0 },
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
        // Living area (open, top-left quadrant)
        // bookshelf 4×1 at (1,1) occupies 1..5 x 1..2
        { type: 'bookshelf', x: 1, z: 1, rot: 0 },
        // bookshelf 4×1 at (7,1) occupies 7..11 x 1..2
        { type: 'bookshelf', x: 7, z: 1, rot: 0 },
        // tv 5×1 at (1,5) occupies 1..6 x 5..6
        { type: 'tv', x: 1, z: 5, rot: 0 },
        // coffee-table 3×5 at (1,9) occupies 1..4 x 9..14
        { type: 'coffee-table', x: 1, z: 9, rot: 0 },
        // sofa 4×8 at (1,16) occupies 1..5 x 16..24
        { type: 'sofa', x: 1, z: 16, rot: 0 },
        // sofa rot=270: 8×4 at (8,16) occupies 8..16 x 16..20
        { type: 'sofa', x: 8, z: 16, rot: 270 },
        // armchair 3×3 at (8,9) occupies 8..11 x 9..12
        { type: 'armchair', x: 8, z: 9, rot: 0 },

        // Kitchen island (center-right, along right wall)
        // counter 3×2 at (30,1) occupies 30..33 x 1..3
        { type: 'counter', x: 30, z: 1, rot: 0 },
        // counter 3×2 at (35,1) occupies 35..38 x 1..3
        { type: 'counter', x: 35, z: 1, rot: 0 },
        // stove 3×3 at (30,5) occupies 30..33 x 5..8
        { type: 'stove', x: 30, z: 5, rot: 0 },
        // sink 3×2 at (35,5) occupies 35..38 x 5..7
        { type: 'sink', x: 35, z: 5, rot: 0 },
        // fridge 3×3 at (44,1) occupies 44..47 x 1..4
        { type: 'fridge', x: 44, z: 1, rot: 0 },

        // Dining area (center)
        // dining-table 4×6 at (16,30) occupies 16..20 x 30..36
        { type: 'dining-table', x: 16, z: 30, rot: 0 },
        // chair above: x=17, z=27, rot=0 — 17..19 x 27..29
        { type: 'chair', x: 17, z: 27, rot: 0 },
        // chair below: x=17, z=37, rot=180 — 17..19 x 37..39
        { type: 'chair', x: 17, z: 37, rot: 180 },
        // chair left: x=13, z=32, rot=270 — 13..15 x 32..34
        { type: 'chair', x: 13, z: 32, rot: 270 },
        // chair right: x=21, z=32, rot=90 — 21..23 x 32..34
        { type: 'chair', x: 21, z: 32, rot: 90 },
        // extra chairs
        // chair above 2: x=19, z=27, rot=0 — overlaps? 19..21 x 27..29 vs right chair 21..23 x 32..34 — no overlap
        { type: 'chair', x: 19, z: 27, rot: 0 },
        // chair below 2: x=19, z=37, rot=180 — 19..21 x 37..39
        { type: 'chair', x: 19, z: 37, rot: 180 },

        // Master bedroom (right, 28..48 x 48..64)
        // bed-double 7×8 at (29,50) occupies 29..36 x 50..58
        { type: 'bed-double', x: 29, z: 50, rot: 0 },
        // nightstand 2×2 at (37,50) occupies 37..39 x 50..52
        { type: 'nightstand', x: 37, z: 50, rot: 0 },
        // nightstand 2×2 at (37,56) occupies 37..39 x 56..58
        { type: 'nightstand', x: 37, z: 56, rot: 0 },
        // wardrobe rot=90: 2×5 at (45,50) occupies 45..47 x 50..55
        { type: 'wardrobe', x: 45, z: 50, rot: 90 },

        // En-suite (36..48 x 64..80)
        // shower 4×4 at (37,65) occupies 37..41 x 65..69
        { type: 'shower', x: 37, z: 65, rot: 0 },
        // bathtub 4×7 at (43,65) occupies 43..47 x 65..72
        { type: 'bathtub', x: 43, z: 65, rot: 0 },
        // toilet 2×3 at (37,72) occupies 37..39 x 72..75
        { type: 'toilet', x: 37, z: 72, rot: 0 },
        // basin 2×2 at (37,76) occupies 37..39 x 76..78
        { type: 'basin', x: 37, z: 76, rot: 0 },

        // Guest bathroom (0..14 x 60..80)
        // toilet 2×3 at (1,61) occupies 1..3 x 61..64
        { type: 'toilet', x: 1, z: 61, rot: 0 },
        // basin 2×2 at (5,61) occupies 5..7 x 61..63
        { type: 'basin', x: 5, z: 61, rot: 0 },
        // shower 4×4 at (9,61) occupies 9..13 x 61..65
        { type: 'shower', x: 9, z: 61, rot: 0 },
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
        // counter rot=90: 2×3 at (21,1) occupies 21..23 x 1..4
        { type: 'counter', x: 21, z: 1, rot: 90 },
        // stove rot=90: 3×3 at (21,4) occupies 21..24... 24 is wall
        // stove 3×3 at (20,4) occupies 20..23 x 4..7
        { type: 'stove', x: 21, z: 4, rot: 90 },
        // sink rot=90: 2×3 at (21,7) occupies 21..23 x 7..10
        { type: 'sink', x: 21, z: 7, rot: 90 },
        // fridge 3×3 at (20,10) occupies 20..23 x 10..13
        { type: 'fridge', x: 20, z: 10, rot: 0 },

        // Living area (left side)
        // tv 5×1 at (1,1) occupies 1..6 x 1..2
        { type: 'tv', x: 1, z: 1, rot: 0 },
        // coffee-table 3×5 at (1,4) occupies 1..4 x 4..9
        { type: 'coffee-table', x: 1, z: 4, rot: 0 },
        // sofa 4×8 at (1,11) occupies 1..5 x 11..19
        { type: 'sofa', x: 1, z: 11, rot: 0 },

        // Small dining
        // dining-table 4×6 at (2,22) occupies 2..6 x 22..28
        { type: 'dining-table', x: 2, z: 22, rot: 0 },
        // chair above: x=3, z=19, rot=0 — 3..5 x 19..21
        { type: 'chair', x: 3, z: 19, rot: 0 },
        // chair below: x=3, z=29, rot=180 — 3..5 x 29..31
        // but z=30 is bathroom wall start at x>=16, OK for x=3..5
        { type: 'chair', x: 3, z: 29, rot: 180 },

        // Stairs to loft: 4×10 at (8,30) occupies 8..12 x 30..40
        { type: 'stairs-straight', x: 8, z: 30, rot: 0 },

        // Bathroom (16..24 x 30..40)
        // toilet 2×3 at (17,31) occupies 17..19 x 31..34
        { type: 'toilet', x: 17, z: 31, rot: 0 },
        // shower 4×4 at (17,35) occupies 17..21 x 35..39
        { type: 'shower', x: 17, z: 35, rot: 0 },
        // basin 2×2 at (21,31) occupies 21..23 x 31..33
        { type: 'basin', x: 21, z: 31, rot: 0 },
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
        // bed-double 7×8 at (1,26) occupies 1..8 x 26..34
        { type: 'bed-double', x: 1, z: 26, rot: 0 },
        // nightstand 2×2 at (9,26) occupies 9..11 x 26..28
        { type: 'nightstand', x: 9, z: 26, rot: 0 },
        // wardrobe 5×2 at (14,26) occupies 14..19 x 26..28
        { type: 'wardrobe', x: 14, z: 26, rot: 0 },
      ],
    },
  },
},

];
