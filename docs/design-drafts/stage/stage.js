/* Shell for the stage drafts: fictional queue, inspector and selection. The scene only ever receives
   ids, a company name, a station and a state, the same limit DESIGN.md sets for the real scene bridge. */
(() => {
  const D = document.documentElement.dataset.d, th = THEMES[D];
  const $ = (s) => document.querySelector(s);
  for (const [k, c] of Object.entries(th.s)) document.documentElement.style.setProperty('--s-' + k, c);

  const STATION = ['Intake', 'Fill', 'Verify', 'Dispatch'];
  const NOTE = ['opens the posting and loads your profile', 'writes known facts into the form', 'reads every field back', 'waits for your approval, then checks for a receipt'];
  const S = {
    needs: { label: 'Needs your answer', group: 'you' },
    ready: { label: 'Ready to approve', group: 'you' },
    run: { label: 'Filling form', group: 'progress' },
    queued: { label: 'Queued', group: 'progress' },
    sent: { label: 'Sent · receipt unconfirmed', group: 'applied' },
    ok: { label: 'Employer receipt confirmed', group: 'applied' },
  };
  const JOBS = [
    { id: 'lumen', co: 'Lumen Analytics', role: 'Data Science Intern', via: 'Lever', st: 2, state: 'needs', f: [8, 9], next: 'Answer 1 question', act: 'Answer questions',
      say: 'When can you start your internship?', ev: 'Just now · Checked the employer’s form.' },
    { id: 'fieldstone', co: 'Fieldstone Capital', role: 'Research Intern', via: 'Greenhouse', st: 3, state: 'ready', f: [14, 14], next: 'Review what was filled, then approve', act: 'Review application',
      say: 'Every field was read back from the employer’s form. Nothing is sent until you approve.', ev: '4 min ago · Verified 14 fields.' },
    { id: 'northwind', co: 'Northwind Labs', role: 'Software Intern', via: 'Workday', st: 1, state: 'run', f: [12, 31], next: 'Nothing needed from you', act: 'Show browser window',
      say: 'Writing known facts into section 2 of 4.', ev: 'Now · Filling “Education”.' },
    { id: 'harbor', co: 'Harbor Robotics', role: 'Robotics Intern', via: 'Ashby', st: 0, state: 'queued', f: [0, 0], next: 'Runs after Northwind Labs', act: 'Prepare now',
      say: 'Waiting in the queue. One application runs at a time.', ev: '12 min ago · Added from Scout.' },
    { id: 'orchard', co: 'Orchard Pay', role: 'Software Intern', via: 'SmartRecruiters', st: 0, state: 'queued', f: [0, 0], next: 'Runs after Harbor Robotics', act: 'Prepare now',
      say: 'Waiting in the queue. One application runs at a time.', ev: '15 min ago · Link pasted.' },
    { id: 'atlas', co: 'Atlas Freight', role: 'Operations Analyst Intern', via: 'Workday', st: 3, state: 'sent', f: [22, 22], next: 'Check for the employer’s receipt', act: 'Check receipt',
      say: 'Sent once. The employer has not shown a receipt yet, so this is not counted as applied.', ev: 'Yesterday · Send clicked once.' },
    { id: 'kestrel', co: 'Kestrel Bio', role: 'Lab Automation Intern', via: 'Greenhouse', st: 3, state: 'ok', f: [17, 17], next: 'Waiting to hear back', act: 'Tracking and notes',
      say: 'The employer’s confirmation page was recognised.', ev: '2 days ago · Receipt confirmed.' },
  ];
  const done = (j) => S[j.state].group === 'applied';
  const dot = (s) => `<i class="dot" data-s="${s}"></i>`;
  let selected = JOBS[0].id, filter = 'all', stage = null;

  const you = JOBS.filter((j) => S[j.state].group === 'you');
  $('#headline').textContent = `${you.length} applications are waiting on you`;
  $('#sub').textContent = '1 question to answer and 1 review to approve. Northwind Labs is being filled now.';
  $('#badge').textContent = you.length;

  const groups = [['all', 'All'], ['you', 'Needs you'], ['progress', 'In progress'], ['applied', 'Applied']];
  $('#filters').innerHTML = groups
    .map(([g, name]) => `<button type="button" data-g="${g}" aria-pressed="${g === filter}">${name} <span>${JOBS.filter((j) => g === 'all' || S[j.state].group === g).length}</span></button>`)
    .join('');
  $('#rows').innerHTML = JOBS.map(
    (j) => `<button type="button" class="row" data-id="${j.id}" data-g="${S[j.state].group}">${dot(j.state)}<b>${j.co}</b><span class="role">${j.role}</span><span class="st">${S[j.state].label}</span><span class="next">${j.next}</span></button>`,
  ).join('');

  function select(id) {
    selected = id;
    const j = JOBS.find((x) => x.id === id), s = S[j.state];
    for (const r of document.querySelectorAll('.row')) r.setAttribute('aria-pressed', r.dataset.id === id);
    const steps = STATION.map((n, i) => {
      const kind = done(j) || i < j.st ? 'done' : i === j.st ? 'now' : 'todo';
      return `<li data-k="${kind}"${kind === 'now' ? ' aria-current="step"' : ''}>${n}</li>`;
    }).join('');
    $('#inspector').innerHTML = `
      <h2>${j.co}</h2>
      <p class="role">${j.role} · ${j.via}</p>
      <p class="status">${dot(j.state)}${s.label}</p>
      <p class="say"${j.state === 'needs' ? ' data-q' : ''}>${j.say}</p>
      <div class="acts"><button type="button" class="primary">${j.act}</button><button type="button" class="quiet">More actions</button></div>
      <ol class="steps" aria-label="Stations">${steps}</ol>
      <p class="fields">${j.f[1] ? `<b>${j.f[0]}</b> of ${j.f[1]} fields verified` : 'No fields checked yet'}</p>
      <div class="meter" aria-hidden="true"><i style="width:${j.f[1] ? (j.f[0] / j.f[1]) * 100 : 0}%"></i></div>
      <p class="ev">${j.ev}</p>
      <p class="ev">Prepared with profile: Default</p>`;
    if (D === 'orbit') document.querySelector('.row[aria-pressed=true]').after($('#inspector'));
    $('#place h3').textContent = j.state === 'ok' || j.state === 'sent' ? 'Applied' : STATION[j.st];
    $('#place p').textContent =
      j.state === 'ok' ? 'The employer confirmed this one' : j.state === 'sent' ? 'Sent once, waiting for the employer’s receipt' : `Station ${j.st + 1} of 4 · ${NOTE[j.st]}`;
    if (stage) stage.select(id, `<b>${j.co}</b><span>${dot(j.state)}${s.label}</span>`);
  }

  $('#rows').addEventListener('click', (e) => {
    const r = e.target.closest('.row');
    if (r) select(r.dataset.id);
  });
  $('#rows').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const rows = [...document.querySelectorAll('.row:not([hidden])')];
    const next = rows[rows.indexOf(document.activeElement) + (e.key === 'ArrowDown' ? 1 : -1)];
    if (!next) return;
    e.preventDefault();
    next.focus();
    select(next.dataset.id);
  });
  $('#filters').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    filter = b.dataset.g;
    for (const x of $('#filters').children) x.setAttribute('aria-pressed', x === b);
    for (const r of document.querySelectorAll('.row')) r.hidden = filter !== 'all' && r.dataset.g !== filter;
  });
  $('#views').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || !stage) return;
    for (const x of $('#views').children) x.setAttribute('aria-pressed', x === b);
    stage.view(b.textContent);
  });
  $('#ask').addEventListener('submit', (e) => {
    e.preventDefault();
    $('#asknote').textContent = 'This is a draft: links are not opened here.';
  });
  for (const a of document.querySelectorAll('.drafts a')) if (a.search === '?d=' + D) a.setAttribute('aria-current', 'page');

  try {
    stage = makeStage($('#stage'), $('#labels'), D, JOBS.map(({ id, co, st, state }) => ({ id, co, st, state })), select);
  } catch (err) {
    console.error(err);
    $('#stage').innerHTML = '<p class="nogl">The 3D view needs WebGL. The queue and inspector still work.</p>';
  }
  select(selected);
})();
