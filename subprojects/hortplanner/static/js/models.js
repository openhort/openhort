// ═══════════════════════════════════════════════════════════════
//  HortPlanner — Model Loader
//
//  Reads component visual definitions from models/manifest.json.
//  Generates Three.js meshes from the declarative definitions.
//  When a .glb file exists for a type, loads the glTF model instead.
//
//  Format: see manifest.json ($schema: hortplanner-models-v1)
//  Profiles: rounded-rect (SVG-compatible), cylinder, icosphere, box
//  Materials: PBR (color, metalness, roughness, opacity, emissive)
//  Animations: rotation, translation (keyframed or continuous)
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';

let _manifest = null;
let _manifestPromise = null;

/** Load and cache the manifest. */
export async function loadManifest(basePath = '/static/models') {
  if (_manifest) return _manifest;
  if (!_manifestPromise) {
    _manifestPromise = fetch(`${basePath}/manifest.json`).then(r => r.json());
  }
  _manifest = await _manifestPromise;
  return _manifest;
}

/** Get the manifest synchronously (must call loadManifest first). */
export function getManifest() { return _manifest; }

/** Get display name for a component type. */
export function getDisplayName(type) {
  return _manifest?.components?.[type]?.displayName || type;
}

/** Get material definition for a type. */
export function getMaterialDef(type) {
  return _manifest?.components?.[type]?.material || {};
}

/** Get body definition for a type. */
export function getBodyDef(type) {
  return _manifest?.components?.[type]?.body || {};
}

/** Get ports for a type. */
export function getPorts(type) {
  return _manifest?.components?.[type]?.ports || { in: 1, out: 1 };
}

// ── Rounded rect helpers (SVG-compatible path generation) ───

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

// ── Material factory ────────────────────────────────────────

function makeMaterial(matDef, isTransparent) {
  const props = {
    color: new THREE.Color(matDef.color || '#888888'),
    metalness: matDef.metalness ?? 0.5,
    roughness: matDef.roughness ?? 0.5,
    side: isTransparent ? THREE.FrontSide : THREE.DoubleSide,
    transparent: isTransparent,
    opacity: matDef.opacity ?? 1.0,
    depthWrite: !isTransparent,
  };
  if (isTransparent) {
    props.polygonOffset = true;
    props.polygonOffsetFactor = 1;
    props.polygonOffsetUnits = 1;
  }
  if (matDef.emissive) {
    props.emissive = new THREE.Color(matDef.emissive);
    props.emissiveIntensity = matDef.emissiveIntensity ?? 0.2;
  }
  return new THREE.MeshStandardMaterial(props);
}

// ── Mesh builders per profile type ──────────────────────────

function buildContainer(type, w, d, compDef) {
  const body = compDef.body;
  const profile = compDef.profile;
  const matDef = compDef.material;
  const h = body.wallHeight;
  const t = body.wallThickness;
  const ft = body.floorThickness;
  const r = profile.cornerRadius || 0;
  const isTransparent = (matDef.opacity ?? 1) < 1;

  const mat = makeMaterial(matDef, isTransparent);
  const group = new THREE.Group();

  // floor (rounded rect)
  const floorShape = rrShape(w, d, r);
  const floorGeo = new THREE.ExtrudeGeometry(floorShape, { depth: ft, bevelEnabled: false });
  floorGeo.rotateX(-Math.PI / 2);
  const floor = new THREE.Mesh(floorGeo, mat);
  floor.receiveShadow = true;
  floor.name = 'floor';
  group.add(floor);

  // wall ring
  const wallOuter = rrShape(w, d, r);
  const iw = w - t * 2, id = d - t * 2;
  const ir = Math.max(0.02, r - t);
  wallOuter.holes.push(rrPath(iw, id, ir));
  const wallGeo = new THREE.ExtrudeGeometry(wallOuter, { depth: h, bevelEnabled: false });
  wallGeo.rotateX(-Math.PI / 2);
  wallGeo.translate(0, ft, 0);
  const walls = new THREE.Mesh(wallGeo, mat);
  walls.castShadow = true;
  walls.userData.isWall = true;
  walls.name = 'walls';
  group.add(walls);

  // dark interior
  const inner = new THREE.Mesh(
    new THREE.PlaneGeometry(iw - 0.02, id - 0.02),
    new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.95 })
  );
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = ft + 0.005;
  inner.receiveShadow = true;
  inner.name = 'innerFloor';
  group.add(inner);

  // features
  const features = compDef.features || {};

  if (features.led?.enabled) {
    const led = new THREE.Mesh(
      new THREE.SphereGeometry(features.led.radius, 8, 8),
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(features.led.color),
        emissive: new THREE.Color(features.led.color),
        emissiveIntensity: features.led.emissiveIntensity,
      })
    );
    led.position.set(0, ft + h * features.led.positionYFactor, d / 2 + 0.01);
    led.name = 'led';
    group.add(led);
  }

  if (features.feet?.enabled) {
    const footMat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(features.feet.color), metalness: 0.6, roughness: 0.4,
    });
    const footGeo = new THREE.CylinderGeometry(features.feet.radius, features.feet.radius * 1.15, features.feet.height, 12);
    const inset = features.feet.inset;
    for (const [fx, fz] of [[-w/2+inset, -d/2+inset], [w/2-inset, -d/2+inset], [-w/2+inset, d/2-inset], [w/2-inset, d/2-inset]]) {
      const foot = new THREE.Mesh(footGeo, footMat);
      foot.position.set(fx, -features.feet.height / 2, fz);
      foot.name = 'foot';
      group.add(foot);
    }
    group.position.y = features.feet.height;
  }

  if (features.screen?.enabled) {
    const scr = features.screen;
    const screenD = d * 0.95;
    const hinge = new THREE.Group();
    hinge.position.set(0, h + ft, -d / 2 + 0.05);
    hinge.name = 'screen';

    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(w - 0.1, screenD, scr.thickness),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(matDef.color), metalness: 0.8, roughness: 0.25 })
    );
    shell.position.y = screenD / 2;
    shell.castShadow = true;
    shell.name = 'screenShell';
    hinge.add(shell);

    const display = new THREE.Mesh(
      new THREE.PlaneGeometry(w - 0.4, screenD - 0.25),
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(scr.displayColor),
        emissive: new THREE.Color(scr.displayEmissive),
        emissiveIntensity: scr.displayEmissiveIntensity,
        metalness: 0.1, roughness: 0.9,
      })
    );
    display.position.set(0, screenD / 2, scr.thickness / 2 + 0.002);
    display.name = 'display';
    hinge.add(display);

    hinge.rotation.x = scr.tiltAngle;
    group.add(hinge);
  }

  return group;
}

function buildSolid(type, w, d, compDef) {
  const profile = compDef.profile;
  const matDef = compDef.material;
  const h = compDef.body.height;
  const group = new THREE.Group();

  const mat = makeMaterial(matDef, false);
  if (matDef.emissive) {
    mat.emissive = new THREE.Color(matDef.emissive);
    mat.emissiveIntensity = matDef.emissiveIntensity ?? 0.2;
  }

  let mesh;
  if (profile.type === 'cylinder') {
    mesh = new THREE.Mesh(new THREE.CylinderGeometry(w / 2, w / 2, h, profile.sides || 6), mat);
    mesh.position.y = h / 2 + 0.05;
  } else if (profile.type === 'icosphere') {
    mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(w * 0.55, profile.subdivisions || 1), mat);
    mesh.position.y = h / 2 + 0.15;
  } else if (profile.type === 'octahedron') {
    mesh = new THREE.Mesh(new THREE.OctahedronGeometry(w * 0.55), mat);
    mesh.position.y = h / 2 + 0.15;
  } else if (profile.type === 'fence') {
    // Flat translucent ground region with glowing corner posts
    const planeMat = makeMaterial(matDef, true);
    planeMat.depthWrite = false;
    planeMat.side = THREE.DoubleSide;
    const plane = new THREE.Mesh(new THREE.BoxGeometry(w - 0.1, 0.06, d - 0.1), planeMat);
    plane.position.y = 0.03;
    plane.name = 'body';
    group.add(plane);

    const postColor = new THREE.Color(matDef.emissive || matDef.color);
    const postMat = new THREE.MeshStandardMaterial({
      color: postColor, emissive: postColor, emissiveIntensity: 2.0,
    });
    const postGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.5, 8);
    const barGeo = new THREE.CylinderGeometry(0.02, 0.02, 1, 6);
    const hw = (w - 0.2) / 2, hd = (d - 0.2) / 2;
    for (const [px, pz] of [[-hw, -hd], [hw, -hd], [-hw, hd], [hw, hd]]) {
      const post = new THREE.Mesh(postGeo, postMat);
      post.position.set(px, 0.25, pz);
      group.add(post);
    }
    // Horizontal bars connecting posts (top edges)
    const barMat = new THREE.MeshStandardMaterial({
      color: postColor, emissive: postColor, emissiveIntensity: 1.2,
      transparent: true, opacity: 0.7,
    });
    const barW = w - 0.2, barD = d - 0.2;
    for (const [bx, bz, len, rotY] of [[0, -hd, barW, 0], [0, hd, barW, 0], [-hw, 0, barD, Math.PI/2], [hw, 0, barD, Math.PI/2]]) {
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, len, 6), barMat);
      bar.position.set(bx, 0.48, bz);
      bar.rotation.z = Math.PI / 2;
      bar.rotation.y = rotY;
      group.add(bar);
    }
    return group;
  } else {
    mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.y = h / 2 + 0.05;
  }

  mesh.castShadow = true;
  mesh.name = 'body';
  if (compDef.features?.spin?.enabled) mesh.userData.spin = true;
  group.add(mesh);

  return group;
}

// ── Public API ──────────────────────────────────────────────

/**
 * Build a Three.js mesh for a component type.
 * Reads definition from manifest. Falls back to basic box if unknown.
 */
export function buildComponentMesh(type, w, d) {
  if (!_manifest) {
    console.warn('Manifest not loaded, using fallback');
    return new THREE.Group();
  }

  const compDef = _manifest.components[type];
  if (!compDef) {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.BoxGeometry(w, 1, d), new THREE.MeshStandardMaterial({ color: 0x888888 })));
    return g;
  }

  if (compDef.body.solid) {
    return buildSolid(type, w, d, compDef);
  } else {
    return buildContainer(type, w, d, compDef);
  }
}

/**
 * Play a named animation on a component mesh.
 * Returns a promise that resolves when the animation completes.
 */
export function playAnimation(mesh, type, animName) {
  const compDef = _manifest?.components?.[type];
  if (!compDef) return Promise.resolve();

  const anim = compDef.animations?.[animName];
  if (!anim || anim.type === 'none') return Promise.resolve();

  return new Promise(resolve => {
    if (anim.type === 'rotation') {
      const target = mesh.getObjectByName(anim.target);
      if (!target) { resolve(); return; }

      const from = anim.from;
      const to = anim.to;
      const dur = anim.duration || 500;
      const start = performance.now();

      const step = () => {
        const t = Math.min((performance.now() - start) / dur, 1);
        const ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        target.rotation.x = from + (to - from) * ease;
        if (t < 1) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    } else {
      resolve();
    }
  });
}
