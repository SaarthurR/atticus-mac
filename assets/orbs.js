// thinking-orbs 0.3.2 engine (dist/index-B8WsUNf5.js) — MIT License, Copyright (c) 2026 Jakub Antalik. https://github.com/Jakubantalik/thinking-orbs
function lerp(a, b, f) {
  return a + (b - a) * f;
}
function frac(x) {
  return x - Math.floor(x);
}
function vnoise(x, y) {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  let fx = x - xi;
  let fy = y - yi;
  fx = fx * fx * (3 - 2 * fx);
  fy = fy * fy * (3 - 2 * fy);
  const a = hashD(xi, yi);
  const b = hashD(xi + 1, yi);
  const c = hashD(xi, yi + 1);
  const d = hashD(xi + 1, yi + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}
function hashD(a, b) {
  const h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return h - Math.floor(h);
}
function fibDir(i, n) {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - 2 * (i + 0.5) / n;
  const rad = Math.sqrt(1 - y * y);
  const a = i * golden;
  return [rad * Math.cos(a), y, rad * Math.sin(a)];
}
function angleDelta(a, b) {
  return Math.atan2(Math.sin(a - b), Math.cos(a - b));
}
function makeProj(yaw, tilt, cx, cy, scale) {
  const st = Math.sin(tilt);
  const ct = Math.cos(tilt);
  const sy = Math.sin(yaw);
  const cyw = Math.cos(yaw);
  return (x, y, z) => {
    const x1 = x * cyw + z * sy;
    const z1 = -x * sy + z * cyw;
    const y1 = y * ct - z1 * st;
    const z2 = y * st + z1 * ct;
    return [cx + x1 * scale, cy - y1 * scale, z2];
  };
}
function inkColor(w, alpha, dark, tint) {
  if (!tint) {
    const g = Math.round((dark ? 1 - w : w) * 255);
    return `rgba(${g},${g},${g},${alpha})`;
  }
  const ramp = (c) => Math.round(dark ? c * (1 - w) : c + (255 - c) * w);
  return `rgba(${ramp(tint.r)},${ramp(tint.g)},${ramp(tint.b)},${alpha})`;
}
function paint(ctx, dots, dark, rMin = 0.3, tint) {
  for (const d of dots) {
    const alpha = d.a ?? 1;
    const w = Math.min(1, Math.max(0, d.white));
    ctx.fillStyle = inkColor(w, alpha, dark, tint);
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
    ctx.fill();
  }
}
function paintLines(ctx, lines, dark, tint) {
  for (const l of lines) {
    const alpha = l.a ?? 1;
    const w = Math.min(1, Math.max(0, l.white));
    ctx.strokeStyle = inkColor(w, alpha, dark, tint);
    ctx.lineWidth = l.w;
    ctx.beginPath();
    ctx.moveTo(l.x1, l.y1);
    ctx.lineTo(l.x2, l.y2);
    ctx.stroke();
  }
}
function finalizeFrame(dots, lines, rMin = 0.3) {
  const visible = [];
  for (const d of dots) {
    if ((d.a ?? 1) < 0.02) continue;
    d.r = Math.max(rMin, d.r);
    visible.push(d);
  }
  visible.sort((a, b) => a.z - b.z);
  return { dots: visible, lines: lines.filter((l) => (l.a ?? 1) >= 0.02) };
}
function paintFrame(ctx, frame, dark, tint) {
  if (frame.lines.length) paintLines(ctx, frame.lines, dark, tint);
  paint(ctx, frame.dots, dark, 0.3, tint);
}
function radiusScale(size, pow) {
  return (size / 300) ** pow;
}
const COUNT_PAIRS = [
  ["latRings", "lonDensity"],
  ["rings", "lonDensity"],
  ["lanes", "segs"]
];
const COUNT_KEYS = ["orbitN", "ghostN", "nodeN", "strandN", "signals"];
const ICON_DENSITY_KEYS = ["iconD"];
const RADIUS_KEYS = [
  "rBase",
  "rDepth",
  "rActive",
  "rDot",
  "ghostR",
  "partR",
  "partRDepth",
  "nodeR",
  "nodeRDepth"
];
function scaleCounts(opts, scale) {
  const out = { ...opts };
  const done = /* @__PURE__ */ new Set();
  const rt = Math.sqrt(scale);
  for (const [a, b] of COUNT_PAIRS) {
    const va = out[a];
    const vb = out[b];
    if (va != null && vb != null && !done.has(a) && !done.has(b)) {
      out[a] = Math.max(2, Math.round(va * rt));
      out[b] = Math.max(2, Math.round(vb * rt));
      done.add(a);
      done.add(b);
    }
  }
  for (const k of COUNT_KEYS) {
    const v = out[k];
    if (v != null && v !== 0 && !done.has(k)) out[k] = Math.max(1, Math.round(v * scale));
  }
  for (const k of ICON_DENSITY_KEYS) {
    const v = out[k];
    if (v != null) out[k] = Math.max(0.02, v * scale);
  }
  return out;
}
function scaleRadii(opts, scale) {
  const out = { ...opts };
  for (const k of RADIUS_KEYS) {
    const v = out[k];
    if (v != null) out[k] = v * scale;
  }
  out.rSizeMul = (out.rSizeMul ?? 1) * scale;
  return out;
}
const BASE_PROFILES = {
  globe: {
    latRings: 17,
    lonDensity: 44,
    rBase: 0.6,
    rDepth: 1.7,
    rBoost: 1,
    inkFar: 0.62,
    inkSpan: 0.54,
    rsPow: 0.6,
    rMin: 0.3
  },
  orbits: {
    orbitN: 12,
    ghostN: 40,
    ghostR: 0.9,
    ghostA: 0.5,
    particles: 3,
    partR: 1.2,
    partRDepth: 1.6,
    rsPow: 0.6,
    rMin: 0.3
  },
  rubik: {
    latRings: 15,
    lonDensity: 40,
    moveCount: 14,
    rBase: 0.6,
    rDepth: 1.7,
    rActive: 0.3,
    inkFar: 0.62,
    inkSpan: 0.54,
    rsPow: 0.6,
    rMin: 0.3
  },
  wave: {
    rings: 15,
    lonDensity: 40,
    rBase: 0.6,
    rDepth: 1.7,
    rsPow: 0.6,
    rMin: 0.3
  },
  web: {
    nodeN: 30,
    thr: 0.72,
    signals: 5,
    nodeR: 1.4,
    nodeRDepth: 1.8,
    lineW: 0.8,
    rsPow: 0.6,
    rMin: 0.3
  },
  braid: {
    strandN: 52,
    turns: 3,
    ghostN: 150,
    rBase: 1.2,
    rDepth: 1.8,
    rsPow: 0.6,
    rMin: 0.3
  },
  ribbon: {
    lanes: 5,
    segs: 88,
    ghostN: 150,
    rBase: 1.1,
    rDepth: 1.7,
    rsPow: 0.6,
    rMin: 0.3
  },
  // ring shares ribbon's painter; faceOn cancels the camera tilt and moves
  // the undulation onto the radius, and there is no ghost sphere behind it
  ring: {
    lanes: 5,
    segs: 88,
    ghostN: 0,
    faceOn: 1,
    rBase: 1.1,
    rDepth: 1.7,
    rsPow: 0.6,
    rMin: 0.3
  },
  morph: {
    rDot: 0.021,
    iconD: 1,
    rMin: 0.25
  }
};
const frameBraid = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.76;
  const pt = makeProj(t * 0.4, 0.3, cx, cy, 1);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const dots = [];
  const ghostN = o.ghostN ?? 150;
  for (let i = 0; i < ghostN; i++) {
    const d = fibDir(i, ghostN);
    const [px, py, z] = pt(d[0] * R, d[1] * R, d[2] * R);
    const depth = (z / R + 1) / 2;
    dots.push({ x: px, y: py, z, r: 0.8 * rs, white: 0.78, a: 0.1 + 0.22 * depth });
  }
  const strandN = o.strandN ?? 52;
  const turns = o.turns ?? 3;
  for (let s = 0; s < 3; s++) {
    const phase = s / 3 * 2 * Math.PI;
    for (let i = 0; i < strandN; i++) {
      const u = (frac(i / strandN + t * 0.045) * 2 - 1) * 0.96;
      const surf = Math.sqrt(Math.max(0, 1 - u * u));
      const endFade = Math.min(1, (1 - Math.abs(u)) / 0.1);
      const a = u * Math.PI * turns + phase;
      const weave = 1 + 0.075 * Math.sin(u * Math.PI * turns * 2 + phase * 2 + t * 0.8);
      const rr = surf * R * weave;
      const [px, py, zr] = pt(Math.cos(a) * rr, u * R * weave, Math.sin(a) * rr);
      const depth = (zr / R + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z: zr,
        r: ((o.rBase ?? 1.2) + (o.rDepth ?? 1.8) * depth) * rs,
        white: 0.55 - 0.45 * depth,
        a: endFade * (0.45 + 0.55 * depth)
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
function solveCycle(time, count, slotDur, rest) {
  const cyc = 2 * count * slotDur + rest;
  const tc = time % cyc;
  const amount = new Array(count).fill(0);
  let active = -1;
  if (tc < 2 * count * slotDur) {
    const slot = Math.floor(tc / slotDur);
    const p = (tc - slot * slotDur) / slotDur;
    const cl = Math.min(1, p / 0.7);
    const ep = 1 - (1 - cl) ** 3;
    if (slot < count) {
      for (let i = 0; i < slot; i++) amount[i] = 1;
      amount[slot] = ep;
      active = slot;
    } else {
      const u = 2 * count - 1 - slot;
      for (let i = 0; i < u; i++) amount[i] = 1;
      amount[u] = 1 - ep;
      active = u;
    }
  }
  return { amount, active };
}
function applyMoves(pt3, moves, sc) {
  let [x, y, z] = pt3;
  let inActive = false;
  for (let i = 0; i < moves.length; i++) {
    if (sc.amount[i] <= 0) continue;
    const mv = moves[i];
    const coord = mv.axis === 0 ? x : mv.axis === 1 ? y : z;
    if (coord < mv.lo || coord >= mv.hi) continue;
    if (i === sc.active) inActive = true;
    const a = mv.ang * sc.amount[i];
    const ca = Math.cos(a);
    const sa = Math.sin(a);
    if (mv.axis === 0) {
      const y2 = y * ca - z * sa;
      z = y * sa + z * ca;
      y = y2;
    } else if (mv.axis === 1) {
      const x2 = x * ca + z * sa;
      z = -x * sa + z * ca;
      x = x2;
    } else {
      const x2 = x * ca - y * sa;
      y = x * sa + y * ca;
      x = x2;
    }
  }
  return [x, y, z, inActive];
}
function makeMoves(count) {
  const moves = [];
  for (let i = 0; i < count; i++) {
    const axis = Math.min(2, Math.floor(hashD(i, 2.3) * 3));
    const lo = -1 + 0.5 * Math.min(3, Math.floor(hashD(i, 5.9) * 4));
    const dir = hashD(i, 7.7) < 0.5 ? 1 : -1;
    moves.push({ axis, lo, hi: lo + 0.5, ang: dir * Math.PI / 2 });
  }
  return moves;
}
const frameGlobe = (size, t, o) => {
  const spin = 0.5;
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 * 0.82;
  const tilt = 0.4 + 0.06 * Math.sin(t * 0.35);
  const pt = makeProj(t * spin, tilt, cx, cy, radius);
  const scan = t * (spin + (1.7 - spin) * (o.scanMul ?? 1));
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const dimBase = o.dimBase ?? 1;
  const dots = [];
  const latRings = o.latRings ?? 17;
  const lonDensity = o.lonDensity ?? 44;
  for (let li = 0; li <= latRings; li++) {
    const lat = -Math.PI / 2 + li / latRings * Math.PI;
    const cosLat = Math.cos(lat);
    const sinLat = Math.sin(lat);
    const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
    for (let lj = 0; lj < lonCount; lj++) {
      const lon = lj / lonCount * 2 * Math.PI;
      const [px, py, z] = pt(cosLat * Math.cos(lon), sinLat, cosLat * Math.sin(lon));
      const depth = (z + 1) / 2;
      const d = angleDelta(lon + t * spin, scan);
      const boost = Math.exp(-(d * d) / 0.18) * Math.max(0, z);
      dots.push({
        x: px,
        y: py,
        z,
        r: ((o.rBase ?? 0.6) + (o.rDepth ?? 1.7) * depth + (o.rBoost ?? 1) * boost) * rs,
        white: (o.inkFar ?? 0.62) - (o.inkSpan ?? 0.54) * depth,
        // dimBase < 1 fades un-scanned dots so the meridian reads clearly
        a: dimBase + (1 - dimBase) * Math.min(1, boost)
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
const frameRubik = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.82;
  const pt = makeProj(t * 0.55, 0.35 + 0.1 * Math.sin(t * 0.9), cx, cy, R);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const moveCount = o.moveCount ?? 14;
  const moves = makeMoves(moveCount);
  const sc = solveCycle(t, moveCount, 0.42, 1.2);
  const dots = [];
  const latRings = o.latRings ?? 15;
  const lonDensity = o.lonDensity ?? 40;
  for (let li = 0; li <= latRings; li++) {
    const lat = -Math.PI / 2 + li / latRings * Math.PI;
    const cosLat = Math.cos(lat);
    const sinLat = Math.sin(lat);
    const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
    for (let lj = 0; lj < lonCount; lj++) {
      const lon = lj / lonCount * 2 * Math.PI;
      const [x, y, z, inActive] = applyMoves([cosLat * Math.cos(lon), sinLat, cosLat * Math.sin(lon)], moves, sc);
      const [px, py, zr] = pt(x, y, z);
      const depth = (zr + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z: zr,
        r: ((o.rBase ?? 0.6) + (o.rDepth ?? 1.7) * depth + (inActive ? o.rActive ?? 0.3 : 0)) * rs,
        white: (o.inkFar ?? 0.62) - (o.inkSpan ?? 0.54) * depth - (inActive ? 0.14 : 0)
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
const frameWave = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.874;
  const pt = makeProj(t * 0.18, 0.38, cx, cy, 1);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const dots = [];
  const rings = o.rings ?? 15;
  const lonDensity = o.lonDensity ?? 40;
  for (let ri = 0; ri <= rings; ri++) {
    const lat = -Math.PI / 2 + ri / rings * Math.PI;
    const cosLat = Math.cos(lat);
    const sinLat = Math.sin(lat);
    const w = 0.62 * Math.sin(t * 2.1 - ri * 0.52) + 0.38 * Math.sin(t * 1.27 + ri * 0.83);
    const rr = R * (0.88 + 0.105 * w);
    const lonCount = Math.max(1, Math.round(Math.abs(cosLat) * lonDensity));
    for (let lj = 0; lj < lonCount; lj++) {
      const lon = lj / lonCount * 2 * Math.PI;
      const [px, py, z] = pt(cosLat * Math.cos(lon) * rr, sinLat * rr, cosLat * Math.sin(lon) * rr);
      const depth = (z / R + 1) / 2;
      const crest = Math.max(0, w);
      dots.push({
        x: px,
        y: py,
        z,
        r: ((o.rBase ?? 0.6) + (o.rDepth ?? 1.7) * depth) * (1 + 0.4 * crest) * rs,
        white: 0.66 - 0.56 * depth - 0.1 * crest
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
function smoothE(x) {
  return x * x * (3 - 2 * x);
}
function polyPath(verts) {
  const V = verts.length;
  const L = [];
  let total = 0;
  for (let i = 0; i < V; i++) {
    const a = verts[i];
    const b = verts[(i + 1) % V];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
    L.push(l);
    total += l;
  }
  return (f) => {
    let target = f * total;
    let i = 0;
    while (target > L[i] && i < V - 1) {
      target -= L[i];
      i++;
    }
    const a = verts[i];
    const b = verts[(i + 1) % V];
    const ff = L[i] ? Math.min(1, target / L[i]) : 0;
    return [a[0] + (b[0] - a[0]) * ff, a[1] + (b[1] - a[1]) * ff];
  };
}
const CIRCLE = (f) => {
  const a = -Math.PI / 2 + f * 2 * Math.PI;
  return [Math.cos(a) * 0.24, Math.sin(a) * 0.24];
};
const TRIANGLE = polyPath([
  [0, -0.26],
  [0.24, 0.16],
  [-0.24, 0.16]
]);
const SQUARE = polyPath([
  [0, -0.2],
  [0.2, -0.2],
  [0.2, 0.2],
  [-0.2, 0.2],
  [-0.2, -0.2]
]);
const CYCLE = [CIRCLE, TRIANGLE, SQUARE];
function morphN(d) {
  return Math.max(6, Math.round(34 * d));
}
const HOLD = 1.4;
const MORPH = 0.9;
const SEG = HOLD + MORPH;
const frameMorph = (size, t, o) => {
  const K = CYCLE.length;
  const tc = t % (SEG * K);
  const held = o.shape != null && o.shape >= 0 && o.shape < K ? Math.floor(o.shape) : -1;
  const k = held >= 0 ? held : Math.floor(tc / SEG);
  const local = held >= 0 ? t % SEG : tc - k * SEG;
  const m = held >= 0 ? 0 : local > HOLD ? smoothE((local - HOLD) / MORPH) : 0;
  const sprd = o.spread ?? 1;
  const pA = CYCLE[k];
  const pB = held >= 0 ? pA : CYCLE[(k + 1) % K];
  const M = 160;
  const pts = [];
  for (let i = 0; i < M; i++) {
    const f = i / M;
    const a = pA(f);
    const b = pB(f);
    pts.push([(a[0] + (b[0] - a[0]) * m) * sprd, (a[1] + (b[1] - a[1]) * m) * sprd]);
  }
  const L = [];
  let total = 0;
  for (let i = 0; i < M; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % M];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
    L.push(l);
    total += l;
  }
  const n = morphN(o.iconD ?? 1);
  const re = (o.rDot ?? 0.021) * 1.35 * sprd;
  const pulse = 1 + 0.02 * Math.sin(local * 3.1);
  const dots = [];
  const c2 = size / 2;
  let seg = 0;
  let acc = 0;
  for (let k2 = 0; k2 < n; k2++) {
    const target = k2 / n * total;
    while (acc + L[seg] < target && seg < M - 1) {
      acc += L[seg];
      seg++;
    }
    const a = pts[seg];
    const b = pts[(seg + 1) % M];
    const f = L[seg] ? Math.min(1, (target - acc) / L[seg]) : 0;
    const x = (a[0] + (b[0] - a[0]) * f) * pulse;
    const y = (a[1] + (b[1] - a[1]) * f) * pulse;
    dots.push({
      x: c2 + x * size,
      y: c2 + y * size,
      z: 0,
      r: Math.max(0.35, re * size),
      white: 0.1
    });
  }
  return finalizeFrame(dots, [], o.rMin);
};
const frameOrbits = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.82;
  const pt = makeProj(t * 0.12, 0.3, cx, cy, 1);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const dots = [];
  const orbitN = o.orbitN ?? 12;
  const ghostN = o.ghostN ?? 40;
  const particles = o.particles ?? 3;
  for (let orb = 0; orb < orbitN; orb++) {
    const h1 = hashD(orb, 1.7);
    const h2 = hashD(orb, 5.2);
    const h3 = hashD(orb, 8.9);
    const ro = R * (0.45 + 0.52 * h1);
    const th = h1 * 2 * Math.PI;
    const phi = Math.acos(2 * h2 - 1);
    const nx = Math.sin(phi) * Math.cos(th);
    const ny = Math.cos(phi);
    const nz = Math.sin(phi) * Math.sin(th);
    let ux = -ny;
    let uy = nx;
    const uz = 0;
    const ul = Math.max(1e-6, Math.sqrt(ux * ux + uy * uy));
    ux /= ul;
    uy /= ul;
    const vx = ny * uz - nz * uy;
    const vy = nz * ux - nx * uz;
    const vz = nx * uy - ny * ux;
    const speed = (0.25 + 0.55 * h3) * (h3 > 0.5 ? 1 : -1);
    for (let k = 0; k < ghostN; k++) {
      const a = k / ghostN * 2 * Math.PI;
      const [px, py, z] = pt(
        (ux * Math.cos(a) + vx * Math.sin(a)) * ro,
        (uy * Math.cos(a) + vy * Math.sin(a)) * ro,
        (uz * Math.cos(a) + vz * Math.sin(a)) * ro
      );
      const depth = (z / ro + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z,
        r: (o.ghostR ?? 0.9) * rs,
        white: 0.72,
        a: (o.ghostA ?? 0.5) * (0.4 + 0.6 * depth)
      });
    }
    for (let m = 0; m < particles; m++) {
      const a = t * speed + m / particles * 2 * Math.PI + h2 * 6;
      const [px, py, z] = pt(
        (ux * Math.cos(a) + vx * Math.sin(a)) * ro,
        (uy * Math.cos(a) + vy * Math.sin(a)) * ro,
        (uz * Math.cos(a) + vz * Math.sin(a)) * ro
      );
      const depth = (z / ro + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z,
        r: ((o.partR ?? 1.2) + (o.partRDepth ?? 1.6) * depth) * rs,
        white: 0.3 - 0.22 * depth
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
const frameRibbon = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.78;
  const spin = o.spin ?? 1;
  const camTilt = 0.3;
  const pt = makeProj(t * 0.1 * spin, camTilt, cx, cy, 1);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const dots = [];
  const ghostN = o.ghostN ?? 150;
  for (let i = 0; i < ghostN; i++) {
    const d = fibDir(i, ghostN);
    const [px, py, z] = pt(d[0] * R, d[1] * R, d[2] * R);
    const depth = (z / R + 1) / 2;
    dots.push({ x: px, y: py, z, r: 0.8 * rs, white: 0.78, a: 0.1 + 0.22 * depth });
  }
  const ya = t * 0.24 * spin;
  const ta = o.faceOn ? -camTilt : 0.55 + 0.3 * Math.sin(t * 0.18) * spin;
  const ux = Math.cos(ya);
  const uy = 0;
  const uz = Math.sin(ya);
  const vx = -uz * Math.sin(ta);
  const vy = Math.cos(ta);
  const vz = ux * Math.sin(ta);
  const nx = uy * vz - uz * vy;
  const ny = uz * vx - ux * vz;
  const nz = ux * vy - uy * vx;
  const wobAmp = 0.23 * (o.wobMul ?? 1);
  const baseR = o.faceOn ? R / (1 + 0.85 * wobAmp) : R;
  const baseLanes = o.lanes ?? 5;
  const segs = o.segs ?? 88;
  const lanes = Math.max(1, Math.round(baseLanes * (o.bandMul ?? 1)));
  for (let w = 0; w < lanes; w++) {
    const laneOff = (w - (lanes - 1) / 2) * 0.075;
    const edge = Math.abs(w - (lanes - 1) / 2) / Math.max(1, (lanes - 1) / 2);
    for (let k = 0; k < segs; k++) {
      const a = k / segs * 2 * Math.PI;
      const wob = (0.16 * Math.sin(a * 3 - t * 1.7 + w * 0.22) + 0.07 * Math.sin(a * 5 + t * 1.1)) * (o.wobMul ?? 1);
      const radial = o.faceOn ? 1 + wob : 1;
      const off = o.faceOn ? laneOff : laneOff + wob;
      const x = ux * Math.cos(a) + vx * Math.sin(a) + nx * off;
      const y = uy * Math.cos(a) + vy * Math.sin(a) + ny * off;
      const z = uz * Math.cos(a) + vz * Math.sin(a) + nz * off;
      const l = Math.sqrt(x * x + y * y + z * z);
      const rr = baseR * radial;
      const [px, py, zr] = pt(x / l * rr, y / l * rr, z / l * rr);
      const depth = (zr / R + 1) / 2;
      dots.push({
        x: px,
        y: py,
        z: zr,
        r: ((o.rBase ?? 1.1) + (o.rDepth ?? 1.7) * depth) * (1 - 0.25 * edge) * rs,
        white: 0.52 - 0.44 * depth + 0.18 * edge,
        a: 0.4 + 0.6 * depth
      });
    }
  }
  return finalizeFrame(dots, [], o.rMin);
};
const frameWeb = (size, t, o) => {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 * 0.8 * (o.spread ?? 1);
  const pt = makeProj(t * 0.12, 0.32, cx, cy, R);
  const rs = radiusScale(size, o.rsPow ?? 0.6);
  const nodeN = o.nodeN ?? 30;
  const thr = o.thr ?? 0.72;
  const nodeR = o.nodeR ?? 1.4;
  const nodeRDepth = o.nodeRDepth ?? 1.8;
  const nodes = [];
  for (let i = 0; i < nodeN; i++) {
    const d = fibDir(i, nodeN);
    const x = d[0] + 0.3 * (vnoise(i * 0.31 + 9, t * 0.24) - 0.5) * 2;
    const y = d[1] + 0.3 * (vnoise(i * 0.53 + 27, t * 0.21) - 0.5) * 2;
    const z = d[2] + 0.3 * (vnoise(i * 0.77 + 55, t * 0.27) - 0.5) * 2;
    const l = Math.sqrt(x * x + y * y + z * z);
    nodes.push([x / l, y / l, z / l]);
  }
  const lines = [];
  const dots = [];
  for (let i = 0; i < nodeN; i++) {
    for (let j = i + 1; j < nodeN; j++) {
      const dx = nodes[i][0] - nodes[j][0];
      const dy = nodes[i][1] - nodes[j][1];
      const dz = nodes[i][2] - nodes[j][2];
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist >= thr) continue;
      const [x1, y1, z1] = pt(nodes[i][0], nodes[i][1], nodes[i][2]);
      const [x2, y2, z2] = pt(nodes[j][0], nodes[j][1], nodes[j][2]);
      const depth = ((z1 + z2) / 2 + 1) / 2;
      lines.push({
        x1,
        y1,
        x2,
        y2,
        white: 0.42,
        a: (1 - dist / thr) * (0.3 + 0.55 * depth),
        w: Math.max(0.6, (o.lineW ?? 0.8) * rs)
      });
    }
  }
  for (let i = 0; i < nodeN; i++) {
    const [px, py, z] = pt(nodes[i][0], nodes[i][1], nodes[i][2]);
    const depth = (z + 1) / 2;
    const pulse = 1 + 0.25 * Math.sin(t * 1.4 + i * 2.7);
    dots.push({
      x: px,
      y: py,
      z,
      r: (nodeR + nodeRDepth * depth) * pulse * rs,
      white: 0.55 - 0.45 * depth
    });
  }
  const signals = o.signals ?? 5;
  for (let s = 0; s < signals; s++) {
    const seg = Math.floor(t * 0.55 + s * 7.31);
    const a = Math.floor(hashD(seg, s * 3.1 + 1.7) * nodeN);
    const b = Math.floor(hashD(seg, s * 5.7 + 4.2) * nodeN);
    if (a === b) continue;
    const f = frac(t * 0.55 + s * 7.31);
    const x = lerp(nodes[a][0], nodes[b][0], f);
    const y = lerp(nodes[a][1], nodes[b][1], f);
    const z = lerp(nodes[a][2], nodes[b][2], f);
    const l = Math.max(1e-6, Math.sqrt(x * x + y * y + z * z));
    const [px, py, zr] = pt(x / l, y / l, z / l);
    const depth = (zr + 1) / 2;
    dots.push({
      x: px,
      y: py,
      z: zr,
      r: (nodeR * 1.5 + nodeRDepth * depth) * rs,
      white: 0.05,
      a: 0.5 + 0.5 * depth
    });
  }
  return finalizeFrame(dots, lines, o.rMin);
};
const MODE_FRAMES = {
  orbits: frameOrbits,
  globe: frameGlobe,
  rubik: frameRubik,
  wave: frameWave,
  web: frameWeb,
  braid: frameBraid,
  ribbon: frameRibbon,
  // ring shares ribbon's geometry — the `faceOn` profile flag switches it
  ring: frameRibbon,
  morph: frameMorph
};
const MODE_DRAWS = Object.fromEntries(
  Object.entries(MODE_FRAMES).map(([key, frame]) => [
    key,
    (ctx, size, t, dark, opts) => paintFrame(ctx, frame(size, t, opts), dark)
  ])
);
const STATE_TO_MODE = {
  working: "orbits",
  searching: "globe",
  solving: "rubik",
  listening: "wave",
  connecting: "web",
  weaving: "braid",
  composing: "ribbon",
  breathing: "ring",
  shaping: "morph"
};
const PRESETS = {
  orbits: {
    64: { speed: 1.885, count: 1, size: 1 },
    32: { speed: 2.9072, count: 0.4251, size: 1.6849 },
    20: { speed: 3.9, count: 0.238, size: 2.4 }
  },
  globe: {
    64: { speed: 2.015, count: 0.42, size: 1.15, extra: { scanMul: 4.08, dimBase: 0.45 } },
    32: { speed: 2.3803, count: 0.1839, size: 1.4769, extra: { scanMul: 4.2301, dimBase: 0.45 } },
    20: { speed: 2.665, count: 0.105, size: 1.75, extra: { scanMul: 4.335, dimBase: 0.45 } }
  },
  rubik: {
    64: { speed: 1.82, count: 0.35, size: 1.05 },
    32: { speed: 1.8964, count: 0.1537, size: 1.4951 },
    20: { speed: 1.95, count: 0.088, size: 1.9 }
  },
  wave: {
    64: { speed: 4.388, count: 0.341, size: 1 },
    32: { speed: 4.1512, count: 0.169, size: 1.3232 },
    20: { speed: 3.998, count: 0.105, size: 1.6 }
  },
  web: {
    64: { speed: 3.315, count: 1.35, size: 0.95 },
    32: { speed: 5.0104, count: 0.4942, size: 1.2571 },
    20: { speed: 6.63, count: 0.25, size: 1.52 }
  },
  braid: {
    64: { speed: 1.625, count: 0.5, size: 1 },
    32: { speed: 2.2234, count: 0.2056, size: 1.2011 },
    20: { speed: 2.75, count: 0.1125, size: 1.36 }
  },
  ribbon: {
    64: { speed: 2.34, count: 0.25, size: 0.85, extra: { spin: 0, bandMul: 3.9, wobMul: 1 } },
    32: { speed: 2.7776, count: 0.0969, size: 0.9766, extra: { spin: 0, bandMul: 4.49, wobMul: 1 } },
    20: { speed: 3.12, count: 0.051, size: 1.073, extra: { spin: 0, bandMul: 4.94, wobMul: 1 } }
  },
  ring: {
    64: { speed: 3.24, count: 0.25, size: 0.956, extra: { spin: 0, bandMul: 3.627, wobMul: 0.368 } },
    32: { speed: 3.5517, count: 0.0678, size: 1.31, extra: { spin: 0, bandMul: 3.8265, wobMul: 0.4751 } },
    20: { speed: 3.78, count: 0.028, size: 1.622, extra: { spin: 0, bandMul: 3.968, wobMul: 0.565 } }
  },
  morph: {
    64: { speed: 2.405, count: 0.702, size: 0.395, extra: { spread: 1.45 } },
    32: { speed: 2.2057, count: 0.5937, size: 0.6916, extra: { spread: 1.45 } },
    20: { speed: 2.08, count: 0.53, size: 1.011, extra: { spread: 1.45 } }
  }
};
const cache = /* @__PURE__ */ new Map();
function resolvePreset(state, size) {
  const key = `${state}-${size}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const mode = STATE_TO_MODE[state];
  const preset = PRESETS[mode][size];
  let opts = { ...BASE_PROFILES[mode] };
  if (preset.count !== 1) opts = scaleCounts(opts, preset.count);
  if (preset.size !== 1) opts = scaleRadii(opts, preset.size);
  if (preset.extra) opts = { ...opts, ...preset.extra };
  const resolved = { mode, speed: preset.speed, opts };
  cache.set(key, resolved);
  return resolved;
}
export { MODE_FRAMES as M, paintFrame as p, resolvePreset as r };

// ── Atticus, not part of the thinking-orbs engine: Markdown and TeX math for every answer (the box, its agent card, the Agent view and shelf) ──
// TeX → MathML, drawn by WebKit's own math layout: the subset short answers use. Anything else throws and shows the source.
const MML = 'http://www.w3.org/1998/Math/MathML';
const MI = {alpha:'α',beta:'β',gamma:'γ',delta:'δ',epsilon:'ϵ',varepsilon:'ε',zeta:'ζ',eta:'η',theta:'θ',vartheta:'ϑ',iota:'ι',kappa:'κ',lambda:'λ',mu:'μ',nu:'ν',xi:'ξ',pi:'π',rho:'ρ',sigma:'σ',tau:'τ',upsilon:'υ',phi:'ϕ',varphi:'φ',chi:'χ',psi:'ψ',omega:'ω',
  Gamma:'Γ',Delta:'Δ',Theta:'Θ',Lambda:'Λ',Xi:'Ξ',Pi:'Π',Sigma:'Σ',Phi:'Φ',Psi:'Ψ',Omega:'Ω',infty:'∞',partial:'∂',nabla:'∇',emptyset:'∅',varnothing:'∅',ell:'ℓ',hbar:'ℏ',R:'ℝ',N:'ℕ',Z:'ℤ',Q:'ℚ',C:'ℂ'};
const MO = {cdot:'⋅',times:'×',div:'÷',pm:'±',mp:'∓',le:'≤',leq:'≤',ge:'≥',geq:'≥',ne:'≠',neq:'≠',approx:'≈',equiv:'≡',sim:'∼',cong:'≅',propto:'∝',to:'→',rightarrow:'→',leftarrow:'←',Rightarrow:'⇒',implies:'⇒',
  Leftrightarrow:'⇔',iff:'⇔',mapsto:'↦',in:'∈',notin:'∉',subset:'⊂',subseteq:'⊆',cup:'∪',cap:'∩',setminus:'∖',forall:'∀',exists:'∃',angle:'∠',circ:'∘',degree:'°',cdots:'⋯',ldots:'…',dots:'…',perp:'⊥',parallel:'∥',
  neg:'¬',land:'∧',lor:'∨',mid:'∣',prime:'′',therefore:'∴',langle:'⟨',rangle:'⟩',lfloor:'⌊',rfloor:'⌋',lceil:'⌈',rceil:'⌉',int:'∫',iint:'∬',oint:'∮','{':'{','}':'}','|':'‖','%':'%','$':'$','#':'#','&':'&','_':'_'};
const BIG = {sum:'∑',prod:'∏',lim:'lim',max:'max',min:'min',sup:'sup',inf:'inf',bigcup:'⋃',bigcap:'⋂'};   // limits go under and over in display math
const SPACE = {',':'.17em',':':'.22em',';':'.28em','!':'-.17em',' ':'.25em',quad:'1em',qquad:'2em'};
const ACCENT = {overline:'‾',bar:'‾',vec:'→',overrightarrow:'→',hat:'^',widehat:'^',tilde:'~',widetilde:'~',dot:'˙',ddot:'¨'};
const FN = /^(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|log|ln|lg|exp|det|gcd|deg|arg|dim|ker)$/;
const ENV = {pmatrix:['(',')'],bmatrix:['[',']'],Bmatrix:['{','}'],vmatrix:['|','|'],matrix:['',''],cases:['{',''],aligned:['',''],align:['',''],'align*':['',''],gathered:['',''],array:['','']};
const tex = (src, block) => {
  if (src.length > 3000) throw Error('long');
  const found = [...src.matchAll(/\\[a-zA-Z]+\*?|\\.|\d+(?:\.\d+)?|\S/g)], t = found.map(m => m[0]), at = found.map(m => m.index);
  let i = 0;
  const fail = () => { throw Error('tex'); };
  const node = (tag, kids = [], attrs = {}) => { const n = document.createElementNS(MML, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); n.append(...kids); return n; };
  const leaf = (tag, s, attrs) => node(tag, [s], attrs);
  const row = kids => kids.length === 1 ? kids[0] : node('mrow', kids);
  const fence = d => leaf('mo', d, {fence: 'true', stretchy: 'true'});
  const delim = () => { const d = t[i++] ?? fail(); return d === '.' ? '' : d[0] === '\\' ? MO[d.slice(1)] ?? fail() : d; };
  const raw = () => {   // \text{…}: the source as written, spaces kept
    if (t[i] !== '{') fail();
    let depth = 0, j = i;
    do { depth += t[j] === '{' ? 1 : t[j] === '}' ? -1 : 0; j++; } while (depth && j < t.length);
    if (depth) fail();
    const s = src.slice(at[i] + 1, at[j - 1]); i = j; return s.replace(/\\(.)/g, '$1');
  };
  const expr = stop => { const kids = []; while (i < t.length && !stop.includes(t[i])) kids.push(scripts()); return row(kids); };
  const group = () => { if (t[i] !== '{') return atom(true); i++; const g = expr(['}']); if (t[i++] !== '}') fail(); return g; };
  const atom = arg => {
    const s = t[i++];
    if (s === undefined || s === '}' || s === '&') fail();
    if (s === '{') { i--; return group(); }
    if (/^\d/.test(s)) { if (arg && s.length > 1) { t[--i] = s.slice(1); at[i]++; return leaf('mn', s[0]); } return leaf('mn', s); }   // \frac12: one digit each
    if (s[0] !== '\\') return /^[a-zA-Z]$/.test(s) ? leaf('mi', s) : leaf('mo', {'-': '−', '*': '∗', "'": '′'}[s] || s, /^[()[\]|]$/.test(s) ? {stretchy: 'false'} : undefined);   // only \left…\right grows
    const c = s.slice(1);
    if (/^[dtc]?frac$/.test(c)) return node('mfrac', [group(), group()]);
    if (c === 'binom') return row([leaf('mo', '('), node('mfrac', [group(), group()], {linethickness: '0'}), leaf('mo', ')')]);
    if (c === 'sqrt') { if (t[i] !== '[') return node('msqrt', [group()]); i++; const n = expr([']']); i++; return node('mroot', [group(), n]); }
    if (/^(text|textrm|textit|mbox)$/.test(c)) return leaf('mtext', raw());
    if (c === 'textbf') return leaf('mtext', raw(), {mathvariant: 'bold'});
    if (c === 'mathrm' || c === 'operatorname') return leaf('mi', raw(), {mathvariant: 'normal'});
    if (c === 'mathbb') { const s = raw(); return leaf('mi', MI[s] ?? fail()); }
    if (c === 'mathbf' || c === 'boldsymbol') { const g = group(); g.setAttribute('mathvariant', 'bold'); return g; }
    if (ACCENT[c]) return node('mover', [group(), leaf('mo', ACCENT[c], {stretchy: String(!/^(dot|ddot|hat|tilde|vec)$/.test(c))})], {accent: 'true'});
    if (c === 'underline') return node('munder', [group(), leaf('mo', '_', {stretchy: 'true'})], {accentunder: 'true'});
    if (c === 'boxed') return node('mrow', [group()], {style: 'border: 1px solid; padding: 3px 5px'});
    if (c === 'left') { const open = delim(), body = expr(['\\right']); if (t[i++] !== '\\right') fail(); return row([fence(open), body, fence(delim())]); }
    if (c === 'begin') {
      const env = raw(), [open, close] = ENV[env] ?? fail(), rows = [[]];
      if (env === 'array') raw();   // its column spec
      for (;;) {
        rows.at(-1).push(expr(['&', '\\\\', '\\end']));
        const sep = t[i++];
        if (sep === '\\\\') rows.push([]); else if (sep === '\\end') { raw(); break; } else if (sep !== '&') fail();
      }
      const align = /^align|aligned/.test(env) ? {columnalign: 'right left', columnspacing: '0'} : env === 'cases' ? {columnalign: 'left left'} : {};
      const table = node('mtable', rows.filter(r => r.some(c => c.childNodes.length || c.textContent)).map(r => node('mtr', r.map(c => node('mtd', [c])))), align);
      return row([open && fence(open), table, close && fence(close)].filter(Boolean));
    }
    if (c in SPACE) return node('mspace', [], {width: SPACE[c]});
    if (/^(displaystyle|textstyle|limits|nolimits|\\)$/.test(c)) return node('mrow');
    if (FN.test(c)) { const n = leaf('mi', c); n.fn = true; return n; }
    if (BIG[c]) { const n = leaf('mo', BIG[c], {movablelimits: 'true'}); n.big = true; return n; }
    if (MI[c]) return leaf('mi', MI[c]);
    if (MO[c]) return leaf('mo', MO[c], /^([{}|]|[lr](angle|vert|floor|ceil))$/.test(c) ? {stretchy: 'false'} : undefined);
    return fail();
  };
  const scripts = () => {
    const base = atom(); let sub = null, sup = null;
    for (;;) { if (t[i] === '_' && !sub) { i++; sub = group(); } else if (t[i] === '^' && !sup) { i++; sup = group(); } else break; }
    const r = sub && sup ? node(base.big ? 'munderover' : 'msubsup', [base, sub, sup]) : sub || sup ? node(base.big ? (sub ? 'munder' : 'mover') : (sub ? 'msub' : 'msup'), [base, sub || sup]) : base;
    return base.fn && t[i] && t[i] !== '(' ? row([r, node('mspace', [], {width: '0.1667em'})]) : r;   // \sin x: TeX's thin space after a function name
  };
  const body = expr([]);
  if (i < t.length) fail();
  const formula = node('math', [body], block ? {display: 'block'} : {displaystyle: 'true'});
  if (block) return formula;
  const box = el('span'); box.setAttribute('style', 'display: inline-block; padding-block: .15em'); box.append(formula);   // Reserve tall MathML's height and leading, even when prose line-height is smaller.
  return box;
};
const math = (src, block) => { try { return tex(src.trim(), block); } catch { return el('span', block ? 'tex block' : 'tex', src.trim()); } };   // unreadable TeX: show what the model wrote
// Plip explain.py (MIT, LICENSE-Plip): adapted bounded declarative input; its diagram/3D renderer has no plotter.
// Expressions are parsed as arithmetic, never executed as JavaScript.
const graphFunction = source => {
  if (typeof source !== 'string' || source.length > 160) throw Error('expression');
  const tokens = source.replace(/^\s*y\s*=/, '').match(/\d*\.?\d+(?:e[+-]?\d+)?|[a-z]+|[^\s]/gi) || [];
  let i = 0, depth = 0;
  const functions = {sin: Math.sin, cos: Math.cos, tan: Math.tan, sqrt: Math.sqrt, abs: Math.abs, log: Math.log, exp: Math.exp};
  const primary = () => {
    if (++depth > 32) throw Error('depth');
    const t = tokens[i++]; let f;
    if (t === '(') { f = sum(); if (tokens[i++] !== ')') throw Error('parenthesis'); }
    else if (t === 'x') f = x => x;
    else if (t === 'pi' || t === 'e') f = () => t === 'pi' ? Math.PI : Math.E;
    else if (Object.hasOwn(functions, t)) { if (tokens[i++] !== '(') throw Error('function'); const a = sum(); if (tokens[i++] !== ')') throw Error('function'); f = x => functions[t](a(x)); }
    else if (/^(?:\d*\.)?\d+(?:e[+-]?\d+)?$/i.test(t || '')) { const n = Number(t); if (!Number.isFinite(n)) throw Error('number'); f = () => n; }
    else throw Error('token');
    depth--; return f;
  };
  const power = () => { const a = primary(); if (tokens[i] !== '^') return a; i++; const b = unary(); return x => a(x) ** b(x); };
  const unary = () => { if (tokens[i] !== '+' && tokens[i] !== '-') return power(); const sign = tokens[i++]; const a = power(); return x => sign === '-' ? -a(x) : a(x); };
  const product = () => { let a = unary(); while (tokens[i] === '*' || tokens[i] === '/' || /^[\w.(]/.test(tokens[i] || '')) { const op = /^[*/]$/.test(tokens[i]) ? tokens[i++] : '*', left = a, b = unary(); a = x => op === '*' ? left(x) * b(x) : left(x) / b(x); } return a; };   // 2x is 2*x
  const sum = () => { let a = product(); while (tokens[i] === '+' || tokens[i] === '-') { const op = tokens[i++], left = a, b = product(); a = x => op === '+' ? left(x) + b(x) : left(x) - b(x); } return a; };
  const f = sum(); if (i !== tokens.length) throw Error('expression'); return f;
};
const graph = (source, expanded = false) => {
  try {
    if (source.length > 16000) throw Error('size');
    let spec = JSON.parse(source);
    const number = n => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e9;
    const short = spec && !spec.type && (spec.fn != null ? 'function' : ['bar', 'line', 'scatter'].find(k => Array.isArray(spec[k])));
    if (short) spec = {...spec, type: short, curves: [spec.fn].flat().map(fn => ({fn})), series: [{data: spec[short]}],   // the prompt's short form
      points: (spec.points || []).map(p => Array.isArray(p) ? {x: p[0], y: p[1], label: p[2]} : p)};
    const label = s => s == null ? '' : typeof s === 'string' && s.length <= 60 ? s : (() => { throw Error('label'); })();
    const range = r => { if (!Array.isArray(r) || r.length !== 2 || !r.every(number) || r[1] - r[0] < 1e-9) throw Error('range'); return r; };
    const pair = p => Array.isArray(p) && p.length === 2 && p.every(number);
    const type = spec.type, functionPlot = type === 'function';
    if (!['function', 'line', 'bar', 'scatter'].includes(type)) throw Error('type');
    const series = functionPlot ? spec.curves : spec.series;
    if (!Array.isArray(series) || !series.length || series.length > 4) throw Error('series');
    const points = spec.points || [];
    if (!Array.isArray(points) || points.length > 16 || !points.every(p => number(p?.x) && number(p.y) && (label(p.label), true))) throw Error('points');
    const pad = ([lo, hi], keepZero) => { const d = hi === lo ? Math.max(1, Math.abs(lo) * .1) : (hi - lo) * .1; return [keepZero && lo === 0 ? 0 : lo - d, hi + d]; };
    let xr = spec.x == null ? null : range(spec.x), yr = spec.y == null ? null : range(spec.y);
    if (functionPlot && !xr) xr = points.length ? [Math.min(...points.map(p => p.x)) - 5, Math.max(...points.map(p => p.x)) + 5] : [-10, 10];   // around the marked points
    const rows = series.map(s => {
      const name = label(s.label ?? (functionPlot && typeof s.fn === 'string' ? s.fn.slice(0, 60) : ''));
      if (functionPlot) {
        const f = graphFunction(s.fn), data = Array.from({length: 401}, (_, i) => { const x = xr[0] + (xr[1] - xr[0]) * i / 400; return [x, f(x)]; });
        return {name, data};
      }
      if (!Array.isArray(s.data) || !s.data.length || s.data.length > 256 || !s.data.every(pair)) throw Error('data');
      return {name, data: s.data};
    });
    if (functionPlot && !yr) {   // fitted to the curves, ignoring the outer 2% (asymptotes) of their samples
      const ys = rows.flatMap(r => r.data.map(p => p[1])).filter(y => Number.isFinite(y) && Math.abs(y) <= 1e9).sort((a, b) => a - b);
      if (!ys.length) throw Error('empty curve');
      const q = t => ys[Math.round((ys.length - 1) * t)], all = [q(.02), q(.98), ...points.map(p => p.y)];
      yr = pad([Math.min(...all), Math.max(...all)]);
    }
    if (functionPlot && rows.some(r => !r.data.some(p => Number.isFinite(p[1]) && p[1] >= yr[0] && p[1] <= yr[1]))) throw Error('empty curve');
    if (!functionPlot) {
      const data = rows.flatMap(r => r.data).concat(points.map(p => [p.x, p.y]));
      const extent = (index, zero) => pad([Math.min(...data.map(p => p[index]), ...(zero ? [0] : [])), Math.max(...data.map(p => p[index]), ...(zero ? [0] : []))], zero);
      xr ??= extent(0, false); yr ??= extent(1, type === 'bar');
    }
    const title = label(spec.title), box = el('div', expanded ? 'graph expanded' : 'graph'), heading = el('div', 'graph-title', title || 'Graph');
    box.dataset.spec = source; box.tabIndex = 0; box.setAttribute('role', 'button'); box.setAttribute('aria-expanded', expanded);
    box.setAttribute('aria-label', (title || 'Graph') + '. Click to expand; Escape to shrink.');
    box.append(heading);
    const svg = (tag, attrs = {}, text) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text != null) n.textContent = text; return n; };
    const height = expanded ? 360 : 240, bottom = height - 35, plotHeight = height - 50;
    const root = svg('svg', {viewBox: `0 0 440 ${height}`, role: 'img', 'aria-label': title || type + ' graph'});
    const X = x => 54 + (x - xr[0]) / (xr[1] - xr[0]) * 368, Y = y => bottom - (y - yr[0]) / (yr[1] - yr[0]) * plotHeight;
    const fmt = n => Number(n.toPrecision(4)).toString(), colors = ['#368de8', '#d98b25', '#b974d5', '#2eac87'];
    const ticks = ([lo, hi]) => {   // round steps (1, 2, 2.5, 5 × 10ⁿ), about five per axis
      const raw = (hi - lo) / 5, mag = 10 ** Math.floor(Math.log10(raw)), step = mag * ([1, 2, 2.5, 5, 10].find(s => s >= raw / mag - 1e-9) ?? 10);
      const out = []; for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9 && out.length < 12; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v); return out;
    };
    for (const x of ticks(xr)) root.append(svg('path', {d: `M${X(x)} 15V${bottom}`, stroke: 'currentColor', opacity: '.12'}), svg('text', {x: X(x), y: height - 16, 'text-anchor': 'middle'}, fmt(x)));
    for (const y of ticks(yr)) root.append(svg('path', {d: `M54 ${Y(y)}H422`, stroke: 'currentColor', opacity: '.12'}), svg('text', {x: 48, y: Y(y) + 4, 'text-anchor': 'end'}, fmt(y)));
    const clamp = (v, r) => Math.max(r[0], Math.min(r[1], v));
    root.append(svg('path', {d: `M${X(clamp(0, xr))} 15V${bottom} M54 ${Y(clamp(0, yr))}H422`, stroke: 'currentColor', opacity: '.5', fill: 'none'}));
    const lines = [[X(clamp(0, xr)), 15, X(clamp(0, xr)), bottom], [54, Y(clamp(0, yr)), 422, Y(clamp(0, yr))]], boxes = [];   // ink a point's label keeps off
    // Nested SVG clips curves/bars without document-global clip IDs (several answers may contain graphs).
    const plot = svg('svg', {x: 54, y: 15, width: 368, height: plotHeight, viewBox: `54 15 368 ${plotHeight}`, overflow: 'hidden'}), hover = [];
    rows.forEach((r, index) => {
      const color = colors[index]; let path = '', previous = null, previousX = 0;
      const uniqueX = [...new Set(r.data.map(p => p[0]))].sort((a, b) => a - b);
      const gap = uniqueX.length > 1 ? Math.min(...uniqueX.slice(1).map((x, i) => X(x) - X(uniqueX[i]))) : 70;
      const barWidth = Math.max(.5, Math.min(50, gap * .75) / rows.length);
      for (const [x, y] of r.data) {
        if (!Number.isFinite(y)) { previous = null; continue; }
        const px = X(x), py = Y(y);
        if (type !== 'bar' && x >= xr[0] && x <= xr[1] && y >= yr[0] && y <= yr[1]) hover.push({x, y, name: r.name, px, py});
        if (type === 'bar') {
          const left = px - barWidth * rows.length / 2 + index * barWidth, top = Math.min(py, Y(0)), bottom = Math.max(py, Y(0));
          plot.append(svg('rect', {x: left, y: top, width: barWidth, height: bottom - top, fill: color, opacity: '.85'})); boxes.push([left, top, left + barWidth, bottom]);
          hover.push({x, y, name: r.name, px: left + barWidth / 2, py, bar: [left, left + barWidth, top, bottom]});
        }
        else if (type === 'scatter') { plot.append(svg('circle', {cx: px, cy: py, r: 3, fill: color})); boxes.push([px - 3, py - 3, px + 3, py + 3]); }
        else {
          // shortcut: sampled curves break at large jumps; use adaptive sampling if finer asymptotes are needed.
          const join = previous !== null && (!functionPlot || Math.abs(py - previous) < plotHeight / 2), cy = Math.max(-10000, Math.min(10000, py));
          if (join) lines.push([previousX, Math.max(-10000, Math.min(10000, previous)), px, cy]);
          path += `${join ? 'L' : 'M'}${px.toFixed(2)} ${cy.toFixed(2)} `; previous = py; previousX = px;
        }
      }
      if (path) plot.append(svg('path', {d: path, stroke: color, 'stroke-width': 2, fill: 'none', 'stroke-linejoin': 'round'}));
      heading.append(el('span', '', r.name || `Series ${index + 1}`)); heading.lastChild.style.color = color;
    });
    const marks = points.map(p => {
      if (p.x < xr[0] || p.x > xr[1] || p.y < yr[0] || p.y > yr[1]) throw Error('point outside plot');
      const px = X(p.x), py = Y(p.y), name = label(p.label);
      plot.append(svg('circle', {cx: px, cy: py, r: 4, fill: 'currentColor'})); boxes.push([px - 4, py - 4, px + 4, py + 4]);
      hover.push({x: p.x, y: p.y, name, px, py}); return {px, py, name};
    });
    root.append(plot);
    // Plip draw.py (MIT): a label tries spots around its anchor, nearest first, and takes the first clear of ink and other labels.
    const cross = ([l, t, r, b], [x1, y1, x2, y2]) => {   // segment meets rect (Liang-Barsky)
      let lo = 0, hi = 1;
      for (const [p, q] of [[x1 - x2, x1 - l], [x2 - x1, r - x1], [y1 - y2, y1 - t], [y2 - y1, b - y1]]) { if (!p) { if (q < 0) return false; } else if (p < 0) lo = Math.max(lo, q / p); else hi = Math.min(hi, q / p); }
      return lo <= hi;
    };
    for (const {px, py, name} of marks.filter(m => m.name)) {
      const w = name.length * 6.5 + 4, h = 16; let best, cost = Infinity;
      spots: for (const reach of [6, 14, 26]) for (const [dx, dy] of [[0, -1], [0, 1], [.7, -.7], [-.7, -.7], [.7, .7], [-.7, .7], [1, 0], [-1, 0]]) {
        const cx = px + dx * reach + Math.sign(dx) * w / 2, cy = py + dy * reach + Math.sign(dy) * h / 2, r = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2];
        const c = (r[0] < 54 || r[2] > 422 || r[1] < 15 || r[3] > bottom ? 100 : 0) + lines.filter(s => cross(r, s)).length + boxes.filter(b => b[0] < r[2] && r[0] < b[2] && b[1] < r[3] && r[1] < b[3]).length;
        if (c < cost) { best = r; cost = c; }
        if (!c) break spots;
      }
      root.append(svg('text', {x: (best[0] + best[2]) / 2, y: best[3] - 4, 'text-anchor': 'middle'}, name)); boxes.push(best);
    }
    const tip = el('div', 'graph-tip'); tip.hidden = true; box.append(root, tip);
    box.graphHover = p => {
      if (!p) { tip.hidden = true; return; }
      const r = root.getBoundingClientRect(), scale = Math.min(r.width / 440, r.height / height);
      const x = (p[0] - r.x - (r.width - scale * 440) / 2) / scale, y = (p[1] - r.y - (r.height - scale * height) / 2) / scale;
      const hit = hover.find(p => p.bar && x >= p.bar[0] && x <= p.bar[1] && y >= p.bar[2] && y <= p.bar[3]);
      const nearest = hit || hover.reduce((a, b) => !a || Math.hypot(b.px - x, b.py - y) <= Math.hypot(a.px - x, a.py - y) ? b : a, null);
      tip.hidden = !nearest || x < 54 || x > 422 || y < 15 || y > bottom;
      if (!tip.hidden) tip.textContent = `${nearest.name ? nearest.name + ': ' : ''}(${fmt(nearest.x)}, ${fmt(nearest.y)})`;
    };
    box.onmousemove = e => box.graphHover([e.clientX, e.clientY]); box.onmouseleave = () => box.graphHover(null);
    box.onclick = () => { const next = graph(source, !expanded), focused = document.activeElement === box; box.replaceWith(next); if (focused) next.focus({preventScroll: true}); next.dispatchEvent(new Event('graphresize', {bubbles: true})); };
    box.onkeydown = e => { if (e.key === 'Escape' && box.classList.contains('expanded')) { e.preventDefault(); e.stopPropagation(); box.click(); } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); box.click(); } };
    return box;
  } catch { return el('pre', '', source); }
};
// Safe Markdown → DOM (no HTML from the model): headings, lists, rules, tables, bold, italics, code, links, $…$ and $$…$$ math
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const INLINE = /((?<!\\)\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?=\S)(?:\\.|[^$\\\n])+?(?<=\S)\$(?!\d)|\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((?:https?:|mailto:)[^\s)]+\)|https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"]|\*[^*\s][^*]*\*|(?<![\w\\])_[^_\s][^_]*_(?!\w))/g;
const inline = (parent, text) => {
  const plain = s => s.replace(/\\\$/g, '$').split('\n').forEach((l, k) => { if (k) parent.append(el('br')); if (l) parent.append(l); });   // a line break the model wrote stays one
  let at = 0;
  for (const m of text.matchAll(INLINE)) {
    plain(text.slice(at, m.index)); const s = m[0]; at = m.index + s.length;
    if (s.startsWith('$$') || s.startsWith('\\[')) parent.append(math(s.slice(2, -2), true));
    else if (s[0] === '$') parent.append(math(s.slice(1, -1)));
    else if (s.startsWith('\\(')) parent.append(math(s.slice(2, -2)));
    else if (s.startsWith('**')) inline(parent.appendChild(el('strong')), s.slice(2, -2));
    else if (s[0] === '`') parent.append(el('code', '', s.slice(1, -1)));
    else if (s[0] === '[') { const k = s.indexOf(']('), a = el('a', '', s.slice(1, k)); a.href = a.title = s.slice(k + 2, -1); parent.append(a); }
    else if (s.startsWith('http')) { const a = el('a', '', s); a.href = s; parent.append(a); }
    else inline(parent.appendChild(el('em')), s.slice(1, -1));
  }
  plain(text.slice(at)); return parent;
};
const markdown = (text, streaming = false, graphs = []) => {
  const out = document.createDocumentFragment(), lines = text.replace(/\r/g, '').split('\n'), item = /^\s*([-*•]|\d+[.)])\s+(.*)/;
  const row = /^\s*\|.*\|\s*$/, cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim()), isTable = i => row.test(lines[i]) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '');
  for (let i = 0, m; i < lines.length;) {
    if (!lines[i].trim()) { i++; continue; }
    if (/^\s*```/.test(lines[i])) {   // a fenced block keeps its lines (code, a small text drawing)
      const isGraph = /^\s*```graph\s*$/.test(lines[i]), code = []; while (++i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i]);
      const closed = i < lines.length; i++;
      const source = code.join('\n'), existing = isGraph && closed ? graphs.findIndex(g => g.dataset.spec === source) : -1;
      out.append(existing >= 0 ? graphs.splice(existing, 1)[0] : isGraph && closed ? graph(source) : isGraph && streaming ? el('div', 'graph pending', 'Graph on screen…') : el('pre', '', source)); continue;
    }
    if (isTable(i)) {
      const wrap = el('div', 'table'), table = wrap.appendChild(el('table')), head = table.appendChild(el('tr'));
      cells(lines[i]).forEach(c => head.append(inline(el('th'), c))); i += 2;
      while (i < lines.length && row.test(lines[i])) { const tr = table.appendChild(el('tr')); cells(lines[i++]).forEach(c => tr.append(inline(el('td'), c))); }
      out.append(wrap); continue;
    }
    if (/^\s*<details\b[^>]*>/i.test(lines[i])) {   // the model folds a spoiler: a real fold, its inside rendered as usual; still streaming, the rest stays inside
      const fold = []; let depth = 0;
      while (i < lines.length) { depth += (lines[i].match(/<details\b/gi) || []).length - (lines[i].match(/<\/details>/gi) || []).length; fold.push(lines[i++]); if (depth <= 0) break; }
      const [, summary, inside] = fold.join('\n').replace(/^\s*<details\b[^>]*>/i, '').replace(/<\/details>\s*$/i, '').match(/^\s*(?:<summary\b[^>]*>([\s\S]*?)<\/summary>)?([\s\S]*)$/i);
      const d = out.appendChild(el('details')); d.append(inline(el('summary'), summary?.trim() || 'Details'), markdown(inside, streaming, graphs)); continue;
    }
    if ((m = lines[i].match(/^\s*#{1,4}\s+(.*)/))) { out.append(inline(el('div', 'h'), m[1])); i++; continue; }
    if (/^\s*-{3,}\s*$/.test(lines[i])) { out.append(el('hr')); i++; continue; }
    if ((m = lines[i].match(item))) {
      const list = el(/\d/.test(m[1]) ? 'ol' : 'ul'); if (/\d/.test(m[1])) list.start = parseInt(m[1]);
      while (i < lines.length && (m = lines[i].match(item))) { list.append(inline(el('li'), m[2])); i++; }
      out.append(list); continue;
    }
    const para = []; while (i < lines.length && lines[i].trim() && !(para.length && (item.test(lines[i]) || /^\s*(#{1,4}\s|```|-{3,}\s*$|<details\b)/i.test(lines[i]) || isTable(i)))) para.push(lines[i++].trim());
    out.append(inline(el('p'), para.join('\n')));
  }
  return out;
};
const shut = s => {   // a streamed line waits at a **bold, `code, [link or $math that has not closed yet, so its marks never flash as symbols
  const k = s.lastIndexOf('\n') + 1, l = s.slice(k), b = s.replace(INLINE, m => ' '.repeat(m.length));   // its last word was cut, so a link still arriving is a [ with no ] yet; [1] or [ ] shows at once
  const open = [l.split('**').length % 2 ? -1 : l.lastIndexOf('**'), l.split('`').length % 2 ? -1 : l.lastIndexOf('`'), l.search(/\[[^\]]*$/),
    b.slice(k).search(/(?<!\\)\$(?![\d\s])/)].filter(i => i >= 0).map(i => k + i);   // b: closed math blanked; a $ before a digit is a price and shows at once
  const block = b.search(/(?<!\\)\$\$|\\[[(]/); if (block >= 0) open.push(block);   // $$, \[ or \( math still open, even lines back
  return !open.length || (s.match(/^\s*```/gm) || []).length % 2 ? s : s.slice(0, Math.min(...open));   // inside a code block every mark is text
};
export { MML, markdown, shut };
