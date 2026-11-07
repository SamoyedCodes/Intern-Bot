/* Monee (careers.monee.com): one Ant Design page. A native adapter is a factory taking the runtime gate R (runtime.js).
   fill:'direct' lets the runtime write desktop-approved values into plain inputs and uploads. This file only names what the
   generic scanner cannot read (row cards, unlabelled controls, the custom widgets' values) and sets an approved value in a
   widget; it never chooses a value itself. A new site is one file like this plus its line in adapters/registry.json. */
(() => {
// Per page, across the runtime's restarts: Monee rewrites the form from the uploaded resume, so fills wait for that.
const parse = {before: null, resumeInput: null, approved: false, doneAt: 0, marked: false};
(globalThis.internAdapters ||= []).push(R => {
  const text = e => (e?.innerText || e?.textContent || '').trim();
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  // The profile's wording for Monee's labels; any other label is asked once and kept as an approved answer.
  const WORDING = {'Course of Study': 'Field of study', 'Cumulative Grade Point Average (CGPA)': 'GPA',
    'Previous / Current Company': 'Company', 'Previous / Current Designation': 'Job title',
    'Current Location': 'Country', 'Website URL': 'Website'};
  const BY_ID = {country_code: 'Country phone code', contact_number: 'Phone number'};
  // Calling codes read "Singapore +65" here and "Singapore (+65)" in the profile.
  const shown = title => String(title).replace(/ (\+\d+)$/, ' ($1)');
  const search = value => value.replace(/ \(\+\d+\)$/, '');

  // Month/Year picker: shows "Aug 2024", read as YYYY-MM like <input type=month>.
  const pickerMonth = e => {
    const m = text(e.querySelector('.picker-value')).match(/^(\w{3}) (\d{4})$/);
    return m && MONTHS.includes(m[1]) ? `${m[2]}-${String(MONTHS.indexOf(m[1]) + 1).padStart(2, '0')}` : '';
  };
  const overlay = () => [...document.querySelectorAll('.month-year-picker-overlay')].find(o => o.getClientRects().length && !o.classList.contains('ant-popover-hidden'));
  async function pickMonth(e, p) {
    const want = String(p.value).match(/^(\d{4})-(\d{2})$/), have = pickerMonth(e);
    if (!want || have === p.value || have && !p.replace) return false;
    await until(() => !overlay());
    e.click();
    if (!await until(overlay)) return false;
    const pop = overlay(), year = () => Number(text(pop.querySelector('.year-display')));
    for (let i = 0; i < 100 && year() !== Number(want[1]); i++) {
      const before = year();
      pop.querySelectorAll('.year-selector button')[before > Number(want[1]) ? 0 : 1].click();
      if (!await until(() => year() !== before, 500)) break;
    }
    const month = [...pop.querySelectorAll('.month-button')].find(b => text(b) === MONTHS[Number(want[2]) - 1]);
    if (year() !== Number(want[1]) || !month || month.disabled) { e.click(); return false; }
    month.click();
    return until(() => pickerMonth(e) === p.value);
  }

  // Select (single or tags): the search input is the scanned control; its choices render in a virtual list.
  const values = e => e.closest('.ant-select-multiple')
    ? [...e.closest('.ant-select').querySelectorAll('.ant-select-content-item:not(.ant-select-content-item-rest) .ant-select-selection-item')].map(s => s.title)
    : [e.closest('.ant-select-content-has-value')].filter(Boolean).map(c => shown(c.title || text(c)));
  const dropdown = e => document.getElementById(e.getAttribute('aria-controls') || e.id + '_list')?.closest('.ant-select-dropdown');
  const choices = e => [...(dropdown(e)?.querySelectorAll('.ant-select-item-option') || [])];
  const searchable = e => !!e.closest('.ant-select-show-search');
  const typeText = (e, value) => {
    if (!searchable(e)) return;  // A list without search filters itself to nothing on typed text.
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', {bubbles: true}));
  };
  const open = e => {
    if (e.getAttribute('aria-expanded') !== 'true') e.closest('.ant-select').querySelector('.ant-select-content').dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
    return until(() => e.getAttribute('aria-expanded') === 'true');
  };
  const close = e => { if (e.value) typeText(e, ''); e.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); e.blur(); };
  // Visits each rendered page of the virtual list, from the top, until visit returns something.
  async function scroll(e, visit) {
    const holder = dropdown(e)?.querySelector('.ant-select-dropdown-list-holder');
    if (holder) { holder.scrollTop = 0; await pause(80); }
    // ponytail: at most 60 pages (~480 choices) inside the bridge's 8 s limit; a longer list is reached by searching instead.
    for (let i = 0; i < 60; i++) {
      const found = visit(choices(e));
      if (found || !holder) return found;
      const top = holder.scrollTop;
      holder.scrollTop += holder.clientHeight;
      await pause(80);
      if (holder.scrollTop === top) return visit(choices(e));
    }
  }
  async function findChoice(e, value) {
    const exact = list => list.find(o => norm(shown(o.title)) === norm(value));
    if (searchable(e)) {
      typeText(e, search(value));
      await pause(150);  // Lets the list re-render for this search before it is read.
      if (await until(() => exact(choices(e)), 600)) return exact(choices(e));
      typeText(e, '');  // Some lists search other text than the label they show ("Others / Not Applicable").
      await pause(150);
    }
    return scroll(e, exact);
  }
  async function pickOptions(e, p) {
    const multiple = !!e.closest('.ant-select-multiple');
    const wanted = multiple ? String(p.value).split(/[,;\n]/).map(s => s.trim()).filter(Boolean) : [String(p.value)];
    const have = values(e).map(norm);
    // Never replace a choice it did not make; verification reports the conflict instead.
    if (have.length && (have.join() === wanted.map(norm).join() || !p.replace)) return false;
    let changed = false, missed = false;
    if (multiple) {
      // Replacing tags the parser added: remove those the approved answer doesn't list.
      for (const tag of e.closest('.ant-select').querySelectorAll('.ant-select-content-item:not(.ant-select-content-item-rest) .ant-select-selection-item')) {
        if (!wanted.map(norm).includes(norm(tag.title))) { tag.querySelector('.ant-select-selection-item-remove')?.click(); changed = true; await pause(100); }
      }
    }
    for (const value of wanted.filter(v => !have.includes(norm(v)))) {
      const choice = await open(e) && await findChoice(e, value);
      if (!choice) { missed = true; break; }
      choice.click();
      changed = await until(() => values(e).map(norm).includes(norm(value)), 1000) || changed;
    }
    if (multiple || missed) close(e);
    return changed;
  }
  async function listChoices(e, query) {
    if (!await open(e)) return [];
    // The profile's wording, then its first word, then everything: a question always offers the form's real choices.
    for (const q of query && searchable(e) ? [search(String(query)), String(query).split(/\s+/)[0], ''] : []) {
      typeText(e, q);
      await pause(150);
      if (await until(() => choices(e).length, 400)) break;
    }
    const seen = new Set();
    await scroll(e, list => { list.forEach(o => seen.add(shown(o.title))); });
    close(e);
    return [...seen];
  }

  // Resume parsing: once the approved resume is uploaded, Monee fills the form from it. Other fills wait until it has
  // finished (plus a moment for its writes); then what changed since before the upload is marked as Monee's, which approved
  // values may replace. Anything already in the form before the upload stays the user's.
  const resumeItem = () => document.querySelector('label[for=resume]')?.closest('.ant-form-item');
  const controls = () => [...document.querySelectorAll('form input:not([type=file]):not([type=submit]), .month-year-picker-input')];
  const current = e => e.matches('.ant-select-input') ? values(e).join(', ') : e.matches('.month-year-picker-input') ? pickerMonth(e) : e.type === 'checkbox' ? String(e.checked) : e.value;
  function released(policyOf) {
    const p = parse.resumeInput && policyOf(parse.resumeInput);
    if (p && p.value != null && !p.omit) parse.approved = true;
    if (!parse.approved) return true;
    if (!resumeItem()?.querySelector('.resume-parsed-container')) return false;
    parse.doneAt ||= performance.now();
    if (performance.now() - parse.doneAt < 1500) return false;
    if (!parse.marked) {
      parse.marked = true;
      for (const e of controls()) if (current(e) !== (parse.before?.get(e) ?? '')) e.setAttribute('data-intern-site-filled', '');
    }
    return true;
  }

  return {
    id: 'monee', name: 'Monee', fill: 'direct',
    pattern: /^https:\/\/careers\.monee\.com\/(job-detail|apply)\?/,
    open: 'a[href^="/apply?"]',
    annotate() {
      // data-intern-* attributes are read by core/automation/scan.js; the site renders nothing from them.
      const mark = (e, name, value) => { if (e && value != null) e.setAttribute('data-intern-' + name, value); };
      parse.before ??= new Map(controls().map(e => [e, current(e)]));
      parse.resumeInput = resumeItem()?.querySelector('input[type=file]') || parse.resumeInput;
      for (const card of document.querySelectorAll('.education-entry-card, .experience-entry-card')) {
        card.setAttribute('data-intern-row', '');
        card.parentElement.setAttribute('data-intern-group', card.matches('.education-entry-card') ? 'education' : 'experience');
        card.querySelectorAll('.month-year-picker-input').forEach((e, i) => {
          mark(e, 'label', ['Start date', 'End date'][i]); mark(e, 'kind', 'month'); mark(e, 'value', pickerMonth(e));
        });
      }
      for (const e of document.querySelectorAll('form input:not([type=submit])')) {
        const label = text(e.closest('.ant-form-item')?.querySelector('.ant-form-item-label label'));
        const unlabelled = !label && !e.labels?.length;
        mark(e, 'label', BY_ID[e.id] || WORDING[label] || (e.type === 'file' && !e.labels?.length ? label || 'Supporting documents' : unlabelled && e.placeholder ? e.placeholder : null));
        if (e.matches('.ant-select-input')) mark(e, 'value', values(e).join(', '));
      }
      const [start, end] = document.querySelectorAll('.ant-picker-range input');
      mark(start, 'label', 'Availability start date'); mark(end, 'label', 'Availability end date');
      // An upload counts once Monee shows its file panel; the runtime binds the file digest to that receipt.
      for (const wrapper of document.querySelectorAll('.ant-upload-wrapper')) {
        wrapper.setAttribute('data-intern-upload', '');
        const done = wrapper.querySelector('.resume-parsed-container');
        if (done) done.setAttribute('data-intern-receipt', text(done.querySelector('p')));
      }
    },
    hold: (e, policyOf) => e.type !== 'file' && !released(policyOf),
    busy: policyOf => !!document.querySelector('.upload-progress-container') || !released(policyOf),
    custom: e => !!e?.matches?.('.ant-select-input, .month-year-picker-input'),
    choose: (e, p) => e.matches('.month-year-picker-input') ? pickMonth(e, p) : pickOptions(e, p),
    options: (e, query) => e.matches('.ant-select-input') ? listChoices(e, query) : [],
    async script({setMessage}) {
      // Proposes Submit: the runtime records it, and only the desktop clicks it after verifying every field.
      const submit = document.querySelector('form input[type=submit]');
      if (submit) R.call(submit, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
