/* SAP SuccessFactors application form (career*.sapsf.com portalcareer, e.g. Synapxe's careers site). Replaces the extracted
   vendor script, whose first click (Expand all sections) and resume button were refused by the runtime, so it never filled a
   live form. fill:'direct' lets the runtime write approved values into plain inputs and textareas; this file opens the
   collapsed sections, uploads documents through SF's attach popup, picks options in SF's paginated picklists, ticks its ARIA
   radios, types into its date pickers and marks the rows of repeating sections. It never chooses a value itself. */
(() => {
(globalThis.internAdapters ||= []).push(R => {
  const text = e => (e?.innerText || e?.textContent || '').trim().replace(/\s+/g, ' ');
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const visible = e => !!e?.getClientRects().length;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };

  // Sections start collapsed and their fields are absent from the scan until expanded.
  const collapsed = () => [...document.querySelectorAll('div[id*=sectionContent]')].some(d => !visible(d));

  // Paginated picklist: input[role=combobox] owning a ul[role=listbox] of li[role=option] through aria-controls.
  const picklist = e => !!e?.matches?.('input.rcmpaginatedselectinput');
  const items = e => [...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('li[role=option]') || [])].filter(visible);
  // A click while the previous list is still closing can be lost, so it is tried twice.
  const open = async e => { for (let i = 0; i < 2 && !items(e).length; i++) { e.click(); await until(() => items(e).length, 1200); } return items(e).length > 0; };
  const close = async e => { if (items(e).length) e.click(); await until(() => !items(e).length, 500); e.blur(); };
  // Mirrors same_choice() in models.py: the option is the answer, or the answer qualified ("National University of Singapore (NUS)").
  const same = (a, b) => { a = norm(a); b = norm(b); return a === b || !!b && a.startsWith(b) && /^\s*[,(\-–—:]/.test(a.slice(b.length)); };
  // A calling-code list holds bare numbers ("65") for an answer of "+65" or "Singapore (+65)".
  const digits = v => String(v ?? '').replace(/\D/g, '');
  const code = e => e.getAttribute('data-intern-kind') === 'tel';
  async function pick(e, p) {
    const is = t => code(e) ? norm(t) === digits(p.value) : same(t, p.value);
    const have = e.value;
    if (is(have) || (norm(have) && !p.replace)) return false;  // Never replace a choice it did not make; verification reports it.
    if (!await open(e)) return false;
    const found = () => items(e).filter(o => is(text(o)));
    // SF renders 100 options a page; typing in the box filters the whole list (CPF's institutions, calling codes).
    if (!found().length && items(e).length >= 100) {
      e.focus();
      e.value = code(e) ? digits(p.value) : String(p.value);
      e.dispatchEvent(new Event('input', {bubbles: true}));
      e.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: e.value.slice(-1)}));
      await until(() => found().length, 3000);
    }
    const options = found();
    if (options.length !== 1) {  // Not offered, or two options fit: it never chooses between them.
      if (e.value !== have) { e.value = have; e.dispatchEvent(new Event('input', {bubbles: true})); }
      await close(e);
      return false;
    }
    options[0].click();
    return until(() => is(e.value), 1000);
  }
  async function choices(e) {
    if (!await open(e)) return [];
    const seen = items(e).map(text).filter(t => t && norm(t) !== 'no selection');
    await close(e);
    return seen;
  }

  // Questions are answered with ARIA radios (span[role=radio]) the runtime cannot tick; each names its option through aria-labelledby.
  const radio = e => !!e?.matches?.('.radioGroup [role=radio]');
  async function tick(e, p) {
    const want = p.value === true ? 'yes' : p.value === false ? 'no' : p.value;
    if (!same(text(document.getElementById(e.getAttribute('aria-labelledby'))), want) || e.getAttribute('aria-checked') === 'true') return false;
    if (e.closest('[role=radiogroup]').querySelector('[role=radio][aria-checked=true]') && !p.replace) return false;
    e.click();
    return until(() => e.getAttribute('aria-checked') === 'true', 1000);
  }

  // Dates are UI5 date pickers: the text box sits two shadow roots down and reads DD/MM/YYYY. The desktop speaks ISO. A date
  // known only to its month ("2026-06", all a résumé says) matches any day SF's own résumé reader put in that month, but no day
  // is invented for an empty box.
  const pickers = () => [...document.querySelectorAll('.datePicker *')].filter(w => /^UI5-DATE-PICKER/.test(w.tagName));
  const dateBox = w => w.shadowRoot?.querySelector('.ui5-date-picker-input')?.shadowRoot?.querySelector('input');
  const pickerOf = e => { const w = e?.getRootNode?.().host?.getRootNode?.().host; return w && /^UI5-DATE-PICKER/.test(w.tagName) ? w : null; };
  const iso = v => String(v || '').replace(/^(\d{2})\/(\d{2})\/(\d{4})$/, '$3-$2-$1');
  const local = v => String(v).replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$3/$2/$1');
  async function setDate(e, p) {
    const w = pickerOf(e), want = local(p.value), have = w.value || e.value;
    if (!/^\d{2}\/\d{2}\/\d{4}$/.test(want) || have === want || iso(have).startsWith(String(p.value)) || (have && !p.replace)) return false;
    e.focus();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, want);
    e.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
    e.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, composed: true, key: 'Enter', code: 'Enter', keyCode: 13}));
    e.blur();
    return until(() => w.value === want, 1500);
  }

  // Documents: each attachment field's + button opens a popup holding the real file input, which uploads on change.
  // The + (or, holding one, the pencil) opens it; the runtime decides whether a file must be sent, and only then is it opened.
  // About 5 s after a document arrives SF rebuilds the whole form, wiping what was filled: the adapter stays busy until then,
  // and the runtime reports the rebuilt controls so the desktop fills the section again.
  const receipt = f => [...f.querySelectorAll('[id$=_attachDownloadLabel]')].find(visible);
  const receiptName = r => (r.innerText || '').split('\n')[0].trim();  // "Resume.pdf\n(14/11/2026)"
  const popupInput = () => [...document.querySelectorAll('[role=dialog]')].filter(visible).map(d => d.querySelector('input.fileUpload')).find(Boolean);
  let sending = null;  // {button, at} from a document sent until the rebuild
  // SF reads a résumé it receives into new rows of the repeating sections, often wrongly ("UNSPECIFIED" as the employer, a
  // project as a job). What it wrote there may be replaced with the profile's rows, and rows past the profile's last are its
  // own invention and are removed; rows the account already held, and anything typed since, are left alone.
  const GROUPS = ['experience', 'education'];
  const rowsOf = group => [...document.querySelectorAll(`[data-intern-group=${group}] [data-intern-row]`)];
  const rowControls = row => [...row.querySelectorAll('.RCMFormField')].map(f => {
    const w = [...f.querySelectorAll('.datePicker *')].find(e => /^UI5-DATE-PICKER/.test(e.tagName));
    const control = w ? dateBox(w) : f.querySelector('input:not([type=hidden]),textarea');
    return control && {name: text(f.querySelector('label')), control, value: w ? w.value : control.value};
  }).filter(Boolean);
  let before = null, parsed = null, wanted = null;  // row counts when a document was sent; what SF then wrote; the profile's row counts
  async function reconcile() {
    if (!before || rebuilding()) return;
    if (!parsed && GROUPS.some(g => rowsOf(g).length > before[g])) {
      parsed = new Map();
      for (const g of GROUPS) rowsOf(g).forEach((row, i) => { if (i >= before[g]) for (const c of rowControls(row)) parsed.set(`${g}:${i}:${c.name}`, c.value); });
    }
    if (!parsed) return;
    for (const g of GROUPS) {
      for (let rows = rowsOf(g); wanted && rows.length > Math.max(before[g], wanted[g]); rows = rowsOf(g)) {
        const last = rows.at(-1), remove = last.querySelector('[role=button][title="Delete Row"]');
        if (!remove || rowControls(last).some(c => c.value !== parsed.get(`${g}:${rows.length - 1}:${c.name}`))) break;
        remove.click();
        if (!await until(() => rowsOf(g).length < rows.length, 2000)) break;
      }
      rowsOf(g).forEach((row, i) => { for (const c of rowControls(row)) if (c.value && c.value === parsed.get(`${g}:${i}:${c.name}`)) c.control.setAttribute('data-intern-site-filled', ''); });
    }
  }
  const rebuilding = () => !!sending && sending.button.isConnected && performance.now() - sending.at < 15000;
  async function attach(e) {
    let opened = false;
    const open = async () => { opened = true; e.click(); return await until(popupInput, 2000) ? popupInput() : null; };
    const counts = Object.fromEntries(GROUPS.map(g => [g, rowsOf(g).length]));
    if (await R.upload(null, e, open) && opened) { sending = {button: e, at: performance.now()}; before = counts; parsed = null; }
    return false;  // The rebuild, not this call, tells the desktop to look again.
  }

  return {
    id: 'sap-successfactors', name: 'SAP SuccessFactors', fill: 'direct',
    pattern: /^https?:\/\/(?:.*\.)?(?:successfactors|sapsf)\.(?:com|eu)\/.*/,
    open: '#applyButton_top',  // The job page repeats Apply at its foot (#applyButton_bottom).
    async annotate() {
      // The form renders after the page loads; a scan before it would find nothing to fill.
      // CPF's opens at /career?_s.crb=… behind SF's "Loading..." overlay, for several seconds.
      if (/career_ns=job_application/.test(location.search) || visible(document.querySelector('.sfloadingIcon'))) await until(() => document.querySelector('.RCMFormField'), 15000);
      const expand = document.querySelector('a[id$=_expandAllSections]');
      if (expand && collapsed()) { expand.click(); await until(() => !collapsed(), 3000); }
      // data-intern-* attributes are read by core/automation/scan.js and runtime.js; the site renders nothing from them.
      // SF puts the required star before the label ("* Formal Name"); the scanner reads a trailing one as required and drops it.
      for (const label of document.querySelectorAll('.RCMFormField > label')) {
        const control = label.parentElement.querySelector('input:not([type=hidden]),textarea,select');
        if (!control) continue;
        control.setAttribute('data-intern-label', text(label).replace(/^\*\s*/, '') + (label.querySelector('.requiredField') ? ' *' : ''));
        // A picklist that waits on another (Certificate, on Qualification) has no combobox role until that one is chosen.
        if (picklist(control)) control.setAttribute('data-intern-kind', 'combobox');
        // A phone box shows the saved number as "(+65) 55512345"; as tel it is compared by its digits.
        if (/phone/i.test(control.name) || /phone|contact number|mobile/i.test(text(label))) control.setAttribute('data-intern-kind', 'tel');
      }
      // Repeating sections (My Work Experience, Highest Qualification) hold one .rcmSectionComponent per row beside an Add button;
      // the scanner lines their rows up with the profile's jobs and schools.
      for (const add of document.querySelectorAll('[id$=_addRowBtn]')) {
        const section = add.closest('.sectionContent'), title = text(document.getElementById(section?.getAttribute('aria-labelledby')));
        const group = /experience|employment/i.test(title) ? 'experience' : /education|qualification/i.test(title) ? 'education' : '';
        if (!group) continue;
        section.setAttribute('data-intern-group', group);
        section.querySelectorAll('.rcmSectionComponent').forEach(r => r.setAttribute('data-intern-row', ''));
      }
      await reconcile();
      for (const w of pickers()) {
        const box = dateBox(w), label = w.closest('.RCMFormField')?.querySelector('label');
        if (!box || !label) continue;
        box.setAttribute('data-intern-kind', 'date');
        box.setAttribute('data-intern-label', text(label).replace(/^\*\s*/, '') + (label.querySelector('.requiredField') ? ' *' : ''));
        box.setAttribute('data-intern-value', iso(w.value || box.value));
      }
      for (const f of document.querySelectorAll('.attachmentField')) {
        const button = f.querySelector('span.addAttachments[role=button]');
        if (!button) continue;
        f.setAttribute('data-intern-upload', text(f.querySelector('label')).replace(/^\*\s*/, ''));  // names the slot for the runtime's proof
        button.setAttribute('data-intern-kind', 'file');
        button.setAttribute('data-intern-label', text(f.querySelector('label')).replace(/^\*\s*/, ''));
        const done = receipt(f);
        f.querySelectorAll('[data-intern-receipt]').forEach(r => r !== done && r.removeAttribute('data-intern-receipt'));
        if (done) done.setAttribute('data-intern-receipt', receiptName(done));
        button.setAttribute('data-intern-value', done ? receiptName(done) : '');
      }
    },
    hold: () => rebuilding(),
    busy: () => rebuilding(),
    custom: e => picklist(e) || radio(e) || !!pickerOf(e) || !!e?.matches?.('span.addAttachments[data-intern-kind=file]'),
    choose: (e, p) => picklist(e) ? pick(e, p) : radio(e) ? tick(e, p) : pickerOf(e) ? setDate(e, p) : attach(e),
    options: e => picklist(e) ? choices(e) : [],
    async script({setMessage, getProfile}) {
      const profile = await getProfile();
      wanted = {experience: (profile.jobData || []).length, education: (profile.educationData || []).length};
      // Proposes Apply: the runtime records it, and only the desktop clicks it after verifying every field.
      const apply = [...document.querySelectorAll('span[role=button][id$=_submitBtn]')].find(visible);
      if (apply) R.call(apply, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
