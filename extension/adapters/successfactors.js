/* SAP SuccessFactors application form (career*.sapsf.com portalcareer, e.g. Synapxe's careers site). Replaces the extracted
   vendor script, whose first click (Expand all sections) and resume button were refused by the runtime, so it never filled a
   live form. fill:'direct' lets the runtime write approved values into plain inputs and textareas; this file opens the
   collapsed sections, uploads documents through SF's attach popup and picks options in SF's paginated picklists. It never
   chooses a value itself. */
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
  async function pick(e, p) {
    const have = norm(e.value), want = norm(p.value);
    if (have === want || (have && !p.replace)) return false;  // Never replace a choice it did not make; verification reports it.
    if (!await open(e)) return false;
    // ponytail: only the first rendered page (SF renders 100 per page); a longer list needs typing to filter, add when one shows up.
    const option = items(e).find(o => norm(text(o)) === want);
    if (!option) { await close(e); return false; }
    option.click();
    return until(() => norm(e.value) === want, 1000);
  }
  async function choices(e) {
    if (!await open(e)) return [];
    const seen = items(e).map(text).filter(t => t && norm(t) !== 'no selection');
    await close(e);
    return seen;
  }

  // Documents: each attachment field's + button opens a popup holding the real file input, which uploads on change.
  // The + (or, holding one, the pencil) opens it; the runtime decides whether a file must be sent, and only then is it opened.
  // About 5 s after a document arrives SF rebuilds the whole form, wiping what was filled: the adapter stays busy until then,
  // and the runtime reports the rebuilt controls so the desktop fills the section again.
  const receipt = f => [...f.querySelectorAll('[id$=_attachDownloadLabel]')].find(visible);
  const receiptName = r => (r.innerText || '').split('\n')[0].trim();  // "Resume.pdf\n(14/11/2026)"
  const popupInput = () => [...document.querySelectorAll('[role=dialog]')].filter(visible).map(d => d.querySelector('input.fileUpload')).find(Boolean);
  let sending = null;  // {button, at} from a document sent until the rebuild
  const rebuilding = () => !!sending && sending.button.isConnected && performance.now() - sending.at < 15000;
  async function attach(e) {
    let opened = false;
    const open = async () => { opened = true; e.click(); return await until(popupInput, 2000) ? popupInput() : null; };
    if (await R.upload(null, e, open) && opened) sending = {button: e, at: performance.now()};
    return false;  // The rebuild, not this call, tells the desktop to look again.
  }

  return {
    id: 'sap-successfactors', name: 'SAP SuccessFactors', fill: 'direct',
    pattern: /^https?:\/\/(?:.*\.)?(?:successfactors|sapsf)\.(?:com|eu)\/.*/,
    open: '#applyButton_top',  // The job page repeats Apply at its foot (#applyButton_bottom).
    async annotate() {
      // The form renders after the page loads; a scan before it would find nothing to fill.
      if (/career_ns=job_application/.test(location.search)) await until(() => document.querySelector('.RCMFormField'), 5000);
      const expand = document.querySelector('a[id$=_expandAllSections]');
      if (expand && collapsed()) { expand.click(); await until(() => !collapsed(), 3000); }
      // data-intern-* attributes are read by core/automation/scan.js and runtime.js; the site renders nothing from them.
      // SF puts the required star before the label ("* Formal Name"); the scanner reads a trailing one as required and drops it.
      for (const label of document.querySelectorAll('.RCMFormField > label')) {
        const control = label.parentElement.querySelector('input:not([type=hidden]),textarea,select');
        if (!control) continue;
        control.setAttribute('data-intern-label', text(label).replace(/^\*\s*/, '') + (label.querySelector('.requiredField') ? ' *' : ''));
        // A phone box shows the saved number as "(+65) 55512345"; as tel it is compared by its digits.
        if (/phone/i.test(control.name) || /phone|contact number|mobile/i.test(text(label))) control.setAttribute('data-intern-kind', 'tel');
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
    custom: e => picklist(e) || !!e?.matches?.('span.addAttachments[data-intern-kind=file]'),
    choose: (e, p) => picklist(e) ? pick(e, p) : attach(e),
    options: e => picklist(e) ? choices(e) : [],
    async script({setMessage}) {
      // Proposes Apply: the runtime records it, and only the desktop clicks it after verifying every field.
      const apply = [...document.querySelectorAll('span[role=button][id$=_submitBtn]')].find(visible);
      if (apply) R.call(apply, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
