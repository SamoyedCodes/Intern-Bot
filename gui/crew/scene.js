function makeCrewScene(host, selectJob, inspectStation) {
  const T = window.THREE;
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  // Always render at 2x: on a standard-density display this supersamples the small models and their edges.
  renderer.setPixelRatio(2);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFShadowMap;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', '3D crew. Drag or use the left and right arrow keys to change the angle.');
  host.prepend(canvas);
  const scene = new T.Scene(),
    camera = new T.OrthographicCamera(-10, 10, 5, -5, 0.1, 90);
  const sun = new T.DirectionalLight(0xfff3dd, 2.8);
  sun.position.set(-8, 13, 8);
  sun.castShadow = true;
  // A tight frustum and a large map keep the cast shadows smooth instead of stair-stepped.
  Object.assign(sun.shadow.camera, { left: -9.5, right: 9.5, top: 8, bottom: -8, near: 4, far: 34 });
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.radius = 3;
  sun.shadow.bias = -0.0003;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, new T.AmbientLight(0xffffff, 1.65));
  const shapes = new Map(),
    materials = new Map();
  function cached(map, key, make) {
    if (!map.has(key)) map.set(key, make());
    return map.get(key);
  }
  function mat(color) {
    return cached(materials, color, () => new T.MeshStandardMaterial({ color, roughness: 0.72 }));
  }
  function mesh(p, g, m, x, y, z) {
    const o = new T.Mesh(g, m);
    o.position.set(x, y, z);
    o.castShadow = true;
    o.receiveShadow = true;
    p.add(o);
    return o;
  }
  function box(p, x, y, z, w, h, d, color, r = 0) {
    const geometry = cached(shapes, ['b', w, h, d, r].join('/'), () =>
      r ? new T.RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2, h / 2, d / 2)) : new T.BoxGeometry(w, h, d),
    );
    return mesh(p, geometry, mat(color), x, y, z);
  }
  function cyl(p, x, y, z, top, bottom, h, color, n = 24) {
    const g = cached(shapes, ['c', top, bottom, h, n].join('/'), () => new T.CylinderGeometry(top, bottom, h, n));
    return mesh(p, g, mat(color), x, y, z);
  }
  function ball(p, x, y, z, r, color) {
    const g = cached(shapes, 's' + r, () => new T.SphereGeometry(r, 18, 12));
    return mesh(p, g, mat(color), x, y, z);
  }
  function group(p, x = 0, y = 0, z = 0) {
    const g = new T.Group();
    g.position.set(x, y, z);
    p.add(g);
    return g;
  }
  function rod(p, a, b, r, color) {
    const av = new T.Vector3(...a),
      bv = new T.Vector3(...b),
      dir = bv.clone().sub(av);
    const o = cyl(p, 0, 0, 0, r, r, dir.length(), color, 12);
    o.position.copy(av.add(bv).multiplyScalar(0.5));
    o.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), dir.normalize());
    return o;
  }
  function plate(p, x, y, z, w, h, text, bg, fg, fontsize = 110) {
    const c = document.createElement('canvas');
    c.width = 768;
    c.height = 160;
    const ctx = c.getContext('2d');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = fg;
    ctx.font = 'bold ' + fontsize + 'px Helvetica Neue, Arial, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText(text, 384, 84, 740);
    const tex = new T.CanvasTexture(c);
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const o = mesh(p, new T.PlaneGeometry(w, h), new T.MeshStandardMaterial({ map: tex, roughness: 1 }), x, y, z);
    o.castShadow = false;
    return o;
  }
  const dark = '#233932',
    cream = '#f4ead1',
    blue = '#39678a',
    mint = '#698d70',
    orange = '#e56c36',
    yellow = '#f2b338';
  function worker(p, x, y, z, paint, id, field = false) {
    const root = group(p, x, y, z),
      torso = group(root, 0, 0.53, 0);
    root.userData[field ? 'job' : 'station'] = id;
    const boots = field ? '#5d6359' : dark,
      skin = field ? '#d8dace' : cream;
    for (const s of [-1, 1]) {
      cyl(root, s * 0.15, 0.35, 0, 0.085, 0.086, 0.36, boots);
      box(root, s * 0.15, 0.15, 0.064, 0.235, 0.15, 0.3, boots, 0.055);
    }
    box(torso, 0, 0.12, 0, 0.49, 0.53, 0.36, paint, 0.105);
    box(torso, 0, 0.025, 0.192, 0.26, 0.17, 0.035, skin, 0.025);
    cyl(torso, 0, 0.46, 0, 0.12, 0.14, 0.17, boots);
    const head = group(torso, 0, 0.63, 0);
    box(head, 0, 0, 0, 0.66, 0.48, 0.47, skin, 0.13);
    box(head, 0, 0.008, 0.225, 0.49, 0.23, 0.075, boots, 0.065);
    const eyes = [-1, 1].map((side) => {
      ball(head, side * 0.335, -0.025, 0.005, 0.067, paint);
      return box(head, side * 0.113, 0.02, 0.268, 0.067, 0.08, 0.018, field ? '#f3f2df' : '#ffcd84', 0.012);
    });
    const antenna = group(head, -0.14, 0.22, -0.04);
    cyl(antenna, 0, 0.06, 0, 0.017, 0.017, 0.12, boots, 10);
    ball(antenna, 0, 0.14, 0, 0.044, paint);
    const arms = [-1, 1].map((s) => {
      const arm = group(torso, s * 0.276, 0.26, 0.01);
      ball(arm, 0, 0, 0, 0.076, boots);
      rod(arm, [0, 0, 0], [s * 0.084, -0.15, 0.1], 0.055, paint);
      ball(arm, s * 0.084, -0.15, 0.1, 0.06, boots);
      rod(arm, [s * 0.084, -0.15, 0.1], [s * 0.083, -0.16, 0.25], 0.047, boots);
      ball(arm, s * 0.083, -0.16, 0.25, 0.073, skin);
      return arm;
    });
    return { root, head, arms, torso, eyes, antenna };
  }
  const floor = box(scene, 0, -0.62, 0, 160, 0.1, 160, '#b8cbbd');
  floor.castShadow = false;
  const shop = group(scene),
    field = group(scene);
  const spots = [
    [-5.35, 0.35],
    [-1.8, -0.53],
    [1.8, -0.53],
    [5.35, 0.35],
  ];
  const names = ['INTAKE', 'FILL', 'VERIFY', 'DISPATCH'],
    paints = [yellow, blue, mint, orange];
  const bots = [],
    bulbs = [];
  for (let i = 0; i < 4; i++) {
    const [x, z] = spots[i],
      station = group(shop, x, 0, z);
    station.userData.station = i;
    box(station, 0, -0.27, 0, 3.38, 0.44, 3.35, '#5e746a', 0.17);
    box(station, 0, -0.018, 0, 3.36, 0.19, 3.33, '#ecdfba', 0.14);
    box(station, 0, 0.09, 0, 3.23, 0.08, 3.19, '#ddd3b5', 0.09);
    box(station, 0, -0.14, 1.676, 2.3, 0.31, 0.045, dark, 0.025);
    plate(station, 0, -0.14, 1.703, 2.24, 0.245, '0' + (i + 1) + '  /  ' + names[i], dark, '#ffedc9', 100);
    const machine = group(station, 0.14, 0, -0.37);
    box(machine, 0, 0.2, 0, 2.06, 0.15, 1.28, dark, 0.065);
    box(machine, 0, 0.55, 0, 1.86, 0.65, 1.18, paints[i], 0.095);
    box(machine, 0, 0.91, 0, 2.12, 0.12, 1.38, cream, 0.055);
    for (const s of [-1, 1]) {
      box(machine, s * 0.74, 0.65, 0.602, 0.06, 0.21, 0.027, dark, 0.015);
    }
    // Each machine has a distinct silhouette, even without its nameplate.
    if (i === 0) {
      for (let j = 0; j < 3; j++) {
        box(machine, -0.25, 1.02 + j * 0.21, -0.18, 1.22, 0.09, 0.81, blue, 0.038);
        box(machine, -0.26, 1.1 + j * 0.21, -0.22, 1.04, 0.055, 0.61, cream, 0.018);
        box(machine, -0.25, 1.13 + j * 0.21, -0.57, 1.22, 0.22, 0.072, blue, 0.021);
      }
      for (const s of [-1, 1]) box(machine, -0.25 + s * 0.57, 1.28, -0.27, 0.07, 0.51, 0.67, blue, 0.025);
    }
    if (i === 1) {
      box(machine, -0.25, 1.14, -0.3, 0.15, 0.36, 0.17, dark, 0.03);
      const screen = group(machine, -0.25, 1.48, -0.35);
      screen.rotation.x = -0.12;
      box(screen, 0, 0, 0, 1.24, 0.75, 0.155, cream, 0.08);
      box(screen, 0, 0.02, 0.084, 1.02, 0.54, 0.02, dark, 0.035);
      for (let j = 0; j < 3; j++) box(screen, -0.12, 0.17 - j * 0.13, 0.105, 0.64 - j * 0.065, 0.033, 0.014, '#9cbfa5');
      box(machine, -0.09, 0.998, 0.3, 0.98, 0.055, 0.35, dark, 0.028);
      for (let j = 0; j < 3; j++) box(machine, -0.12, 1.033, 0.18 + j * 0.088, 0.77, 0.02, 0.027, '#91a49b');
    }
    if (i === 2) {
      for (const s of [-1, 1]) box(machine, s * 0.67, 1.3, -0.19, 0.18, 0.77, 0.35, mint, 0.05);
      box(machine, 0, 1.75, -0.19, 1.52, 0.22, 0.38, mint, 0.065);
      box(machine, 0, 1.62, -0.17, 1.04, 0.033, 0.2, '#c7ec81');
      for (let j = 0; j < 5; j++) {
        const roller = cyl(machine, 0, 1.02, -0.45 + j * 0.2, 0.09, 0.09, 1.18, '#5a7069');
        roller.rotation.z = Math.PI / 2;
      }
    }
    if (i === 3) {
      box(machine, -0.1, 1.43, -0.18, 1.34, 1.03, 0.83, orange, 0.13);
      box(machine, -0.1, 1.58, 0.246, 0.98, 0.17, 0.025, dark, 0.032);
      box(machine, -0.1, 1.47, 0.3, 1.09, 0.07, 0.2, cream, 0.028);
      box(machine, -0.1, 1.14, 0.25, 0.47, 0.085, 0.018, cream, 0.012);
    }
    cyl(machine, 0.8, 1.2, -0.45, 0.031, 0.036, 0.47, dark, 12);
    const bulb = ball(machine, 0.8, 1.46, -0.45, 0.12, cream);
    bulbs.push(bulb);
    const b = worker(station, -0.68, 0.12, 0.89, paints[i], i);
    b.root.scale.setScalar(1.14);
    b.root.rotation.y = 0.68;
    bots.push(b);
    // Tool caddy on each workbench.
    cyl(machine, 0.71, 1.066, 0.27, 0.115, 0.095, 0.21, dark);
    for (let k = 0; k < 3; k++)
      rod(machine, [0.67 + k * 0.038, 1.09, 0.28], [0.63 + k * 0.075, 1.31 + (k % 2) * 0.07, 0.25], 0.018, cream);
  }
  for (let i = 0; i < 3; i++) {
    const [x, z] = spots[i],
      [nx, nz] = spots[i + 1];
    rod(shop, [x + 1.35, -0.21, z], [nx - 1.35, -0.21, nz], 0.14, dark);
  }
  const folder = group(shop);
  box(folder, 0, 0, 0, 0.68, 0.085, 0.49, orange, 0.035);
  box(folder, -0.17, 0.005, -0.255, 0.29, 0.065, 0.11, orange, 0.02);
  box(folder, 0.025, 0.055, 0.015, 0.53, 0.028, 0.36, cream, 0.012);
  for (let i = 0; i < 2; i++) box(folder, -0.025, 0.073, -0.05 + i * 0.1, 0.26, 0.01, 0.016, dark);

  const questionSign = group(bots[2].root, 0.41, 1.91, 0.14);
  box(questionSign, 0, 0, 0, 0.42, 0.47, 0.052, yellow, 0.055);
  plate(questionSign, 0, 0, 0.032, 0.34, 0.35, '?', yellow, dark, 158);
  questionSign.visible = false;
  const receiptSlip = group(shop, spots[3][0] + 0.04, 1.29, spots[3][1] + 0.06);
  box(receiptSlip, 0, 0, 0, 0.7, 0.05, 0.61, cream, 0.012);
  for (let j = 0; j < 3; j++) box(receiptSlip, -0.04, 0.032, -0.13 + j * 0.095, 0.38, 0.012, 0.018, dark);
  receiptSlip.visible = false;

  // Three tracks form a window into the sorted, filtered native table.
  const tracks = [],
    maxBars = 18;
  for (let i = 0; i < 3; i++) {
    const row = group(field);
    row.userData.job = i;
    box(row, 0, -0.17, 0, 12.8, 0.27, 1.86, '#444b41', 0.07);
    box(row, 0, -0.017, 0, 12.72, 0.055, 1.78, '#292e29', 0.03);
    const name = plate(row, 3.86, -0.14, 0.94, 4.5, 0.23, '', '#282e27', '#f2f4e9', 104);
    const workerModel = worker(row, -5.3, 0, 0.12, '#b7d94a', i, true);
    workerModel.root.rotation.y = 0.4;
    const bars = Array.from({ length: maxBars }, () => box(row, 0, 0.04, 0, 1, 1, 1, '#d4d8c9', 0.035));
    const flags = bars.map(() => {
      const flag = group(row);
      cyl(flag, 0, 0.36, 0, 0.026, 0.026, 0.72, cream, 8);
      box(flag, 0.16, 0.58, 0, 0.34, 0.24, 0.04, '#eeb75b', 0.015);
      return flag;
    });
    tracks.push({ row, name, bars, flags, worker: workerModel, title: null });
  }
  let fieldMode = false,
    state = null,
    yaw = 0.32,
    dragging = null,
    pending = false,
    touched = -1e9,
    w = 0,
    h = 0;
  let elapsed = 0,
    idle = 0,
    drift = 0,
    previous = 0,
    packetX = spots[0][0],
    packetZ = spots[0][1],
    lastId = null;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  function redraw() {
    if (!pending && !document.hidden) {
      pending = true;
      requestAnimationFrame(frame);
    }
  }
  function resize() {
    w = host.clientWidth;
    h = host.clientHeight;
    if (w && h) renderer.setSize(w, h, false);
    redraw();
  }
  new ResizeObserver(resize).observe(host);
  document.addEventListener('visibilitychange', redraw);
  reduce.addEventListener('change', redraw);
  function update(next) {
    state = next;
    if (fieldMode !== state.field) {
      fieldMode = state.field;
      yaw = fieldMode ? 0.37 : 0.32;
    }
    field.visible = fieldMode;
    shop.visible = !fieldMode;
    const ground = fieldMode ? '#262c26' : state.dark ? '#405a50' : '#b7cabe';
    floor.material = mat(ground);
    scene.background = new T.Color(ground);
    tracks.forEach((track, i) => {
      const job = state.rows[i];
      track.row.visible = Boolean(job);
      if (!job) return;
      track.row.position.z = (i - (state.rows.length - 1) / 2) * 2.35;
      if (track.title !== job.name) {
        const texture = track.name.material.map,
          c = texture.image,
          ctx = c.getContext('2d');
        ctx.fillStyle = '#282e27';
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.fillStyle = '#f2f4e9';
        ctx.fillText(job.name, 384, 84, 740);
        texture.needsUpdate = true;
        track.title = job.name;
      }
      track.bars.forEach((bar, k) => {
        const bin = job.bars[k],
          flag = track.flags[k];
        bar.visible = Boolean(bin);
        flag.visible = Boolean(bin?.[1]);
        if (!bin) return;
        const [checked, blocked, omitted] = bin,
          gap = 9.6 / Math.max(9, job.bars.length);
        const height = 0.07 + checked * 0.83;
        bar.scale.set(gap * 0.75, height, 1.08);
        bar.position.set(-4.15 + k * gap, height / 2 + 0.04, 0);
        bar.material = mat(
          blocked ? '#eeb75b' : checked ? (job.id === state.selected ? '#e1e9b5' : '#b4c2b3') : omitted ? '#94a7b7' : '#697267',
        );
        flag.position.set(bar.position.x, height + 0.04, 0);
      });
      track.worker.arms[1].rotation.z = job.ask ? 2.3 : 0;
    });
    redraw();
  }
  const pick = new T.Raycaster();
  function selectAt(e) {
    const rect = canvas.getBoundingClientRect();
    const point = new T.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, 1 - ((e.clientY - rect.top) / rect.height) * 2);
    pick.setFromCamera(point, camera);
    for (const hit of pick.intersectObjects(
      (fieldMode ? field : shop).children.filter((o) => o.visible),
      true,
    )) {
      let o = hit.object;
      while (o) {
        if (o.userData.job != null) {
          const job = state.rows[o.userData.job];
          if (job) selectJob(job.id);
          return;
        }
        if (o.userData.station != null) {
          inspectStation(o.userData.station);
          return;
        }
        o = o.parent;
      }
    }
  }
  canvas.addEventListener('pointerdown', (e) => {
    touched = performance.now();
    dragging = { x: e.clientX, y: e.clientY, yaw };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (dragging) {
      touched = performance.now();
      yaw = Math.max(-0.75, Math.min(0.85, dragging.yaw + (e.clientX - dragging.x) * 0.005));
      redraw();
    }
  });
  canvas.addEventListener('pointerup', (e) => {
    if (dragging && Math.hypot(e.clientX - dragging.x, e.clientY - dragging.y) < 6) selectAt(e);
    dragging = null;
  });
  canvas.addEventListener('pointercancel', () => {
    dragging = null;
  });
  canvas.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    e.preventDefault();
    touched = performance.now();
    yaw = Math.max(-0.75, Math.min(0.85, yaw + (e.key === 'ArrowLeft' ? -0.12 : 0.12)));
    redraw();
  });
  function cameraPose() {
    const aspect = w / h;
    // Keep the entire row of machines in view on narrow screens.
    const half = Math.max(fieldMode ? 3.85 : 3.12, (fieldMode ? 7.35 : 7.85) / aspect);
    Object.assign(camera, { left: -half * aspect, right: half * aspect, top: half, bottom: -half });
    // A slow, small sway around the chosen angle; it holds still while the user is turning the scene.
    const turn = yaw + Math.sin(drift * 0.16) * 0.075,
      lift = Math.sin(drift * 0.11) * 0.35;
    camera.position.set(Math.sin(turn) * 16, (fieldMode ? 11.2 : 8.5) + lift, Math.cos(turn) * 16);
    camera.lookAt(0, fieldMode ? 0.3 : 0.6, 0);
    camera.updateProjectionMatrix();
  }
  function frame(now) {
    pending = false;
    if (!state || !w || !h || document.hidden) return;
    const job = state.rows.find((r) => r.id === state.selected);
    const work = job ? job.station : 0;
    const ambient = Boolean(state.motion && !reduce.matches);
    const animate = Boolean(job && job.moving && ambient);
    const dt = Math.min(0.07, (now - previous) / 1000);
    previous = now;
    if (animate) elapsed += dt;
    if (ambient) {
      idle += dt;
      if (!dragging && now - touched > 4000) drift += dt;
    }
    cameraPose();
    if (fieldMode) {
      tracks.forEach((track, i) => {
        const working = animate && state.rows[i]?.id === state.selected;
        rest(track.worker, i, ambient, working ? Math.sin(elapsed * 3) * 0.16 : 0);
      });
    } else {
      const [x, z] = spots[work],
        smooth = !animate || lastId !== job?.id ? 1 : 1 - Math.exp(-7 * dt);
      packetX += (x - packetX) * smooth;
      packetZ += (z - packetZ) * smooth;
      folder.position.set(packetX + 0.16, 1.18 + (animate ? Math.sin(elapsed * 4) * 0.025 : 0), packetZ + 0.24);
      folder.rotation.y = -0.13;
      lastId = job?.id;
      folder.visible = Boolean(job && !job.sent && !job.receipt);
      receiptSlip.visible = Boolean(job?.receipt);
      questionSign.visible = Boolean(job?.ask && work === 2);
      bots.forEach((b, i) => {
        const active = Boolean(job) && work === i,
          blocked = active && job.ask,
          moving = active && animate;
        b.root.position.x = moving ? -0.97 : -0.68;
        b.root.position.z = moving ? 0.44 : 0.89;
        b.root.rotation.y = moving ? 1.51 : 0.68;
        rest(b, i, ambient && !moving, blocked ? -0.6 : moving ? Math.sin(elapsed * 4) * 0.22 : -0.18);
        if (moving) {
          b.torso.rotation.x = 0.13 + 0.045 * Math.sin(elapsed * 5);
          b.arms[1].rotation.x = -0.9 + 0.45 * Math.sin(elapsed * 7);
          b.arms[0].rotation.x = -0.75 - 0.34 * Math.sin(elapsed * 7);
        }
        // The raised arm waits for the user; with motion on it waves the placard gently.
        b.arms[1].rotation.z = blocked ? 2.43 + (ambient ? Math.sin(idle * 2.2) * 0.07 : 0) : 0;
        bulbs[i].material = mat(active ? (blocked ? orange : yellow) : cream);
      });
    }
    renderer.render(scene, camera);
    if (ambient) redraw();
  }
  // Idle pose: breathing, a slow look around, an antenna sway and a blink every few seconds.
  // Each worker has its own phase so the crew never moves in unison. Nothing here moves the folder,
  // a lamp or a station: idle motion carries no information about the application.
  function rest(b, i, on, look) {
    const t = idle + i * 1.73;
    const blink = on && t % (4.6 + (i % 3) * 0.9) < 0.13;
    b.torso.position.y = 0.53 + (on ? Math.sin(t * 1.7) * 0.012 : 0);
    b.torso.rotation.x = on ? Math.sin(t * 1.7 + 0.6) * 0.022 : 0;
    b.head.rotation.y = look + (on ? Math.sin(t * 0.43) * 0.2 + Math.sin(t * 0.17) * 0.12 : 0);
    b.head.rotation.z = on ? Math.sin(t * 0.61) * 0.05 : 0;
    b.antenna.rotation.z = on ? Math.sin(t * 2.3) * 0.12 : 0;
    b.antenna.rotation.x = on ? Math.sin(t * 1.9 + 1) * 0.08 : 0;
    b.arms[0].rotation.x = on ? Math.sin(t * 1.7) * 0.06 : 0;
    b.arms[1].rotation.x = on ? Math.sin(t * 1.7 + 0.4) * 0.06 : 0;
    for (const eye of b.eyes) eye.scale.y = blink ? 0.15 : 1;
  }
  resize();
  return { update };
}
