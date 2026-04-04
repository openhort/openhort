#!/usr/bin/env python3
"""Generate GLB files for all HortPlanner models using Playwright + Three.js GLTFExporter.

Opens a browser page that loads Three.js from CDN, builds each model's geometry
in JavaScript, exports to GLB binary via GLTFExporter, and returns base64 for
Python to decode and save.

Usage:
    poetry run python scripts/generate-glbs.py
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "subprojects" / "hortplanner" / "static" / "models" / "glb"
SERVER_URL = "http://localhost:8960/"
CDN_FALLBACK = "https://cdn.jsdelivr.net/npm/three@0.162.0"

# ── JavaScript helper injected once into the page ─────────────────────────────
SETUP_JS = r"""
window._generateGLB = async function(buildFn) {
    const THREE = await import('three');
    const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');

    const scene = new THREE.Scene();
    const fn = new Function('scene', 'THREE', buildFn);
    fn(scene, THREE);

    const exporter = new GLTFExporter();
    return new Promise((resolve, reject) => {
        exporter.parse(scene, (result) => {
            const bytes = new Uint8Array(result);
            let binary = '';
            for (let i = 0; i < bytes.length; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            resolve(btoa(binary));
        }, (error) => {
            reject(error);
        }, { binary: true });
    });
};
"""

# ── Shared JS snippets ───────────────────────────────────────────────────────

def _container_js(
    inner_w: float,
    inner_d: float,
    wall_h: float,
    wall_t: float,
    floor_t: float,
    corner_r: float,
    color: str,
    metalness: float,
    roughness: float,
    opacity: float = 1.0,
    feet: bool = False,
    screen: bool = False,
) -> str:
    """JS code for a rounded-rect container (walls + floor), optionally with feet/screen."""
    transparent = "true" if opacity < 1.0 else "false"
    js = f"""
    // Rounded-rect shape
    const shape = new THREE.Shape();
    const iw = {inner_w}, id = {inner_d}, wt = {wall_t}, cr = {corner_r};
    const ow = iw + wt * 2, od = id + wt * 2;
    const hw = ow / 2, hd = od / 2;
    const r = Math.min(cr, hw, hd);

    // Outer path (clockwise)
    shape.moveTo(-hw + r, -hd);
    shape.lineTo(hw - r, -hd);
    shape.quadraticCurveTo(hw, -hd, hw, -hd + r);
    shape.lineTo(hw, hd - r);
    shape.quadraticCurveTo(hw, hd, hw - r, hd);
    shape.lineTo(-hw + r, hd);
    shape.quadraticCurveTo(-hw, hd, -hw, hd - r);
    shape.lineTo(-hw, -hd + r);
    shape.quadraticCurveTo(-hw, -hd, -hw + r, -hd);

    // Inner hole (counter-clockwise)
    const ihw = iw / 2, ihd = id / 2;
    const ir = Math.max(0, r - wt);
    const hole = new THREE.Path();
    hole.moveTo(-ihw + ir, -ihd);
    hole.lineTo(ihw - ir, -ihd);
    hole.quadraticCurveTo(ihw, -ihd, ihw, -ihd + ir);
    hole.lineTo(ihw, ihd - ir);
    hole.quadraticCurveTo(ihw, ihd, ihw - ir, ihd);
    hole.lineTo(-ihw + ir, ihd);
    hole.quadraticCurveTo(-ihw, ihd, -ihw, ihd - ir);
    hole.lineTo(-ihw, -ihd + ir);
    hole.quadraticCurveTo(-ihw, -ihd, -ihw + ir, -ihd);
    shape.holes.push(hole);

    const wallMat = new THREE.MeshStandardMaterial({{
        color: '{color}', metalness: {metalness}, roughness: {roughness},
        opacity: {opacity}, transparent: {transparent}, side: THREE.DoubleSide
    }});

    // Walls via extrude
    const extrudeSettings = {{ depth: {wall_h}, bevelEnabled: false }};
    const wallGeo = new THREE.ExtrudeGeometry(shape, extrudeSettings);
    const wallMesh = new THREE.Mesh(wallGeo, wallMat);
    wallMesh.rotation.x = -Math.PI / 2;
    wallMesh.position.y = {floor_t};
    scene.add(wallMesh);

    // Floor
    const floorShape = new THREE.Shape();
    floorShape.moveTo(-hw + r, -hd);
    floorShape.lineTo(hw - r, -hd);
    floorShape.quadraticCurveTo(hw, -hd, hw, -hd + r);
    floorShape.lineTo(hw, hd - r);
    floorShape.quadraticCurveTo(hw, hd, hw - r, hd);
    floorShape.lineTo(-hw + r, hd);
    floorShape.quadraticCurveTo(-hw, hd, -hw, hd - r);
    floorShape.lineTo(-hw, -hd + r);
    floorShape.quadraticCurveTo(-hw, -hd, -hw + r, -hd);

    const floorGeo = new THREE.ExtrudeGeometry(floorShape, {{ depth: {floor_t}, bevelEnabled: false }});
    const floorMat = new THREE.MeshStandardMaterial({{
        color: '#1a1a2e', metalness: 0.2, roughness: 0.8,
        opacity: {opacity}, transparent: {transparent}
    }});
    const floorMesh = new THREE.Mesh(floorGeo, floorMat);
    floorMesh.rotation.x = -Math.PI / 2;
    floorMesh.position.y = 0;
    scene.add(floorMesh);
    """

    if feet:
        js += f"""
    // Feet
    const feetPositions = [
        [-hw + 0.35, 0, -hd + 0.35],
        [ hw - 0.35, 0, -hd + 0.35],
        [-hw + 0.35, 0,  hd - 0.35],
        [ hw - 0.35, 0,  hd - 0.35]
    ];
    const footGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.06, 12);
    const footMat = new THREE.MeshStandardMaterial({{ color: '#333333', metalness: 0.5, roughness: 0.5 }});
    for (const [fx, fy, fz] of feetPositions) {{
        const foot = new THREE.Mesh(footGeo, footMat);
        foot.position.set(fx, 0.03, fz);
        scene.add(foot);
    }}
    // Shift everything up so feet sit at y=0
    scene.traverse(c => {{ if (c !== scene) c.position.y -= 0; }});
    """

    if screen:
        js += f"""
    // Screen panel behind the base
    const scrW = ow - 0.1, scrH = {wall_h} * 2.5, scrT = 0.05;
    const screenGeo = new THREE.BoxGeometry(scrW, scrH, scrT);
    const screenMat = new THREE.MeshStandardMaterial({{
        color: '{color}', metalness: {metalness}, roughness: {roughness}
    }});
    const screenMesh = new THREE.Mesh(screenGeo, screenMat);
    screenMesh.name = 'screen';
    // Position: behind the base, tilted
    screenMesh.position.set(0, {floor_t} + {wall_h} + scrH / 2 * Math.cos(0.17), -hd + scrT / 2);
    screenMesh.rotation.x = -0.17;
    scene.add(screenMesh);

    // Display surface on the screen
    const dispGeo = new THREE.BoxGeometry(scrW - 0.15, scrH - 0.15, 0.002);
    const dispMat = new THREE.MeshStandardMaterial({{
        color: '#0c1829', emissive: '#1a3050', emissiveIntensity: 0.6,
        metalness: 0.1, roughness: 0.3
    }});
    const dispMesh = new THREE.Mesh(dispGeo, dispMat);
    dispMesh.position.set(0, 0, scrT / 2 + 0.001);
    screenMesh.add(dispMesh);
    """

    return js


# ── Model definitions ─────────────────────────────────────────────────────────

MODELS: dict[str, str] = {}

# 1. mac-mini
MODELS["mac-mini"] = _container_js(
    inner_w=6.0, inner_d=6.0, wall_h=1.0, wall_t=0.10, floor_t=0.08,
    corner_r=0.35, color="#a8b0bc", metalness=0.85, roughness=0.20, feet=True,
)

# 2. macbook
MODELS["macbook"] = _container_js(
    inner_w=7.0, inner_d=5.0, wall_h=0.4, wall_t=0.10, floor_t=0.08,
    corner_r=0.20, color="#6b7280", metalness=0.80, roughness=0.25, screen=True,
)

# 3. rpi
MODELS["rpi"] = _container_js(
    inner_w=5.0, inner_d=5.0, wall_h=0.5, wall_t=0.10, floor_t=0.08,
    corner_r=0.08, color="#16a34a", metalness=0.30, roughness=0.70,
)

# 4. cloud-vm
MODELS["cloud-vm"] = _container_js(
    inner_w=6.0, inner_d=6.0, wall_h=1.2, wall_t=0.10, floor_t=0.08,
    corner_r=0.10, color="#3b82f6", metalness=0.10, roughness=0.90, opacity=0.55,
)

# 5. docker
MODELS["docker"] = _container_js(
    inner_w=1.5, inner_d=1.5, wall_h=1.0, wall_t=0.10, floor_t=0.08,
    corner_r=0.10, color="#0ea5e9", metalness=0.40, roughness=0.50,
)

# 6. virtual-hort
MODELS["virtual-hort"] = _container_js(
    inner_w=1.5, inner_d=1.5, wall_h=1.0, wall_t=0.10, floor_t=0.08,
    corner_r=0.10, color="#a855f7", metalness=0.10, roughness=0.90, opacity=0.45,
)

# 7. mcp-server — hexagonal prism
MODELS["mcp-server"] = """
    const radius = 0.4;
    const height = 2.0;
    const geo = new THREE.CylinderGeometry(radius, radius, height, 6);
    const mat = new THREE.MeshStandardMaterial({
        color: '#f59e0b', metalness: 0.60, roughness: 0.30,
        emissive: '#f59e0b', emissiveIntensity: 0.25
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = height / 2;
    scene.add(mesh);
"""

# 8. llming — icosphere
MODELS["llming"] = """
    const radius = 0.4;
    const height = 2.0;
    const geo = new THREE.IcosahedronGeometry(radius, 1);
    const mat = new THREE.MeshStandardMaterial({
        color: '#8b5cf6', metalness: 0.30, roughness: 0.50,
        emissive: '#8b5cf6', emissiveIntensity: 0.35
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = 'body';
    mesh.position.y = height / 2;
    scene.add(mesh);
"""

# 9. program — box
MODELS["program"] = """
    const w = 0.8, h = 2.0, d = 0.8;
    const geo = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshStandardMaterial({
        color: '#10b981', metalness: 0.50, roughness: 0.40
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = h / 2;
    scene.add(mesh);
"""

# 10. agent — octahedron
MODELS["agent"] = """
    const radius = 0.5;
    const height = 2.5;
    const geo = new THREE.OctahedronGeometry(radius);
    const mat = new THREE.MeshStandardMaterial({
        color: '#06b6d4', metalness: 0.25, roughness: 0.35,
        emissive: '#06b6d4', emissiveIntensity: 0.5
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = 'body';
    mesh.position.y = height / 2;
    scene.add(mesh);
"""

# 11. fence — flat ground plane with corner posts and bars
MODELS["fence"] = """
    const w = 1.6, d = 1.6, postH = 0.5, postR = 0.03, barR = 0.015;
    const matOpts = {
        color: '#f97316', metalness: 0.0, roughness: 1.0,
        opacity: 0.30, transparent: true,
        emissive: '#f97316', emissiveIntensity: 0.4
    };
    const mat = new THREE.MeshStandardMaterial(matOpts);

    // Ground plane
    const planeGeo = new THREE.BoxGeometry(w, 0.02, d);
    const planeMesh = new THREE.Mesh(planeGeo, mat.clone());
    planeMesh.material.opacity = 0.15;
    planeMesh.position.y = 0.01;
    scene.add(planeMesh);

    // Corner posts
    const postGeo = new THREE.CylinderGeometry(postR, postR, postH, 8);
    const hw = w / 2, hd = d / 2;
    const corners = [[-hw, hd], [hw, hd], [hw, -hd], [-hw, -hd]];
    for (const [cx, cz] of corners) {
        const post = new THREE.Mesh(postGeo, mat);
        post.position.set(cx, postH / 2, cz);
        scene.add(post);
    }

    // Top bars connecting corners
    const barPairs = [[0,1],[1,2],[2,3],[3,0]];
    for (const [a, b] of barPairs) {
        const [ax, az] = corners[a];
        const [bx, bz] = corners[b];
        const dx = bx - ax, dz = bz - az;
        const len = Math.sqrt(dx * dx + dz * dz);
        const barGeo = new THREE.CylinderGeometry(barR, barR, len, 6);
        const bar = new THREE.Mesh(barGeo, mat);
        bar.position.set((ax + bx) / 2, postH, (az + bz) / 2);
        bar.rotation.z = Math.PI / 2;
        // Rotate around y to align with direction
        bar.rotation.y = Math.atan2(dz, dx);
        // CylinderGeometry is along Y, so we rotate to lay it horizontal
        bar.rotation.set(0, Math.atan2(dz, dx), Math.PI / 2);
        scene.add(bar);
    }

    // Mid-height bars
    for (const [a, b] of barPairs) {
        const [ax, az] = corners[a];
        const [bx, bz] = corners[b];
        const dx = bx - ax, dz = bz - az;
        const len = Math.sqrt(dx * dx + dz * dz);
        const barGeo = new THREE.CylinderGeometry(barR, barR, len, 6);
        const bar = new THREE.Mesh(barGeo, mat);
        bar.position.set((ax + bx) / 2, postH * 0.5, (az + bz) / 2);
        bar.rotation.set(0, Math.atan2(dz, dx), Math.PI / 2);
        scene.add(bar);
    }
"""

# ── Home / furniture models ──────────────────────────────────────────────────

# Helper constants: 1 tile = 0.25m in-scene
T = 0.25  # tile size


def _box_model(w: int, d: int, h: float, color: str, metalness: float = 0.1, roughness: float = 0.6) -> str:
    """Simple box sitting on ground."""
    sw, sd = w * T, d * T
    return f"""
    const geo = new THREE.BoxGeometry({sw}, {h}, {sd});
    const mat = new THREE.MeshStandardMaterial({{ color: '{color}', metalness: {metalness}, roughness: {roughness} }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = {h} / 2;
    scene.add(mesh);
    """


def _table_model(w: int, d: int, h: float, color: str, metalness: float = 0.05, roughness: float = 0.6) -> str:
    """Table with top panel and 4 legs."""
    sw, sd = w * T, d * T
    top_t = 0.05
    leg_r = 0.03
    return f"""
    const sw = {sw}, sd = {sd}, h = {h}, topT = {top_t}, legR = {leg_r};
    const topGeo = new THREE.BoxGeometry(sw, topT, sd);
    const mat = new THREE.MeshStandardMaterial({{ color: '{color}', metalness: {metalness}, roughness: {roughness} }});
    const top = new THREE.Mesh(topGeo, mat);
    top.position.y = h - topT / 2;
    scene.add(top);

    const legH = h - topT;
    const legGeo = new THREE.CylinderGeometry(legR, legR, legH, 8);
    const insetX = sw / 2 - 0.06, insetZ = sd / 2 - 0.06;
    const legPositions = [
        [-insetX, legH / 2, -insetZ],
        [ insetX, legH / 2, -insetZ],
        [-insetX, legH / 2,  insetZ],
        [ insetX, legH / 2,  insetZ]
    ];
    for (const [lx, ly, lz] of legPositions) {{
        const leg = new THREE.Mesh(legGeo, mat);
        leg.position.set(lx, ly, lz);
        scene.add(leg);
    }}
    """


# 12. sofa
MODELS["sofa"] = f"""
    const sw = {4 * T}, sd = {8 * T}, h = 1.0;
    const mat = new THREE.MeshStandardMaterial({{ color: '#6b7280', roughness: 0.6, metalness: 0.1 }});

    // Base
    const baseH = 0.35;
    const baseGeo = new THREE.BoxGeometry(sw, baseH, sd);
    const base = new THREE.Mesh(baseGeo, mat);
    base.position.y = baseH / 2;
    scene.add(base);

    // Seat cushion
    const cushH = 0.15;
    const cushGeo = new THREE.BoxGeometry(sw - 0.05, cushH, sd - 0.1);
    const cushMat = new THREE.MeshStandardMaterial({{ color: '#7c8490', roughness: 0.7, metalness: 0.05 }});
    const cush = new THREE.Mesh(cushGeo, cushMat);
    cush.position.y = baseH + cushH / 2;
    scene.add(cush);

    // Back panel
    const backH = h - baseH;
    const backGeo = new THREE.BoxGeometry(sw, backH, 0.12);
    const back = new THREE.Mesh(backGeo, mat);
    back.position.set(0, baseH + backH / 2, -sd / 2 + 0.06);
    scene.add(back);
"""

# 13. chair
MODELS["chair"] = f"""
    const sw = {2 * T}, sd = {2 * T}, seatH = 0.5;
    const mat = new THREE.MeshStandardMaterial({{ color: '#78716c', roughness: 0.6, metalness: 0.1 }});

    // Seat
    const seatT = 0.05;
    const seatGeo = new THREE.BoxGeometry(sw, seatT, sd);
    const seat = new THREE.Mesh(seatGeo, mat);
    seat.position.y = seatH;
    scene.add(seat);

    // 4 legs
    const legR = 0.025, legH = seatH - seatT / 2;
    const legGeo = new THREE.CylinderGeometry(legR, legR, legH, 8);
    const inX = sw / 2 - 0.04, inZ = sd / 2 - 0.04;
    for (const [lx, lz] of [[-inX, -inZ], [inX, -inZ], [-inX, inZ], [inX, inZ]]) {{
        const leg = new THREE.Mesh(legGeo, mat);
        leg.position.set(lx, legH / 2, lz);
        scene.add(leg);
    }}

    // Backrest
    const backH = 0.55;
    const backGeo = new THREE.BoxGeometry(sw, backH, 0.04);
    const back = new THREE.Mesh(backGeo, mat);
    back.position.set(0, seatH + backH / 2, -sd / 2 + 0.02);
    scene.add(back);
"""

# 14. dining-table
MODELS["dining-table"] = _table_model(4, 6, 0.9, "#92400e")

# 15. coffee-table
MODELS["coffee-table"] = _table_model(3, 5, 0.5, "#78716c", metalness=0.1, roughness=0.5)

# 16. desk
MODELS["desk"] = _table_model(4, 3, 0.9, "#92400e")

# 17. bed-single
MODELS["bed-single"] = f"""
    const sw = {4 * T}, sd = {8 * T}, h = 0.6;
    const woodMat = new THREE.MeshStandardMaterial({{ color: '#92400e', roughness: 0.7, metalness: 0.05 }});
    const bedMat = new THREE.MeshStandardMaterial({{ color: '#60a5fa', roughness: 0.8, metalness: 0.0 }});

    // Frame
    const frameH = 0.25;
    const frameGeo = new THREE.BoxGeometry(sw, frameH, sd);
    const frame = new THREE.Mesh(frameGeo, woodMat);
    frame.position.y = frameH / 2;
    scene.add(frame);

    // Mattress
    const mattH = h - frameH;
    const mattGeo = new THREE.BoxGeometry(sw - 0.04, mattH, sd - 0.04);
    const matt = new THREE.Mesh(mattGeo, bedMat);
    matt.position.y = frameH + mattH / 2;
    scene.add(matt);

    // Headboard
    const hbH = 0.4;
    const hbGeo = new THREE.BoxGeometry(sw, hbH, 0.06);
    const hb = new THREE.Mesh(hbGeo, woodMat);
    hb.position.set(0, frameH + hbH / 2, -sd / 2 + 0.03);
    scene.add(hb);
"""

# 18. bed-double
MODELS["bed-double"] = f"""
    const sw = {7 * T}, sd = {8 * T}, h = 0.6;
    const woodMat = new THREE.MeshStandardMaterial({{ color: '#92400e', roughness: 0.7, metalness: 0.05 }});
    const bedMat = new THREE.MeshStandardMaterial({{ color: '#60a5fa', roughness: 0.8, metalness: 0.0 }});

    // Frame
    const frameH = 0.25;
    const frameGeo = new THREE.BoxGeometry(sw, frameH, sd);
    const frame = new THREE.Mesh(frameGeo, woodMat);
    frame.position.y = frameH / 2;
    scene.add(frame);

    // Mattress
    const mattH = h - frameH;
    const mattGeo = new THREE.BoxGeometry(sw - 0.04, mattH, sd - 0.04);
    const matt = new THREE.Mesh(mattGeo, bedMat);
    matt.position.y = frameH + mattH / 2;
    scene.add(matt);

    // Headboard
    const hbH = 0.4;
    const hbGeo = new THREE.BoxGeometry(sw, hbH, 0.06);
    const hb = new THREE.Mesh(hbGeo, woodMat);
    hb.position.set(0, frameH + hbH / 2, -sd / 2 + 0.03);
    scene.add(hb);
"""

# 19. wardrobe — tall box with front panel line
MODELS["wardrobe"] = f"""
    const sw = {5 * T}, sd = {2 * T}, h = 2.8;
    const mat = new THREE.MeshStandardMaterial({{ color: '#78716c', roughness: 0.6, metalness: 0.1 }});

    const bodyGeo = new THREE.BoxGeometry(sw, h, sd);
    const body = new THREE.Mesh(bodyGeo, mat);
    body.position.y = h / 2;
    scene.add(body);

    // Front panel line (subtle darker strip down the middle)
    const lineGeo = new THREE.BoxGeometry(0.01, h - 0.1, 0.002);
    const lineMat = new THREE.MeshStandardMaterial({{ color: '#57534e', roughness: 0.5, metalness: 0.1 }});
    const line = new THREE.Mesh(lineGeo, lineMat);
    line.position.set(0, h / 2, sd / 2 + 0.001);
    scene.add(line);
"""

# 20. nightstand
MODELS["nightstand"] = _box_model(2, 2, 0.6, "#78716c")

# 21. bookshelf — box with horizontal shelf lines
MODELS["bookshelf"] = f"""
    const sw = {4 * T}, sd = {1 * T}, h = 2.8;
    const mat = new THREE.MeshStandardMaterial({{ color: '#92400e', roughness: 0.7, metalness: 0.05 }});

    const bodyGeo = new THREE.BoxGeometry(sw, h, sd);
    const body = new THREE.Mesh(bodyGeo, mat);
    body.position.y = h / 2;
    scene.add(body);

    // Shelf lines
    const shelfMat = new THREE.MeshStandardMaterial({{ color: '#78350f', roughness: 0.6, metalness: 0.05 }});
    const numShelves = 5;
    for (let i = 1; i <= numShelves; i++) {{
        const sy = (h / (numShelves + 1)) * i;
        const shelfGeo = new THREE.BoxGeometry(sw - 0.02, 0.02, sd + 0.002);
        const shelf = new THREE.Mesh(shelfGeo, shelfMat);
        shelf.position.set(0, sy, 0);
        scene.add(shelf);
    }}
"""

# 22. tv — thin panel on stand
MODELS["tv"] = f"""
    const sw = {5 * T}, sd = {1 * T}, h = 1.8;
    const mat = new THREE.MeshStandardMaterial({{ color: '#1e293b', roughness: 0.3, metalness: 0.4 }});

    // Stand base
    const standW = 0.4, standD = 0.15, standH = 0.5;
    const standGeo = new THREE.BoxGeometry(standW, standH, standD);
    const stand = new THREE.Mesh(standGeo, mat);
    stand.position.y = standH / 2;
    scene.add(stand);

    // Screen panel
    const screenH = h - standH;
    const screenGeo = new THREE.BoxGeometry(sw, screenH, 0.04);
    const screen = new THREE.Mesh(screenGeo, mat);
    screen.position.y = standH + screenH / 2;
    scene.add(screen);

    // Display surface
    const dispGeo = new THREE.BoxGeometry(sw - 0.06, screenH - 0.06, 0.002);
    const dispMat = new THREE.MeshStandardMaterial({{
        color: '#0f172a', emissive: '#1e3a5f', emissiveIntensity: 0.3,
        metalness: 0.1, roughness: 0.2
    }});
    const disp = new THREE.Mesh(dispGeo, dispMat);
    disp.position.set(0, standH + screenH / 2, 0.021);
    scene.add(disp);
"""

# 23. armchair
MODELS["armchair"] = f"""
    const sw = {3 * T}, sd = {3 * T}, h = 0.9;
    const mat = new THREE.MeshStandardMaterial({{ color: '#78716c', roughness: 0.6, metalness: 0.1 }});

    // Seat base
    const baseH = 0.4;
    const baseGeo = new THREE.BoxGeometry(sw, baseH, sd);
    const base = new THREE.Mesh(baseGeo, mat);
    base.position.y = baseH / 2;
    scene.add(base);

    // Back
    const backH = h - baseH;
    const backGeo = new THREE.BoxGeometry(sw, backH, 0.10);
    const back = new THREE.Mesh(backGeo, mat);
    back.position.set(0, baseH + backH / 2, -sd / 2 + 0.05);
    scene.add(back);

    // Arms
    const armH = 0.25, armW = 0.08;
    const armGeo = new THREE.BoxGeometry(armW, armH, sd);
    for (const side of [-1, 1]) {{
        const arm = new THREE.Mesh(armGeo, mat);
        arm.position.set(side * (sw / 2 - armW / 2), baseH + armH / 2, 0);
        scene.add(arm);
    }}
"""

# 24. counter
MODELS["counter"] = _box_model(3, 2, 1.1, "#d4d4d8", metalness=0.2, roughness=0.4)

# 25. stove — box with dark top
MODELS["stove"] = f"""
    const sw = {3 * T}, sd = {3 * T}, h = 1.1;
    const bodyMat = new THREE.MeshStandardMaterial({{ color: '#27272a', roughness: 0.3, metalness: 0.5 }});

    const bodyGeo = new THREE.BoxGeometry(sw, h, sd);
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = h / 2;
    scene.add(body);

    // Dark cooktop
    const topGeo = new THREE.BoxGeometry(sw + 0.005, 0.02, sd + 0.005);
    const topMat = new THREE.MeshStandardMaterial({{ color: '#18181b', roughness: 0.1, metalness: 0.6 }});
    const top = new THREE.Mesh(topGeo, topMat);
    top.position.y = h + 0.01;
    scene.add(top);

    // Burner rings
    const burnerGeo = new THREE.RingGeometry(0.06, 0.08, 16);
    const burnerMat = new THREE.MeshStandardMaterial({{ color: '#3f3f46', roughness: 0.3, metalness: 0.4, side: THREE.DoubleSide }});
    const offsets = [[-0.12, -0.12], [0.12, -0.12], [-0.12, 0.12], [0.12, 0.12]];
    for (const [ox, oz] of offsets) {{
        const burner = new THREE.Mesh(burnerGeo, burnerMat);
        burner.rotation.x = -Math.PI / 2;
        burner.position.set(ox, h + 0.021, oz);
        scene.add(burner);
    }}
"""

# 26. fridge
MODELS["fridge"] = _box_model(3, 3, 2.5, "#d4d4d8", metalness=0.3, roughness=0.3)

# 27. sink
MODELS["sink"] = _box_model(3, 2, 1.1, "#a8a29e", metalness=0.4, roughness=0.3)

# 28. toilet
MODELS["toilet"] = _box_model(2, 3, 0.5, "#fafaf9", metalness=0.1, roughness=0.2)

# 29. bathtub — open-top box
MODELS["bathtub"] = f"""
    const sw = {4 * T}, sd = {7 * T}, h = 0.8, wt = 0.06;
    const mat = new THREE.MeshStandardMaterial({{ color: '#fafaf9', roughness: 0.2, metalness: 0.1 }});

    // Outer shell
    const outerGeo = new THREE.BoxGeometry(sw, h, sd);
    const outer = new THREE.Mesh(outerGeo, mat);
    outer.position.y = h / 2;
    scene.add(outer);

    // Inner cutout (darker)
    const innerGeo = new THREE.BoxGeometry(sw - wt * 2, h - wt + 0.01, sd - wt * 2);
    const innerMat = new THREE.MeshStandardMaterial({{ color: '#e7e5e4', roughness: 0.2, metalness: 0.15 }});
    const inner = new THREE.Mesh(innerGeo, innerMat);
    inner.position.y = h / 2 + wt / 2;
    scene.add(inner);
"""

# 30. shower — flat tray
MODELS["shower"] = _box_model(4, 4, 0.15, "#e7e5e4", metalness=0.1, roughness=0.2)

# 31. basin
MODELS["basin"] = _box_model(2, 2, 1.0, "#fafaf9", metalness=0.1, roughness=0.2)

# 32. stairs-straight — stepped geometry
MODELS["stairs-straight"] = f"""
    const sw = {4 * T}, sd = {10 * T}, totalH = 3.5;
    const mat = new THREE.MeshStandardMaterial({{ color: '#92400e', roughness: 0.7, metalness: 0.05 }});
    const numSteps = 10;
    const stepH = totalH / numSteps;
    const stepD = sd / numSteps;

    for (let i = 0; i < numSteps; i++) {{
        const sh = stepH;
        const geo = new THREE.BoxGeometry(sw, sh, stepD);
        const step = new THREE.Mesh(geo, mat);
        step.position.set(0, stepH * i + sh / 2, -sd / 2 + stepD * i + stepD / 2);
        scene.add(step);
    }}
"""

# 33. washing-machine — box with cylindrical drum
MODELS["washing-machine"] = f"""
    const sw = {3 * T}, sd = {3 * T}, h = 1.1;
    const mat = new THREE.MeshStandardMaterial({{ color: '#d4d4d8', roughness: 0.3, metalness: 0.3 }});

    // Body
    const bodyGeo = new THREE.BoxGeometry(sw, h, sd);
    const body = new THREE.Mesh(bodyGeo, mat);
    body.position.y = h / 2;
    scene.add(body);

    // Drum (visible on front face)
    const drumR = Math.min(sw, h) * 0.35;
    const drumGeo = new THREE.CylinderGeometry(drumR, drumR, 0.04, 24);
    const drumMat = new THREE.MeshStandardMaterial({{ color: '#a1a1aa', roughness: 0.2, metalness: 0.5 }});
    const drum = new THREE.Mesh(drumGeo, drumMat);
    drum.name = 'drum';
    drum.rotation.x = Math.PI / 2;
    drum.position.set(0, h * 0.45, sd / 2 + 0.001);
    scene.add(drum);

    // Door ring
    const ringGeo = new THREE.TorusGeometry(drumR, 0.015, 8, 24);
    const ringMat = new THREE.MeshStandardMaterial({{ color: '#71717a', roughness: 0.2, metalness: 0.4 }});
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.position.set(0, h * 0.45, sd / 2 + 0.02);
    scene.add(ring);
"""

# 34. floor-lamp — thin pole + lampshade sphere
MODELS["floor-lamp"] = f"""
    const h = 2.0, poleR = 0.02;
    const poleMat = new THREE.MeshStandardMaterial({{ color: '#78716c', roughness: 0.5, metalness: 0.2 }});

    // Base disc
    const baseGeo = new THREE.CylinderGeometry(0.12, 0.15, 0.03, 16);
    const base = new THREE.Mesh(baseGeo, poleMat);
    base.position.y = 0.015;
    scene.add(base);

    // Pole
    const poleGeo = new THREE.CylinderGeometry(poleR, poleR, h - 0.15, 8);
    const pole = new THREE.Mesh(poleGeo, poleMat);
    pole.position.y = 0.03 + (h - 0.15) / 2;
    scene.add(pole);

    // Lampshade sphere
    const shadeGeo = new THREE.SphereGeometry(0.12, 16, 12);
    const shadeMat = new THREE.MeshStandardMaterial({{
        color: '#fef3c7', roughness: 0.4, metalness: 0.1,
        emissive: '#fef3c7', emissiveIntensity: 0.5
    }});
    const shade = new THREE.Mesh(shadeGeo, shadeMat);
    shade.position.y = h - 0.05;
    scene.add(shade);
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(MODELS)} GLB models...")
    print(f"Output directory: {OUT_DIR}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Try the local server first, fall back to a minimal page with CDN imports
        try:
            resp = page.goto(SERVER_URL, timeout=5000)
            if resp and resp.ok:
                print(f"Using local server at {SERVER_URL}")
            else:
                raise Exception("Server returned non-OK")
        except Exception:
            print(f"Server not available at {SERVER_URL}, using CDN fallback...")
            html = f"""<!DOCTYPE html>
<html><head>
<script type="importmap">
{{
    "imports": {{
        "three": "{CDN_FALLBACK}/build/three.module.js",
        "three/addons/": "{CDN_FALLBACK}/examples/jsm/"
    }}
}}
</script>
</head><body><p>GLB Generator</p></body></html>"""
            page.set_content(html)
            page.wait_for_timeout(1000)

        # Inject the generator function
        page.evaluate(SETUP_JS)
        print("Injected GLB generator function\n")

        results: dict[str, int] = {}
        errors: list[str] = []

        for name, build_js in MODELS.items():
            try:
                b64 = page.evaluate(f"window._generateGLB(`{_escape_js(build_js)}`)")
                if b64:
                    data = base64.b64decode(b64)
                    out_path = OUT_DIR / f"{name}.glb"
                    out_path.write_bytes(data)
                    results[name] = len(data)
                    print(f"  {name}.glb  ({len(data):,} bytes)")
                else:
                    errors.append(f"{name}: export returned null")
                    print(f"  {name}.glb  FAILED (null result)")
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"  {name}.glb  ERROR: {e}")

        browser.close()

    # Summary
    print(f"\n{'='*50}")
    print(f"Generated: {len(results)}/{len(MODELS)} models")
    total_bytes = sum(results.values())
    print(f"Total size: {total_bytes:,} bytes ({total_bytes / 1024:.1f} KB)")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")

    # List all files
    print(f"\nFiles in {OUT_DIR}:")
    for f in sorted(OUT_DIR.glob("*.glb")):
        print(f"  {f.name:30s} {f.stat().st_size:>8,} bytes")


def _escape_js(code: str) -> str:
    """Escape JS code for embedding in a template literal."""
    return code.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


if __name__ == "__main__":
    main()
