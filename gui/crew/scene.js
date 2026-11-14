/* Orbit chart and Bar field. Display only: the scene draws what gui/workshop.py sends and can ask Qt to
   select a visible row or explain a station; it never changes an application. */
function makeCrewScene(host, selectJob, inspectStation) {
  const T = window.THREE;
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  // Always render at 2x: on a standard-density display this supersamples the thin orbit lines.
  renderer.setPixelRatio(2);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFShadowMap;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', '3D orbit chart. Drag, or use the left and right arrow keys, to turn it.');
  host.prepend(canvas);
  const overlay = document.getElementById('overlay');
  const scene = new T.Scene(),
    camera = new T.OrthographicCamera(-1, 1, 1, -1, 1, 400);
  const sun = new T.DirectionalLight(0xffe9c9, 2.3);
  sun.position.set(-6, 12, 8);
  sun.castShadow = true;
  Object.assign(sun.shadow.camera, { left: -10, right: 10, top: 9, bottom: -9, near: 2, far: 40 });
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.radius = 4;
  sun.shadow.bias = -0.0004;
  scene.add(sun, new T.AmbientLight(0xc4ccff, 1.15));

  const mats = new Map(),
    geos = new Map();
  const memo = (m, key, make) => m.get(key) || (m.set(key, make()), m.get(key));
  const mat = (c, glow = 0) =>
    memo(mats, c + '|' + glow, () => new T.MeshStandardMaterial({ color: c, roughness: 0.78, emissive: glow ? c : '#000000', emissiveIntensity: glow }));
  const clear = (c, o, glow = 0) =>
    memo(mats, ['c', c, o, glow].join(), () => new T.MeshStandardMaterial({ color: c, roughness: 1, transparent: o < 1, opacity: o, side: 2, depthWrite: o >= 1, emissive: glow ? c : '#000000', emissiveIntensity: glow }));
  function put(p, g, m, x, y, z) {
    const o = new T.Mesh(g, typeof m === 'string' ? mat(m) : m);
    o.position.set(x, y, z);
    o.castShadow = o.receiveShadow = true;
    p.add(o);
    return o;
  }
  const group = (p, x = 0, y = 0, z = 0) => {
    const g = new T.Group();
    g.position.set(x, y, z);
    p.add(g);
    return g;
  };
  const box = (p, x, y, z, w, h, d, c, r = 0) =>
    put(p, memo(geos, ['b', w, h, d, r].join(), () => (r ? new T.RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2, h / 2, d / 2)) : new T.BoxGeometry(w, h, d))), c, x, y, z);
  const ball = (p, x, y, z, r, c) => put(p, memo(geos, 's' + r, () => new T.SphereGeometry(r, 28, 18)), c, x, y, z);
  const disc = (p, y, r, c) => put(p, new T.CylinderGeometry(r, r, 0.02, 128), c, 0, y, 0);
  // A flat ring or arc lying in the orbit plane. Angle 0 faces the default camera, positive angles go right.
  function ring(p, r, w, y, m, a0 = 0, len = Math.PI * 2) {
    const key = 'r' + [r, w, a0, len].map((n) => +n.toFixed(3)).join();
    const o = put(p, memo(geos, key, () => new T.CylinderGeometry(r - w / 2, r + w / 2, 0.001, Math.max(12, Math.round(len * 30)), 1, true, a0, len)), m, 0, y, 0);
    o.castShadow = false; // a line on the chart, not an object above it
    return o;
  }
  const at = (a, r, y = 0) => new T.Vector3(Math.sin(a) * r, y, Math.cos(a) * r);

  function label(cls, onClick) {
    const el = document.createElement(onClick ? 'button' : 'div');
    el.className = 'wl ' + cls;
    el.hidden = true;
    if (onClick) {
      el.type = 'button';
      el.addEventListener('click', onClick);
    }
    overlay.append(el);
    return { el, pos: new T.Vector3(), on: true };
  }

  /* Orbit chart */
  const chalk = '#eef0fa',
    sky = group(scene);
  const EASE = 'cubic-bezier(0.16, 1, 0.3, 1)';
  const STATIONS = ['Intake', 'Fill', 'Verify', 'Dispatch'],
    ORBITS = [...STATIONS, 'Applied', 'Closed'],
    R = [7.8, 6.2, 4.6, 3.0],
    CORE = 1.9,
    RIM = 8.9;
  const RADII = [...R, CORE, RIM],
    TAU = Math.PI * 2;
  disc(sky, -0.04, RIM, clear('#1c2556', 0.6)).renderOrder = -1; // draw the chart's ground before the lines on it
  // Lines start invisible and ease to their resting opacity, so the chart draws itself in on first show.
  function line(r, w, rest) {
    const o = ring(sky, r, w, 0, clear(chalk, 0.5, 1).clone());
    o.material.opacity = 0;
    o.userData.rest = rest;
    return o;
  }
  const lines = [...R.map((r) => line(r, 0.035, 0.38)), line(CORE, 0.025, 0.3), line(RIM, 0.025, 0.22)];
  const spoke = clear(chalk, 0.1, 1);
  for (let a = 0; a < 24; a++) {
    const g = group(sky);
    g.rotation.y = (a * Math.PI) / 12;
    box(g, 0, 0, 5.25, 0.014, 0.002, 7.3, spoke).castShadow = false;
  }
  const rnd = (i, s) => (((Math.sin(i * 127.1 + s * 311.7) * 43758.5453) % 1) + 1) % 1;
  // Four star materials twinkle out of phase.
  const starMats = [0, 1, 2, 3].map(() => new T.MeshStandardMaterial({ color: '#39437c', roughness: 1, emissive: chalk, emissiveIntensity: 1 }));
  for (let i = 0; i < 260; i++) {
    const sx = rnd(i, 1) * 80 - 40,
      sz = rnd(i, 2) * 80 - 40;
    if (Math.hypot(sx, sz) > 9.8) ball(sky, sx, -1.2, sz, 0.02 + rnd(i, 3) ** 3 * 0.06, starMats[i % 4]).castShadow = false;
  }
  const sunMat = mat('#ffd596', 1).clone();
  ball(sky, 0, 0.25, 0, 0.95, sunMat);
  // Thin nested shells add up to a soft glow; they breathe slowly and flare when an application reaches Applied.
  const halos = Array.from({ length: 9 }, (_, i) => {
    const shell = ball(sky, 0, 0.25, 0, 1.02 + (i / 8) ** 1.5 * 0.95, clear('#ffd596', 0.035, 1));
    shell.castShadow = shell.receiveShadow = false;
    return shell;
  });
  // One spinning group per orbit; idle rotation moves bodies along their orbit, never between orbits.
  const lanes = [...R, CORE, RIM].map(() => group(sky));
  const CENTRE = [-1.6, 2.4, -0.5, 0.35, 2.6, -2.5],
    SPIN = [0.012, 0.03, 0.016, 0.022, 0.04, 0.004];
  // Four turning brackets, so the selection never reads as the flat "Ready to approve" ring.
  const reticle = group(sky);
  for (let k = 0; k < 4; k++) ring(reticle, 0.92, 0.045, 0, clear(chalk, 1, 1), (k * Math.PI) / 2 + 0.22, Math.PI / 2 - 0.44);
  reticle.visible = false;
  const effects = group(sky);
  const hit = clear('#000000', 0);
  const stationTags = STATIONS.map((name, i) => {
    const l = label('station', () => inspectStation(i));
    l.pos.copy(at(1.62, R[i], 0.12)); // a ruler of labels on the right, clear of the busy centre
    l.el.title = `What ${name} does`;
    l.below = i % 2 === 1; // neighbours alternate above and below the ruler so their pills never overlap
    // Pointing at a station name lights its orbit.
    for (const [type, n] of [['pointerenter', i], ['pointerleave', -1], ['focus', i], ['blur', -1]])
      l.el.addEventListener(type, () => {
        hoverLane = n;
        redraw();
      });
    return l;
  });
  const coreTag = label('station core'),
    rimTag = label('station rim'),
    moreTags = [...R, CORE, RIM].map(() => label('more')),
    focusTag = label('tag'),
    hoverTag = label('tag hover'),
    emptyTag = label('empty');
  coreTag.pos.set(0, 2.8, 0); // above the far side of the Applied orbit, so it never covers a planet there
  rimTag.pos.copy(at(-2.05, RIM, 0.1));
  emptyTag.el.textContent = 'No applications in this view';
  let bodies = new Map(),
    spinning = [],
    runner = null,
    fx = [],
    intro = true,
    flare = 0,
    pop = 0,
    pingIn = 0,
    hovered = null,
    hoverLane = -1,
    selLane = -1;
  const outCubic = (t) => 1 - (1 - t) ** 3,
    inOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
  // A timed effect: step(t) runs each frame with t from 0 to 1, then done() removes what it drew.
  function play(life, step, done, delay = 0) {
    if (ambient()) fx.push({ life, step, done, age: -delay });
  }
  function ripple(parent, color, r0, r1, life, w = 0.1, peak = 0.9, y = 0) {
    if (!ambient()) return;
    const m = clear(color, 0.5, 1).clone(), // any opacity below 1 makes the material transparent
      o = ring(parent, 1, w, y, m);
    o.visible = false;
    play(
      life,
      (t) => {
        const s = r0 + (r1 - r0) * outCubic(t);
        o.visible = true;
        o.scale.set(s, 1, s);
        m.opacity = peak * (1 - t) ** 1.5;
      },
      () => {
        o.removeFromParent();
        m.dispose();
      },
    );
  }
  // A planet settles after a change: a ring in its tone, and the sun answers when it reaches Applied.
  function arrive(b, hop) {
    ripple(b.g, b.row.color, b.size * 1.2, b.size * 3.6, 0.9);
    if (hop && b.lane === 4) {
      flare = 1;
      ripple(sky, '#ffd596', 1.1, RIM, 1.6, 0.014, 0.55, 0.03);
    }
  }

  function lane(row) {
    return row.group === 'Closed' ? 5 : row.group === 'Applied' ? 4 : row.station;
  }
  function buildOrbit(rows, selected) {
    // Remember where every planet was so a checkpoint reads as travel, not a jump cut.
    const live = ambient(),
      old = new Map();
    if (live) for (const [id, b] of bodies) old.set(id, { A: Math.atan2(b.pos.x, b.pos.z), R: Math.hypot(b.pos.x, b.pos.z), sig: b.sig, lane: b.lane, s: b.s, size: b.size, color: b.row.color });
    for (const g of lanes) g.clear();
    bodies = new Map();
    spinning = [];
    runner = null;
    const buckets = lanes.map(() => []);
    for (const row of rows) buckets[lane(row)].push(row);
    buckets.forEach((list, i) => {
      const r = RADII[i],
        cap = Math.floor((2 * Math.PI * r) / (i === 5 ? 0.45 : 0.95));
      // Keep the selected body on the chart even when its orbit is full.
      let shown = list.slice(0, cap);
      const pick = list.find((row) => row.id === selected);
      if (pick && !shown.includes(pick)) shown = [...shown.slice(0, cap - 1), pick];
      const step = Math.min((2 * Math.PI) / Math.max(1, shown.length), i === 5 ? 0.3 : 0.9);
      shown.forEach((row, k) => {
        const a = CENTRE[i] + (k - (shown.length - 1) / 2) * step;
        bodies.set(row.id, planet(i, row, a, r));
      });
      const more = moreTags[i];
      more.on = list.length > shown.length;
      more.el.textContent = `+${list.length - shown.length} more`;
      more.pos.copy(at(CENTRE[i] + (shown.length / 2 + 0.6) * step, r, 0.1));
    });
    [...stationTags, coreTag, rimTag].forEach((l, i) => {
      const was = l.el.querySelector('i')?.textContent,
        n = String(buckets[i].length);
      l.el.innerHTML = `<b>${ORBITS[i]}</b><i>${n}</i>`;
      // A count that changed blinks once.
      if (live && was != null && was !== n) l.el.querySelector('i').animate([{ background: 'rgba(255,255,255,.55)', transform: 'scale(1.25)' }, {}], { duration: 500, easing: EASE });
    });
    rimTag.on = buckets[5].length > 0;
    emptyTag.on = rows.length === 0;
    if (!live) return;
    const fresh = [...bodies.keys()].filter((id) => !old.has(id)),
      crowd = intro || fresh.length > 2;
    let n = 0;
    for (const [id, b] of bodies) {
      const was = old.get(id);
      if (!was) {
        // One new application announces itself; a filter change or first show sweeps in quietly.
        b.s = 0.001;
        b.wait = crowd ? Math.min(0.5, n++ * 0.035) : 0;
        b.ping = !crowd;
        continue;
      }
      const hop = was.lane !== b.lane;
      b.s = was.s;
      b.from = { A: was.A, R: was.R, t: 0, life: hop ? 1.1 : 0.5, lift: hop ? 0.7 : 0 };
      if (hop || was.sig !== b.sig) b.land = () => arrive(b, hop);
    }
    for (const [id, was] of old) {
      if (bodies.has(id)) continue;
      const o = ball(effects, Math.sin(was.A) * was.R, 0.25, Math.cos(was.A) * was.R, was.size, mat(was.color, 0.3));
      o.castShadow = false;
      play(0.22, (t) => o.scale.setScalar(Math.max(0.001, was.s * (1 - t))), () => o.removeFromParent());
    }
    intro = false;
  }
  function planet(i, row, a, r) {
    const parent = lanes[i],
      p = at(a, r, 0.25),
      g = group(parent, p.x, p.y, p.z),
      closed = row.group === 'Closed';
    g.userData.job = row.id;
    const hollow = row.sent && !row.receipt && row.group !== 'Applied';
    const size = closed ? 0.13 : row.moving ? 0.34 : row.group === 'Needs you' ? 0.36 : row.group === 'Applied' ? 0.24 : hollow ? 0.27 : 0.23;
    const color = row.color;
    const core = ball(g, 0, 0, 0, size, hollow ? clear(color, 0.22, 0.5) : mat(color, closed ? 0.15 : row.group === 'In progress' && !row.moving ? 0.3 : 0.7));
    ball(g, 0, 0, 0, Math.max(0.6, size * 1.7), hit).castShadow = false;
    if (hollow) ring(g, size * 1.15, 0.06, 0, clear(color, 1, 1));
    if (row.ask) {
      const o = ring(g, size * 1.8, 0.08, 0, clear(color, 1, 1));
      o.rotation.x = 1.05;
      spinning.push(o);
    } else if (row.ready) ring(g, size * 1.85, 0.045, 0, clear(color, 1, 1));
    // A moon is the employer's receipt: only a recognised confirmation draws it.
    if (row.receipt) ball(g, size + 0.16, 0.08, 0, 0.07, mat(chalk, 0.8));
    const b = { g, core, row, size, a, r, lane: i, s: 1, wait: 0, pos: p, sig: [i, row.ask, row.ready, hollow, row.receipt, row.moving, color].join() };
    if (row.moving) {
      // The comet: a tail that tapers and fades behind the one application being worked on.
      b.tail = group(parent);
      b.tail.rotation.y = a;
      for (let k = 0; k < 8; k++) ring(b.tail, r, 0.12 - k * 0.012, 0.25, clear(color, +(0.85 * (1 - k / 8) ** 1.6).toFixed(2), 1), -0.07 - (k + 1) * 0.085, 0.085);
      runner = b;
    }
    return b;
  }

  /* Bar field: three tracks form a window into the sorted, filtered native table. */
  const field = group(scene);
  field.visible = false;
  const tracks = [],
    maxBars = 18;
  function plate(p, w, h) {
    const c = document.createElement('canvas');
    c.width = 1024;
    c.height = 128;
    const tex = new T.CanvasTexture(c);
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const o = put(p, new T.PlaneGeometry(w, h), new T.MeshStandardMaterial({ map: tex, roughness: 1, transparent: true }), 0, 0, 0);
    o.castShadow = false;
    o.rotation.x = -Math.PI / 2;
    return o;
  }
  for (let i = 0; i < 3; i++) {
    const row = group(field);
    row.userData.job = i;
    box(row, 0, -0.17, 0, 12.8, 0.27, 1.86, '#1a2150', 0.07);
    box(row, 0, -0.017, 0, 12.72, 0.055, 1.78, '#11173a', 0.03);
    // The name lies on the left of its own track so the bars in front never hide it.
    const name = plate(row, 4, 0.5);
    name.position.set(-4.25, 0.015, 0);
    const bars = Array.from({ length: maxBars }, () => box(row, 0, 0.04, 0, 1, 1, 1, '#d9def5', 0.035));
    const flags = bars.map(() => {
      const flag = group(row);
      box(flag, 0, 0.36, 0, 0.05, 0.72, 0.05, chalk);
      box(flag, 0.16, 0.6, 0, 0.32, 0.22, 0.04, mat('#ffb347', 0.4), 0.015);
      return flag;
    });
    tracks.push({ row, name, bars, flags, title: null });
  }
  function buildField(rows, selected, grow) {
    tracks.forEach((track, i) => {
      const job = rows[i];
      track.row.visible = Boolean(job);
      if (!job) return;
      track.row.position.z = (i - (rows.length - 1) / 2) * 2.6;
      const tex = track.name.material.map,
        ctx = tex.image.getContext('2d');
      ctx.clearRect(0, 0, 1024, 128);
      ctx.fillStyle = job.id === selected ? '#ffb347' : chalk;
      ctx.font = '500 64px Futura, "Avenir Next", sans-serif';
      ctx.textBaseline = 'middle';
      ctx.fillText(job.name, 8, 66, 1000);
      tex.needsUpdate = true;
      track.bars.forEach((bar, k) => {
        const bin = job.bars[k],
          flag = track.flags[k];
        bar.visible = Boolean(bin);
        flag.visible = Boolean(bin?.[1]);
        if (!bin) return;
        const [checked, blocked, omitted] = bin,
          gap = 8.2 / Math.max(9, job.bars.length);
        // The frame loop eases each bar to its height; entering the view grows them in a sweep.
        const u = bar.userData;
        Object.assign(u, { x: -2.05 + gap / 2 + k * gap, gap, goal: 0.07 + checked * 1.1 });
        if (grow || u.h == null) Object.assign(u, { h: 0, wait: i * 0.06 + k * 0.018 });
        bar.material = blocked ? mat('#ffb347', 0.35) : mat(checked ? (job.id === selected ? '#ffffff' : '#c3cae6') : omitted ? '#7f89b3' : '#3a4580');
      });
    });
  }

  /* Camera, picking and the frame loop */
  const PRESETS = { '3D': { yaw: 0.3, pitch: 0.72 }, Top: { yaw: 0, pitch: 1.5 }, Side: { yaw: 0.3, pitch: 0.14 } };
  const FIELD = { yaw: 0.35, pitch: 0.78 };
  const presetButtons = [...document.querySelectorAll('#presets button')];
  let state = null,
    fieldMode = false,
    goal = { ...PRESETS['3D'] },
    yaw = goal.yaw,
    pitch = goal.pitch,
    half = 0,
    w = 0,
    h = 0,
    drag = null,
    touched = -1e9,
    spin = 0,
    previous = 0,
    pending = false,
    built = '';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const v = new T.Vector3(),
    ray = new T.Raycaster(),
    pt = new T.Vector2();
  const ambient = () => Boolean(state && state.motion && !reduce.matches);
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
  function choose(name) {
    goal = { ...(fieldMode && name === '3D' ? FIELD : PRESETS[name]) };
    for (const b of presetButtons) b.setAttribute('aria-pressed', b.textContent === name);
    touched = performance.now();
    redraw();
  }
  for (const b of presetButtons) b.addEventListener('click', () => choose(b.textContent));

  function update(next) {
    const modeChanged = !state || state.field !== next.field,
      before = state;
    state = next;
    host.classList.toggle('still', !ambient());
    // Changing view dips the canvas so the chart and the Bar field do not cut into each other.
    if (before && modeChanged && ambient()) canvas.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, easing: EASE });
    fieldMode = state.field;
    sky.visible = !fieldMode;
    field.visible = fieldMode;
    if (modeChanged) choose('3D');
    // Rebuild the chart only when the rows change; a new selection only moves the marker and the tag.
    const key = JSON.stringify(state.rows);
    if (fieldMode) buildField(state.rows, state.selected, modeChanged);
    else if (modeChanged || key !== built || (state.rows.some((r) => r.id === state.selected) && !bodies.has(state.selected)))
      buildOrbit(state.rows, state.selected);
    built = key;
    const row = state.rows.find((r) => r.id === state.selected);
    document.getElementById('place').hidden = fieldMode || !row;
    selLane = row && !fieldMode ? lane(row) : -1;
    if (selLane >= 0) {
      const title = document.querySelector('#place h1');
      if (title.textContent !== ORBITS[selLane]) {
        title.textContent = ORBITS[selLane];
        if (ambient()) title.animate([{ opacity: 0, transform: 'translateY(8px)' }, {}], { duration: 420, easing: EASE });
      }
      // Past the stations the status often repeats the orbit's name; the employer says more.
      document.querySelector('#place p').textContent = selLane < 4 ? `Orbit ${selLane + 1} of 4 · ${row.status}` : row.status === ORBITS[selLane] ? row.name : row.status;
    }
    focusTag.el.innerHTML = row ? `<b></b><span><i></i></span>` : '';
    if (row) {
      focusTag.el.querySelector('b').textContent = row.name;
      focusTag.el.querySelector('span').append(row.status);
      focusTag.el.querySelector('i').style.background = row.color;
    }
    if (before && before.selected !== state.selected) {
      pop = 1; // the reticle closes in on the new selection
      if (ambient()) focusTag.el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 260, easing: 'ease-out' });
    }
    redraw();
  }

  function jobAt(e) {
    const rect = canvas.getBoundingClientRect();
    pt.set(((e.clientX - rect.left) / rect.width) * 2 - 1, 1 - ((e.clientY - rect.top) / rect.height) * 2);
    ray.setFromCamera(pt, camera);
    for (const hitResult of ray.intersectObjects((fieldMode ? field : sky).children.filter((o) => o.visible), true))
      for (let o = hitResult.object; o; o = o.parent) {
        const id = o.userData.job;
        if (id == null) continue;
        return fieldMode ? state.rows[id]?.id : id;
      }
    return null;
  }
  canvas.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, y: e.clientY, yaw: goal.yaw, pitch: goal.pitch };
    touched = performance.now();
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) {
      const id = (state && jobAt(e)) || null;
      canvas.style.cursor = id ? 'pointer' : 'grab';
      if (id !== hovered) {
        hovered = id;
        redraw();
      }
      return;
    }
    goal.yaw = clamp(drag.yaw - (e.clientX - drag.x) * 0.005, -1.3, 1.3);
    goal.pitch = clamp(drag.pitch + (e.clientY - drag.y) * 0.004, 0.1, 1.5);
    touched = performance.now();
    redraw();
  });
  canvas.addEventListener('pointerup', (e) => {
    const id = drag && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6 && jobAt(e);
    drag = null;
    if (id) selectJob(id);
  });
  canvas.addEventListener('pointercancel', () => (drag = null));
  canvas.addEventListener('pointerleave', () => {
    hovered = null;
    redraw();
  });
  canvas.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    goal.yaw = clamp(goal.yaw + (e.key === 'ArrowLeft' ? 0.15 : -0.15), -1.3, 1.3);
    touched = performance.now();
    redraw();
  });

  function pose(sway) {
    const sp = Math.sin(pitch),
      cp = Math.cos(pitch),
      aspect = w / h;
    // Frame the chart in the canvas below the title and presets.
    const top = 64,
      side = 16,
      bottom = 14;
    const fw = Math.max(200, w - 2 * side),
      fh = Math.max(150, h - top - bottom);
    const span = fieldMode ? 13.6 : 2 * RIM + 0.6,
      depth = fieldMode ? 8 : 2 * RIM + 0.6,
      height = fieldMode ? 2.2 : 2.6;
    const need = Math.max((span * h) / (2 * fw), ((depth * sp + height * cp) * h) / (2 * fh));
    // The first frame starts slightly wide and settles in.
    half = half ? half + (need - half) * 0.2 : need * (ambient() ? 1.12 : 1);
    const sy = (1 - ((top + fh / 2) / h) * 2) * half;
    Object.assign(camera, { left: -half * aspect, right: half * aspect, top: half - sy, bottom: -half - sy });
    const turn = yaw + sway;
    camera.position.set(Math.sin(turn) * cp * 90, (fieldMode ? 0.4 : 0) + sp * 90, Math.cos(turn) * cp * 90);
    camera.lookAt(0, fieldMode ? 0.4 : 0, 0);
    camera.updateProjectionMatrix();
  }
  function frame(now) {
    pending = false;
    if (!state || !w || !h || document.hidden) return;
    const move = ambient(),
      dt = Math.min(0.07, (now - previous) / 1000 || 0);
    previous = now;
    if (move) spin += dt;
    const ease = move ? 1 - Math.exp(-8 * dt) : 1;
    yaw += (goal.yaw - yaw) * ease;
    pitch += (goal.pitch - pitch) * ease;
    // A slow sway around the chosen angle, held for four seconds after the user turns the chart.
    const sway = move && !drag && now - touched > 4000 ? Math.sin(spin * 0.25) * 0.05 : 0;
    pose(sway);
    // Everything below eases toward its target; with motion off, k is 1 and each value lands at once.
    const k = (rate) => (move ? 1 - Math.exp(-rate * dt) : 1);
    lanes.forEach((g, i) => (g.rotation.y = spin * SPIN[i]));
    for (const o of spinning) {
      o.rotation.y = spin * 1.2;
      o.scale.setScalar(1 + Math.sin(spin * 2.4) * 0.05);
    }
    for (const [id, b] of bodies) {
      const th = lanes[b.lane].rotation.y;
      let A = b.a + th,
        rr = b.r,
        lift = 0;
      if (b.from) {
        // Travel in polar coordinates, so a checkpoint spirals the planet onto its new orbit.
        const f = b.from;
        f.t = move ? Math.min(1, f.t + dt / f.life) : 1;
        const e = inOut(f.t),
          d = ((((A - f.A + Math.PI) % TAU) + TAU) % TAU) - Math.PI;
        A = f.A + d * e;
        rr = f.R + (b.r - f.R) * e;
        lift = Math.sin(Math.PI * e) * f.lift;
        if (f.t >= 1) {
          b.from = null;
          if (b.land) b.land();
          b.land = null;
        }
      }
      b.pos.set(Math.sin(A) * rr, 0.25 + lift, Math.cos(A) * rr);
      b.g.position.set(Math.sin(A - th) * rr, 0.25 + lift, Math.cos(A - th) * rr);
      if (b.wait > 0 && move) b.wait -= dt;
      else {
        if (b.ping) arrive(b, false);
        b.ping = false;
        b.s += ((id === state.selected ? 1.3 : 1) * (id === hovered ? 1.12 : 1) - b.s) * k(14);
      }
      b.g.scale.setScalar(b.s);
      if (b.tail) b.tail.visible = !b.from;
    }
    // The application being worked on sends out a slow ping.
    if (move && runner && !runner.from && (pingIn -= dt) <= 0) {
      pingIn = 1.8;
      ripple(runner.g, runner.row.color, runner.size * 1.1, runner.size * 3.2, 1.4, 0.1, 0.7);
    }
    fx = fx.filter((f) => {
      f.age += move ? dt : f.life;
      if (f.age < 0) return true;
      const t = Math.min(1, f.age / f.life);
      f.step(t);
      if (t >= 1) f.done();
      return t < 1;
    });
    flare += -flare * k(2.2);
    pop += -pop * k(9);
    sunMat.emissiveIntensity = 1 + flare * 0.9;
    halos.forEach((shell, i) => shell.scale.setScalar(1 + (Math.sin(spin * 0.9) * 0.012 + flare * 0.06) * (i + 1)));
    starMats.forEach((m, i) => (m.emissiveIntensity = 0.65 + 0.35 * Math.sin(spin * (0.7 + i * 0.23) + i * 1.7)));
    lines.forEach((o, i) => {
      const goal = fieldMode ? 0 : i === selLane ? (i === 5 ? 0.9 : 1) : o.userData.rest + (i === hoverLane ? 0.34 : 0);
      o.material.opacity += (goal - o.material.opacity) * k(i === selLane || i === hoverLane ? 12 : 5);
    });
    if (fieldMode)
      for (const track of tracks)
        track.bars.forEach((bar, n) => {
          const u = bar.userData;
          if (!bar.visible) return;
          if (u.wait > 0 && move) u.wait -= dt;
          else u.h += (u.goal - u.h) * k(10);
          const hgt = Math.max(0.001, u.h),
            flag = track.flags[n];
          bar.scale.set(u.gap * 0.72, hgt, 1.08);
          bar.position.set(u.x, hgt / 2 + 0.04, 0);
          flag.position.set(u.x, hgt + 0.04, 0);
          flag.scale.setScalar(clamp((u.h / u.goal - 0.6) / 0.4, 0.001, 1));
        });
    const chosen = bodies.get(state.selected);
    if (chosen && !fieldMode) {
      // The reticle glides from the last selection instead of jumping.
      if (reticle.visible) reticle.position.lerp(chosen.pos, k(16));
      else reticle.position.copy(chosen.pos);
      reticle.scale.setScalar((chosen.size / 0.36) * (1 + pop * 0.7));
      reticle.rotation.y = spin * 0.35;
      focusTag.pos.copy(reticle.position).setY(reticle.position.y + chosen.size * 1.3 + 0.5);
    }
    reticle.visible = Boolean(chosen) && !fieldMode;
    const near = hovered !== state.selected && bodies.get(hovered);
    hoverTag.on = Boolean(near);
    if (near) {
      hoverTag.el.textContent = near.row.name;
      hoverTag.pos.copy(near.pos).setY(near.pos.y + near.size * 1.3 + 0.3);
    }
    renderer.render(scene, camera);
    const labels = [...stationTags, coreTag, rimTag, ...moreTags, emptyTag, hoverTag, focusTag];
    for (const l of labels) {
      const show = !fieldMode && l.on && (l !== focusTag || Boolean(chosen));
      l.el.hidden = !show;
      if (!show) continue;
      if (l === emptyTag) {
        l.el.style.transform = `translate(${w / 2}px,${h / 2}px) translate(-50%,-50%)`;
        continue;
      }
      v.copy(l.pos);
      if (l.el.classList.contains('more')) lanes[moreTags.indexOf(l)].localToWorld(v);
      v.project(camera);
      l.el.style.transform = `translate(${(((v.x + 1) / 2) * w).toFixed(1)}px,${(((1 - v.y) / 2) * h).toFixed(1)}px) translate(-50%,${l.below ? '6px' : '-100%'})`;
    }
    if (move || Math.abs(goal.yaw - yaw) + Math.abs(goal.pitch - pitch) > 0.001) redraw();
  }
  resize();
  return { update };
}
