/* Stage drafts: one engine, three worlds. Uses only what the bundled three build in ../crew exports,
   so any of these can move into gui/crew without a new dependency. */
const THEMES = {
  line: {
    view: { yaw: 0.44, pitch: 0.46 }, ink: '#141b26', brand: '#f0522a', ground: '#dfe4ea', grid: '#cdd4dc',
    s: { needs: '#ffb400', ready: '#f0522a', run: '#2a6df4', queued: '#9aa5b3', sent: '#9aa5b3', ok: '#1e9e63' },
  },
  orbit: {
    view: { yaw: 0.3, pitch: 0.72 }, ink: '#e9ecf7', brand: '#ffb347', sun: '#ffd596',
    s: { needs: '#ffb347', ready: '#ffffff', run: '#6fb6ff', queued: '#7f89b3', sent: '#b9a6ff', ok: '#7ee0a8' },
  },
  maquette: {
    view: { yaw: 0.36, pitch: 0.56 }, ink: '#12332c', brand: '#ee6a2f', ground: '#d9e0d9', grid: '#c8d1c9',
    paint: ['#f2b338', '#39678a', '#698d70', '#e56c36'],
    s: { needs: '#e9a400', ready: '#ee6a2f', run: '#3b7f9e', queued: '#a3aea6', sent: '#a3aea6', ok: '#2f8757' },
  },
};
const SCENES = {};
const isDone = (j) => j.state === 'ok' || j.state === 'sent';

function kit(T) {
  const mats = new Map(), geos = new Map();
  const memo = (m, key, make) => m.get(key) || (m.set(key, make()), m.get(key));
  const mat = (c, glow = 0) =>
    memo(mats, c + '|' + glow, () => new T.MeshStandardMaterial({ color: c, roughness: 0.78, emissive: glow ? c : '#000000', emissiveIntensity: glow }));
  const clear = (c, o, glow = 0) =>
    new T.MeshStandardMaterial({ color: c, roughness: 1, transparent: o < 1, opacity: o, side: 2, depthWrite: o >= 1, emissive: glow ? c : '#000000', emissiveIntensity: glow });
  const put = (p, g, m, x, y, z) => {
    const o = new T.Mesh(g, typeof m === 'string' ? mat(m) : m);
    o.position.set(x, y, z);
    o.castShadow = o.receiveShadow = true;
    p.add(o);
    return o;
  };
  const band = (p, rTop, rBottom, h, y, m, a0, len) =>
    put(p, new T.CylinderGeometry(rTop, rBottom, h, Math.max(10, Math.round(len * 26)), 1, true, a0, len), m, 0, y, 0);
  return {
    mat, clear, put,
    box: (p, x, y, z, w, h, d, c, r = 0) =>
      put(p, memo(geos, ['b', w, h, d, r].join(), () => (r ? new T.RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2, h / 2, d / 2)) : new T.BoxGeometry(w, h, d))), c, x, y, z),
    cyl: (p, x, y, z, r, h, c, n = 40) => put(p, memo(geos, ['c', r, h, n].join(), () => new T.CylinderGeometry(r, r, h, n)), c, x, y, z),
    ball: (p, x, y, z, r, c) => put(p, memo(geos, 's' + r, () => new T.SphereGeometry(r, 28, 18)), c, x, y, z),
    group: (p, x = 0, y = 0, z = 0) => {
      const g = new T.Group();
      g.position.set(x, y, z);
      p.add(g);
      return g;
    },
    // A flat ring or arc lying on the ground. Angle 0 faces the viewer, positive angles go right.
    ring: (p, r, w, y, m, a0 = 0, len = Math.PI * 2) => band(p, r - w / 2, r + w / 2, 0.001, y, m, a0, len),
    wall: (p, r, h, y, m, a0, len) => band(p, r, r, h, y, m, a0, len),
  };
}

function daylight({ T, scene, th }) {
  const sun = new T.DirectionalLight(0xfff3e0, 2.7);
  sun.position.set(-10, 16, 9);
  sun.castShadow = true;
  Object.assign(sun.shadow.camera, { left: -18, right: 18, top: 15, bottom: -15, near: 2, far: 60 });
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.radius = 4;
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.03;
  scene.add(sun, new T.AmbientLight(0xffffff, 1.6));
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = th.ground;
  g.fillRect(0, 0, 128, 128);
  g.strokeStyle = th.grid;
  g.lineWidth = 2;
  g.strokeRect(0, 0, 128, 128);
  const tex = new T.CanvasTexture(c);
  tex.wrapS = tex.wrapT = 1000; // RepeatWrapping
  tex.repeat.set(200, 200);
  tex.colorSpace = T.SRGBColorSpace;
  tex.anisotropy = 8;
  const floor = new T.Mesh(new T.PlaneGeometry(500, 500), new T.MeshStandardMaterial({ map: tex, roughness: 1 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
}

/* 1. Line: every application is a railcar on one elevated line with four stops and a terminus. */
SCENES.line = (x) => {
  const { T, k, scene, jobs, th, label } = x;
  daylight(x);
  const SX = [-4.8, -1.6, 1.6, 4.8], END = 7.8, Y = 1.15;
  const deck = '#f4f6f8', pier = '#c9d1da', ink = th.ink, paper = '#ffffff';
  k.box(scene, 1.2, Y - 0.13, 0, 16.4, 0.26, 1.3, deck, 0.07);
  for (let px = -6.4; px < 9.3; px += 1.6) k.box(scene, px, (Y - 0.26) / 2, 0, 0.42, Y - 0.26, 0.8, pier, 0.06);
  k.box(scene, 1.2, Y + 0.012, 0, 16.4, 0.03, 0.3, th.brand);
  k.box(scene, 9.3, Y + 0.2, 0, 0.2, 0.42, 1, ink, 0.05);
  for (const sx of [...SX, END]) {
    k.cyl(scene, sx, Y + 0.025, 0, 0.52, 0.03, ink);
    k.cyl(scene, sx, Y + 0.035, 0, 0.38, 0.03, paper);
  }
  SX.forEach((sx, i) => {
    const s = k.group(scene, sx, 0, -1.45);
    k.box(s, 0, (Y - 0.2) / 2, 0, 2.4, Y - 0.2, 1, pier, 0.06);
    k.box(s, 0, Y - 0.1, 0, 2.7, 0.2, 1.4, deck, 0.05);
    for (const e of [-1.05, 1.05]) k.cyl(s, e, Y + 0.65, -0.45, 0.05, 1.3, ink, 12);
    k.box(s, 0, Y + 1.32, -0.3, 2.5, 0.07, 1.1, deck, 0.03);
    k.box(s, 0, Y + 1.32, 0.27, 2.5, 0.13, 0.05, ink);
    if (i === 0) for (let n = 0; n < 3; n++) k.box(s, 0.2, Y + 0.07 + n * 0.13, -0.05, 0.8, 0.06, 0.55, n % 2 ? pier : paper, 0.02);
    if (i === 1) {
      k.box(s, 0.2, Y + 0.14, -0.15, 0.1, 0.28, 0.1, ink);
      k.box(s, 0.2, Y + 0.52, -0.15, 0.82, 0.5, 0.07, ink, 0.04);
      k.box(s, 0.2, Y + 0.03, 0.25, 0.7, 0.05, 0.22, pier, 0.02);
    }
    if (i === 2) {
      for (const e of [-0.82, 0.82]) k.box(scene, sx, Y + 0.75, e, 0.14, 1.5, 0.14, ink, 0.03);
      k.box(scene, sx, Y + 1.5, 0, 0.16, 0.14, 1.78, ink, 0.03);
      k.box(scene, sx, Y + 1.41, 0, 0.06, 0.04, 1.3, k.mat(th.s.run, 0.9));
    }
    if (i === 3) {
      k.box(s, 0.3, Y + 0.45, -0.1, 0.7, 0.9, 0.55, ink, 0.1);
      k.box(s, 0.3, Y + 0.62, 0.18, 0.46, 0.06, 0.02, paper);
    }
  });
  const capsule = new T.CapsuleGeometry(0.3, 0.62, 6, 20);
  const cars = new Map(), queued = [0, 0, 0, 0], flags = [];
  for (const j of jobs) {
    const x0 = j.state === 'ok' ? END : j.state === 'sent' ? (SX[3] + END) / 2 : SX[j.st] - 1.28 * queued[j.st]++;
    const g = k.group(scene, x0, Y + 0.04, 0);
    g.userData.job = j.id;
    for (const e of [-0.3, 0.3]) k.box(g, e, 0.08, 0, 0.26, 0.16, 0.5, ink, 0.04);
    const body = k.put(g, capsule, paper, 0, 0.44, 0);
    body.rotation.z = Math.PI / 2;
    k.box(g, 0, 0.5, 0, 0.74, 0.15, 0.612, ink, 0.03);
    k.ball(g, 0.36, 0.75, 0, 0.075, k.mat(th.s[j.state], 0.8));
    if (j.state === 'needs') {
      const m = k.group(g, -0.2, 0, -0.5);
      k.cyl(m, 0, 0.8, 0, 0.03, 1.6, ink, 10);
      k.box(m, 0.21, 1.45, 0, 0.4, 0.26, 0.03, k.mat(th.s.needs, 0.35), 0.02);
      flags.push(m);
    }
    cars.set(j.id, { g, body, x0, j });
  }
  const count = (i) => jobs.filter((j) => !isDone(j) && j.st === i).length;
  ['Intake', 'Fill', 'Verify', 'Dispatch'].forEach((n, i) => label(`<b>${n}</b><i>${count(i)}</i>`, new T.Vector3(SX[i], Y + 1.7, -1.6), 'station'));
  label(`<b>Applied</b><i>${jobs.filter(isDone).length}</i>`, new T.Vector3(END, Y + 1.15, 0.4), 'station');
  const v = new T.Vector3();
  return {
    span: 17, depth: 5.5, height: 3.6, center: new T.Vector3(1.2, 1.2, -0.4),
    select(id) {
      for (const [key, c] of cars) c.body.material = k.mat(key === id ? th.brand : paper);
    },
    tick(t) {
      for (const c of cars.values()) if (c.j.state === 'run') c.g.position.x = c.x0 + Math.sin(t * 1.4) * 0.16;
      for (const m of flags) m.rotation.y = Math.sin(t * 2.2) * 0.3;
    },
    focus(id) {
      const c = cars.get(id);
      return v.set(c.g.position.x, Y + (c.j.state === 'needs' ? 1.85 : 1.1), 0);
    },
  };
};

/* 2. Orbit: four orbits are the four stages, inward toward the receipt at the centre. */
SCENES.orbit = (x) => {
  const { T, k, scene, jobs, th, label } = x;
  const sun = new T.DirectionalLight(0xffe9c9, 2.2);
  sun.position.set(-6, 12, 8);
  scene.add(sun, new T.AmbientLight(0xbfc8ff, 1.1));
  const R = [7.8, 6.2, 4.6, 3.0], chalk = th.ink;
  k.cyl(scene, 0, -0.04, 0, 8.9, 0.02, k.clear('#1c2556', 0.62), 96);
  const orbits = R.map((r) => k.ring(scene, r, 0.035, 0, k.clear(chalk, 0.4, 1)));
  const innerOrbit = k.ring(scene, 1.9, 0.025, 0, k.clear(chalk, 0.3, 1));
  k.ring(scene, 8.9, 0.025, 0, k.clear(chalk, 0.25, 1));
  const tick = k.clear(chalk, 0.12, 1);
  for (let a = 0; a < 24; a++) {
    const g = k.group(scene);
    g.rotation.y = (a * Math.PI) / 12;
    k.box(g, 0, 0, 5.25, 0.014, 0.002, 7.3, tick);
  }
  const rnd = (i, s) => (((Math.sin(i * 127.1 + s * 311.7) * 43758.5453) % 1) + 1) % 1;
  for (let i = 0; i < 300; i++) {
    const sx = rnd(i, 1) * 72 - 36, sz = rnd(i, 2) * 72 - 36;
    if (Math.hypot(sx, sz) > 9.6) k.ball(scene, sx, -1, sz, rnd(i, 3) > 0.85 ? 0.07 : 0.035, k.mat(chalk, 1));
  }
  k.ball(scene, 0, 0.25, 0, 0.95, k.mat(th.sun, 1));
  k.ball(scene, 0, 0.25, 0, 1.35, k.clear(th.sun, 0.14, 1));
  const A = [-1.9, 0.75, -0.55, 0.15], n = [0, 0, 0, 0], planets = new Map(), spin = [];
  const ringG = R.map(() => k.group(scene)), inner = k.group(scene);
  const hit = k.clear('#000000', 0);
  for (const j of jobs) {
    const r = isDone(j) ? 1.9 : R[j.st];
    const a = j.state === 'ok' ? 2.4 : j.state === 'sent' ? -1 : A[j.st] + n[j.st]++ * 0.9;
    const g = k.group(isDone(j) ? inner : ringG[j.st], Math.sin(a) * r, 0.25, Math.cos(a) * r);
    g.userData.job = j.id;
    const size = { queued: 0.22, run: 0.33, needs: 0.36, ready: 0.36, sent: 0.2, ok: 0.2 }[j.state];
    k.ball(g, 0, 0, 0, size, k.mat(th.s[j.state], j.state === 'queued' ? 0.25 : 0.7));
    k.ball(g, 0, 0, 0, 0.62, hit);
    if (j.state === 'needs') {
      const o = k.ring(g, size * 1.8, 0.08, 0, k.clear(th.s.needs, 1, 1));
      o.rotation.x = 1.05;
      spin.push(o);
    }
    if (j.state === 'ready') k.ring(g, size * 1.85, 0.05, 0, k.clear(chalk, 1, 1));
    if (j.state === 'run') k.ring(ringG[j.st], r, 0.1, 0.25, k.clear(th.s.run, 0.8, 1), a - 0.62, 0.56);
    planets.set(j.id, { g, j });
  }
  const reticle = k.ring(scene, 0.74, 0.04, 0, k.clear(chalk, 1, 1));
  ['Intake', 'Fill', 'Verify', 'Dispatch'].forEach((name, i) => {
    const c = jobs.filter((j) => !isDone(j) && j.st === i).length;
    label(`<b>${name}</b><i>${c}</i>`, new T.Vector3(Math.sin(1.12) * R[i], 0.1, Math.cos(1.12) * R[i]), 'station');
  });
  label(`<b>Applied</b><i>${jobs.filter(isDone).length}</i>`, new T.Vector3(0, 1.75, 0), 'station');
  const v = new T.Vector3();
  let sel = null;
  return {
    span: 19.6, depth: 18.4, height: 2.4, center: new T.Vector3(0, 0, 0),
    select(id) {
      sel = planets.get(id);
      for (const p of planets.values()) p.g.scale.setScalar(p === sel ? 1.3 : 1);
      orbits.forEach((o, i) => (o.material.opacity = !isDone(sel.j) && sel.j.st === i ? 1 : 0.35));
      innerOrbit.material.opacity = isDone(sel.j) ? 1 : 0.3;
    },
    tick(t) {
      ringG.forEach((g, i) => (g.rotation.y = t * [0.01, 0.045, 0.016, 0.022][i]));
      inner.rotation.y = t * 0.05;
      for (const o of spin) o.rotation.y = t * 1.2;
      if (sel) sel.g.getWorldPosition(reticle.position);
    },
    focus(id) {
      return planets.get(id).g.getWorldPosition(v).setY(0.95);
    },
  };
};

/* 3. Maquette: the existing four-station workshop as a clay model, with the queue as a ring around it. */
SCENES.maquette = (x) => {
  const { T, k, scene, jobs, th, label } = x;
  daylight(x);
  const clay = '#f4f5f0', clay2 = '#d9dfd8', dark = '#2b4a41', B = 0.36, top = 0.685;
  k.cyl(scene, 0, 0.15, 0, 5.5, 0.3, clay2, 96);
  k.cyl(scene, 0, 0.33, 0, 5.3, 0.06, clay, 96);
  const X = [-3.6, -1.2, 1.2, 3.6], Z = [0.35, -0.5, -0.5, 0.35];
  const stations = [], lamps = [], heads = [];
  X.forEach((sx, i) => {
    const s = k.group(scene, sx, B, Z[i]);
    s.rotation.y = [0.22, 0.07, -0.07, -0.22][i];
    stations.push(s);
    k.box(s, 0, 0.3, 0, 2.1, 0.6, 1.5, clay, 0.1);
    k.box(s, 0, 0.64, 0, 2.2, 0.09, 1.6, clay2, 0.04);
    k.box(s, 0, 0.3, 0.77, 1, 0.2, 0.04, th.paint[i], 0.02);
    if (i === 0) {
      for (let n = 0; n < 3; n++) k.box(s, -0.2, top + 0.1 + n * 0.2, -0.2, 1.15, 0.07, 0.75, clay, 0.03);
      for (const e of [-1, 1]) k.box(s, -0.2 + e * 0.6, top + 0.32, -0.2, 0.06, 0.62, 0.6, clay2, 0.02);
    }
    if (i === 1) {
      k.box(s, -0.2, top + 0.2, -0.35, 0.14, 0.4, 0.14, clay2, 0.03);
      k.box(s, -0.2, top + 0.62, -0.38, 1.2, 0.72, 0.12, clay, 0.06).rotation.x = -0.1;
      k.box(s, -0.2, top + 0.62, -0.31, 1, 0.54, 0.02, dark, 0.03).rotation.x = -0.1;
      k.box(s, -0.1, top + 0.03, 0.3, 0.95, 0.05, 0.33, clay, 0.02);
    }
    if (i === 2) {
      for (const e of [-1, 1]) k.box(s, e * 0.68, top + 0.42, -0.2, 0.18, 0.84, 0.36, clay, 0.05);
      k.box(s, 0, top + 0.92, -0.2, 1.54, 0.2, 0.4, clay, 0.06);
      k.box(s, 0, top + 0.8, -0.2, 1.1, 0.03, 0.2, k.mat('#bfe37a', 0.6));
      for (let n = 0; n < 5; n++) k.cyl(s, 0, top + 0.07, -0.5 + n * 0.2, 0.08, 1.15, clay2, 16).rotation.z = Math.PI / 2;
    }
    if (i === 3) {
      k.box(s, -0.1, top + 0.52, -0.2, 1.3, 1, 0.8, clay, 0.13);
      k.box(s, -0.1, top + 0.68, 0.21, 0.95, 0.14, 0.03, dark, 0.03);
      k.box(s, -0.1, top + 0.56, 0.27, 1.05, 0.06, 0.2, clay2, 0.02);
    }
    k.cyl(s, 0.82, top + 0.24, -0.5, 0.03, 0.48, dark, 10);
    lamps.push(k.ball(s, 0.82, top + 0.52, -0.5, 0.11, clay));
    const bot = k.group(s, -0.72, 0, 1.08);
    bot.rotation.y = 0.6;
    for (const e of [-1, 1]) k.box(bot, e * 0.14, 0.1, 0.03, 0.2, 0.2, 0.3, dark, 0.05);
    k.box(bot, 0, 0.5, 0, 0.5, 0.52, 0.36, clay, 0.1);
    k.box(bot, 0, 0.52, 0.185, 0.24, 0.14, 0.02, th.paint[i], 0.02);
    for (const e of [-1, 1]) k.box(bot, e * 0.31, 0.5, 0.03, 0.1, 0.36, 0.12, clay2, 0.05);
    const head = k.group(bot, 0, 1, 0);
    k.box(head, 0, 0, 0, 0.66, 0.46, 0.46, clay, 0.13);
    k.box(head, 0, 0.01, 0.22, 0.5, 0.22, 0.06, dark, 0.06);
    for (const e of [-1, 1]) k.box(head, e * 0.11, 0.02, 0.255, 0.07, 0.08, 0.015, k.mat('#ffcd84', 0.7), 0.01);
    k.cyl(head, -0.14, 0.3, -0.04, 0.016, 0.14, dark, 8);
    k.ball(head, -0.14, 0.4, -0.04, 0.045, th.paint[i]);
    heads.push(head);
  });
  for (let i = 0; i < 3; i++) {
    const dx = X[i + 1] - X[i], dz = Z[i + 1] - Z[i];
    k.box(scene, X[i] + dx / 2, B + 0.2, Z[i] + dz / 2, Math.hypot(dx, dz) - 1.9, 0.1, 0.3, dark, 0.04).rotation.y = -Math.atan2(dz, dx);
  }
  const folder = k.group(stations[0], 0.3, top + 0.16, 0.42);
  k.box(folder, 0, 0, 0, 0.7, 0.09, 0.5, th.brand, 0.03);
  k.box(folder, -0.17, 0.005, -0.26, 0.28, 0.07, 0.12, th.brand, 0.02);
  k.box(folder, 0.02, 0.055, 0.015, 0.54, 0.03, 0.37, clay, 0.01);
  const mark = k.group(folder, 0, 0.6, 0);
  const gem = k.box(mark, 0, 0, 0, 0.2, 0.2, 0.2, k.mat(th.s.needs, 0.6));
  gem.rotation.set(0.615, 0, Math.PI / 4);
  const slip = k.box(stations[3], 0.3, top + 0.03, 0.42, 0.5, 0.03, 0.4, '#ffffff', 0.01);
  // Queue ring: one arc per application, in queue order from left to right.
  const QR = 6.3, a0 = -1.05, step = 2.1 / jobs.length, gap = 0.035, segs = new Map();
  k.ring(scene, QR, 0.05, 0.02, k.mat(clay2));
  jobs.forEach((j, i) => {
    const g = k.group(scene), m = k.clear(th.s[j.state], 1), from = a0 + i * step + gap / 2, len = step - gap;
    g.userData.job = j.id;
    k.wall(g, QR + 0.14, 0.22, 0.11, m, from, len);
    k.wall(g, QR - 0.14, 0.22, 0.11, m, from, len);
    k.ring(g, QR, 0.28, 0.22, m, from, len);
    segs.set(j.id, g);
  });
  ['Intake', 'Fill', 'Verify', 'Dispatch'].forEach((name, i) => {
    const c = jobs.filter((j) => !isDone(j) && j.st === i).length;
    label(`<b>${name}</b><i>${c}</i>`, new T.Vector3(X[i], B + 2.55, Z[i] - 0.2), 'station');
  });
  label(`<b>Queue</b><i>${jobs.length}</i>`, new T.Vector3(Math.sin(a0 - 0.1) * QR, 0.5, Math.cos(a0 - 0.1) * QR), 'station');
  const v = new T.Vector3();
  let cur = jobs[0];
  return {
    span: 11.8, depth: 12.4, height: 3.2, center: new T.Vector3(0, 0.9, 0.3),
    select(id) {
      cur = jobs.find((j) => j.id === id);
      stations[cur.st].add(folder);
      folder.visible = !isDone(cur);
      slip.visible = cur.state === 'ok';
      mark.visible = cur.state === 'needs';
      lamps.forEach((l, i) => (l.material = i === cur.st ? k.mat(th.s[cur.state], 0.8) : k.mat(clay)));
      for (const [key, g] of segs) g.position.y = key === id ? 0.3 : 0;
    },
    tick(t) {
      folder.position.y = top + 0.16 + (t ? 0.05 + Math.sin(t * 2.4) * 0.04 : 0);
      mark.rotation.y = t * 1.5;
      heads.forEach((h, i) => (h.rotation.y = Math.sin(t * 0.7 + i * 1.7) * 0.28));
    },
    focus() {
      return stations[cur.st].localToWorld(v.set(0.3, top + (isDone(cur) ? 1.6 : cur.state === 'needs' ? 1.25 : 0.75), 0.42));
    },
  };
};

function makeStage(host, labelHost, name, jobs, onPick) {
  const T = THREE, th = THEMES[name], root = document.documentElement;
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', '3D view of the application queue. Drag, or use the left and right arrow keys, to turn it.');
  host.append(canvas);
  const scene = new T.Scene(), camera = new T.OrthographicCamera(-1, 1, 1, -1, 1, 400), labels = [];
  const label = (html, pos, cls) => {
    const el = document.createElement('div');
    el.className = 'wl ' + cls;
    el.innerHTML = html;
    labelHost.append(el);
    const l = { el, pos };
    labels.push(l);
    return l;
  };
  const world = SCENES[name]({ T, k: kit(T), scene, jobs, th, label });
  const tag = label('', new T.Vector3(), 'tag');
  const VIEWS = { '3D': th.view, Top: { yaw: 0, pitch: 1.5 }, Side: { yaw: 0, pitch: 0.12 } };
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const v = new T.Vector3(), ray = new T.Raycaster(), pt = new T.Vector2();
  let goal = { ...th.view }, yaw = goal.yaw, pitch = goal.pitch, half = 0, w = 0, h = 0, free, drag = null, held = 0, sel = null;

  function resize() {
    w = host.clientWidth;
    h = host.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    const px = (n) => parseFloat(getComputedStyle(root).getPropertyValue(n)) || 0;
    const l = px('--fl'), r = px('--fr'), t = px('--ft'), b = px('--fb');
    // The model is framed in the part of the window the panels leave free.
    free = { w: Math.max(240, w - l - r), h: Math.max(180, h - t - b), cx: l + (w - l - r) / 2, cy: t + (h - t - b) / 2 };
  }
  new ResizeObserver(resize).observe(host);

  function pose() {
    const sp = Math.sin(pitch), cp = Math.cos(pitch), aspect = w / h;
    const need = 1.06 * Math.max((world.span * h) / (2 * free.w), ((world.depth * sp + world.height * cp) * h) / (2 * free.h));
    half += (need - half) * (half ? 0.14 : 1);
    const sx = ((free.cx / w) * 2 - 1) * half * aspect, sy = (1 - (free.cy / h) * 2) * half;
    Object.assign(camera, { left: -half * aspect - sx, right: half * aspect - sx, top: half - sy, bottom: -half - sy });
    const c = world.center;
    camera.position.set(c.x + Math.sin(yaw) * cp * 90, c.y + sp * 90, c.z + Math.cos(yaw) * cp * 90);
    camera.lookAt(c);
    camera.updateProjectionMatrix();
  }
  function jobAt(e) {
    const r = canvas.getBoundingClientRect();
    pt.set(((e.clientX - r.left) / r.width) * 2 - 1, 1 - ((e.clientY - r.top) / r.height) * 2);
    ray.setFromCamera(pt, camera);
    for (const hit of ray.intersectObjects(scene.children, true))
      for (let o = hit.object; o; o = o.parent) if (o.userData.job) return o.userData.job;
    return null;
  }
  canvas.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, y: e.clientY, yaw: goal.yaw, pitch: goal.pitch };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return void (canvas.style.cursor = jobAt(e) ? 'pointer' : 'grab');
    goal.yaw = clamp(drag.yaw - (e.clientX - drag.x) * 0.005, -1.3, 1.3);
    goal.pitch = clamp(drag.pitch + (e.clientY - drag.y) * 0.004, 0.1, 1.5);
  });
  canvas.addEventListener('pointerup', (e) => {
    const id = drag && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6 && jobAt(e);
    drag = null;
    held = performance.now() + 4000;
    if (id) onPick(id);
  });
  canvas.addEventListener('pointercancel', () => (drag = null));
  canvas.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    goal.yaw = clamp(goal.yaw + (e.key === 'ArrowLeft' ? 0.15 : -0.15), -1.3, 1.3);
    held = performance.now() + 4000;
  });

  function draw(now) {
    if (!w || !h) return;
    const move = !still.matches, t = move ? now / 1000 : 0;
    const sway = move && !drag && now > held ? Math.sin(now / 4000) * 0.05 : 0;
    yaw += (goal.yaw + sway - yaw) * (move ? 0.08 : 1);
    pitch += (goal.pitch - pitch) * (move ? 0.08 : 1);
    pose();
    world.tick(t);
    if (sel) tag.pos.copy(world.focus(sel));
    renderer.render(scene, camera);
    for (const l of labels) {
      v.copy(l.pos).project(camera);
      l.el.style.transform = `translate(${(((v.x + 1) / 2) * w).toFixed(1)}px,${(((1 - v.y) / 2) * h).toFixed(1)}px) translate(-50%,-100%)`;
    }
  }
  const loop = (now) => (requestAnimationFrame(loop), draw(now));
  resize();
  loop(performance.now());
  return {
    select(id, html) {
      sel = id;
      world.select(id);
      tag.el.innerHTML = html;
      draw(performance.now()); // correct even while the window is in the background and frames are paused
    },
    view(n) {
      goal = { ...VIEWS[n] };
      held = 0;
    },
  };
}
