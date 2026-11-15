/* Eightfold careers sites on an employer's own domain (careers.micron.com) or *.eightfold.ai, recognized by the page's pcsx-data
   block. Each posting's Apply Now opens one account-less form at /careers/apply?pid=<id>; the extracted vendor adapter covers only
   Eightfold's older SmartApply page. fill:'direct' lets the runtime write approved values into plain inputs and radios; this file
   names the controls the scanner misreads and picks options in the searchable dropdowns. It never chooses a value itself. */
(() => {
// Per page, across the runtime's restarts: Eightfold rewrites the form from the uploaded résumé, so fills wait for that (as in monee.js).
const parse = {rendered: false, before: null, approved: false, since: 0, doneAt: 0, filled: null};
(globalThis.internAdapters ||= []).push(R => {
  const text = e => (e?.innerText || e?.textContent || '').trim().replace(/\s+/g, ' ');
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  // As runtime.js reads it: PayPal keeps its consent dialog in the page with visibility:hidden until a file is picked.
  const visible = e => !!e?.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };
  const typeText = (e, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', {bubbles: true}));
  };
  // Calling codes read "🇸🇬 (+65) Singapore" here and "Singapore (+65)" in the profile; other choices read as they are.
  const shown = t => String(t).replace(/^[\u{1F1E6}-\u{1F1FF}]{2}\s*/u, '').replace(/^\((\+[\d ]+)\)\s*(.+)$/, '$2 ($1)').trim();
  const search = v => String(v).replace(/\s*\(\+\d+\)$/, '');

  // Dropdown: an input[role=combobox] owning a listbox of button[role=option]; a pick becomes the input's value.
  const dropdown = e => !!e?.matches?.('input[role=combobox][aria-controls]');
  const items = e => [...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('[role=option]') || [])];
  const open = async e => { if (!items(e).length) { e.focus(); e.click(); } return until(() => items(e).length, 1000); };
  const close = e => { e.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); e.blur(); };
  async function pick(e, p) {
    const have = norm(shown(e.value)), want = norm(p.value);
    if (have === want || have && !p.replace) return false;  // Never replace a choice it did not make; verification reports it.
    await open(e);
    const option = () => items(e).find(o => norm(shown(text(o))) === want);
    // The open list holds every choice (all 254 calling codes). A choice clicked while a typed search is still re-rendering the list
    // shows in the box but is dropped on blur (seen live), so a search, only for a choice not listed, gets time to settle.
    if (!option()) {
      typeText(e, search(p.value));
      await pause(400);
      if (!await until(option, 1500)) { typeText(e, ''); close(e); return false; }
    }
    option().click();
    return until(() => norm(shown(e.value)) === want, 1000);
  }
  async function choices(e) {
    if (!await open(e)) return [];
    const seen = items(e).map(o => shown(text(o)));
    close(e);
    return seen;
  }

  // Radios carry a readonly attribute (meaningless on a radio), so the runtime, which never writes a read-only control, leaves them
  // here: the approved option is clicked, unless the question already holds another answer.
  const radio = e => !!e?.matches?.('[role=radiogroup] input[type=radio][readonly]');
  async function press(e, p) {
    if (norm(text(e.labels?.[0])) !== norm(p.value) || e.checked) return false;
    if (!p.replace && [...document.getElementsByName(e.name)].some(r => r.checked)) return false;
    e.click();
    return until(() => e.checked, 500);
  }

  // Résumé: a picked file opens the employer's consent dialog (Micron's for its use of Eightfold's AI, PayPal's Data Privacy Agreement:
  // Cancel / I Agree), and nothing is uploaded until it is accepted. The dialog is asked as a question named by its title; only your
  // approved Yes clicks I Agree. Eightfold then reads the résumé and rewrites the form from it (seen live: a typed "Ada" became the
  // résumé's "Jonathan"), so other fills wait for that, and what it changed is marked as the site's, which approved values may replace.
  const agree = d => [...d.querySelectorAll('button')].find(b => /^i agree$/i.test(text(b)));
  const consent = () => [...document.querySelectorAll('[role=dialog]')].find(d => visible(d) && agree(d));
  const agreement = e => !!e?.matches?.('button[data-intern-consent]');
  async function accept(e, p) {
    if (p.value !== true) return false;
    e.click();
    return until(() => !e.isConnected || !visible(e), 2000);
  }
  const resumeBox = () => { let b = document.querySelector('input[type=file]'); while (b && !b.querySelector?.('label')) b = b.parentElement; return b; };
  const received = () => [...(resumeBox()?.querySelectorAll('li') || [])].find(li => li.querySelector('button[aria-label^="Delete file"]'));
  const sending = () => !!resumeBox()?.querySelector('li') && !received();  // "Upload is in progress … Matching…"
  const fields = () => [...document.querySelectorAll('form input:not([type=file]):not([type=radio]):not([type=checkbox]), form textarea')];
  // The form is re-rendered after the résumé is read, so values are kept by each control's id ("Contact_Information_email"), not element.
  const keyOf = e => e.id || e.name || text(e.labels?.[0]);
  // A value still exactly what the résumé wrote is the site's; one you changed since is yours and stays.
  const markParsed = () => { for (const e of fields()) if (parse.filled?.get(keyOf(e)) === e.value) e.setAttribute('data-intern-site-filled', ''); };
  function released(policyOf) {
    const input = document.querySelector('input[type=file]'), p = input && policyOf(input);
    if (p && p.value != null && !p.omit && !parse.approved) { parse.approved = true; parse.since = performance.now(); }
    if (!parse.approved) return true;
    const dialog = consent();
    // Not yet agreed: fill the rest now, and the résumé's rewrite is replaced on a later pass. Agreed: wait for the upload it starts.
    if (dialog) { const q = policyOf(agree(dialog)); return !(q && q.value === true); }
    if (sending()) return false;
    if (!received()) return performance.now() - parse.since > 15000;  // A file the site never took leaves the rest to fill.
    parse.doneAt ||= performance.now();
    if (performance.now() - parse.doneAt < 1500) return false;
    parse.filled ??= new Map(fields().filter(e => e.value !== (parse.before?.get(keyOf(e)) ?? '')).map(e => [keyOf(e), e.value]));
    markParsed();
    return true;
  }
  // Some employers (Qualcomm) ask you to sign in first: an Email → Continue dialog over the page, shown about 2 s after it loads.
  const signIn = () => [...document.querySelectorAll('[role=dialog]')].find(d => visible(d) && [...d.querySelectorAll('h1,h2,h3')].some(h => /^(sign in|log in)$/i.test(text(h))));

  return {
    id: 'eightfold-pcs', name: 'Eightfold', fill: 'direct',
    pattern: /^https:\/\/[^/]+\/careers\/apply\?(?:[^#]*&)?pid=\d+/,
    selector: '#pcsx-data',
    // One page: its headings change as answers reveal sections (PayPal's address after Country), which would otherwise read as a new
    // section whose earlier answers must be reconciled on a review page it doesn't have.
    section: () => 'Application form',
    async annotate() {
      // The form renders after the page fetches its questions; a scan before it would find nothing to fill.
      await until(() => document.querySelector('button[data-test-id=submitApplicationButton]') || signIn(), 5000);
      // Questions keep arriving after the submit button (PayPal's 12 controls became 21, replacing the résumé input the first fill had
      // used), so a page's first scan waits until the count has held for half a second.
      if (!parse.rendered && !signIn()) {
        let count = -1, since = 0;
        await until(() => { const n = document.querySelectorAll('form input, form textarea').length; if (n !== count) { count = n; since = performance.now(); } return performance.now() - since > 500; }, 4000);
        parse.rendered = true;
      }
      // A sign-in dialog (Qualcomm's asks for an email, Microsoft's offers only Microsoft/LinkedIn/Google/Facebook buttons) is read as one
      // credential control: the desktop hands the sign-in to you, and the scan leaves out what is inside it, so nothing is typed there.
      signIn()?.setAttribute('data-intern-kind', 'password');
      // data-intern-* attributes are read by core/automation/scan.js and runtime.js; the site renders nothing from them.
      parse.before ??= new Map(fields().map(e => [keyOf(e), e.value]));
      markParsed();
      // The consent dialog's I Agree is a required yes/no question named by the dialog's title (runtime.js scans a marked dialog too).
      const dialog = consent();
      if (dialog) {
        const button = agree(dialog), title = text(document.getElementById(dialog.getAttribute('aria-labelledby'))) || text(dialog.querySelector('h1,h2,h3'));
        button.setAttribute('data-intern-kind', 'checkbox');
        button.setAttribute('data-intern-consent', '');
        button.setAttribute('data-intern-label', (title || 'Consent to process your résumé') + ' *');
      }
      // The résumé slot names the upload for the runtime's proof; a received file shows as a row with its Delete button.
      const box = resumeBox();
      if (box) {
        box.setAttribute('data-intern-upload', 'Resume');
        box.querySelector('input[type=file]')?.setAttribute('data-intern-label', 'Resume');
        const row = received(), name = row?.querySelector('span[title]')?.getAttribute('title');
        box.querySelectorAll('[data-intern-receipt]').forEach(r => r !== row && r.removeAttribute('data-intern-receipt'));
        if (row && name) row.setAttribute('data-intern-receipt', name);
      }
      for (const e of document.querySelectorAll('input[role=combobox][aria-controls]')) {
        e.setAttribute('data-intern-kind', 'combobox');
        e.setAttribute('data-intern-value', shown(e.value));
        if (norm(e.getAttribute('aria-label')) === 'country code') e.setAttribute('data-intern-label', 'Country phone code');
      }
      // A radio's aria-label reads "<option>, <question>" and its group's aria-labelledby names no element, so each option read as its own
      // question. The question is what the group's labels share at their end ("Yes, Have you…" / "No, Have you…"); the option's own text
      // can differ from its aria-label (Vodafone's "country / region" against "country/region").
      for (const g of document.querySelectorAll('[role=radiogroup]')) {
        const radios = [...g.querySelectorAll('input[type=radio][aria-label]')], labels = radios.map(r => r.getAttribute('aria-label'));
        let tail = labels[0] || '';
        for (const l of labels) while (tail && !l.endsWith(tail)) tail = tail.slice(1);
        const question = radios.length > 1 && tail.includes(', ') ? tail.slice(tail.indexOf(', ') + 2) : '';
        if (question) radios.forEach(r => r.setAttribute('data-intern-label', question));
      }
    },
    hold: (e, policyOf) => e.type !== 'file' && !agreement(e) && !released(policyOf),
    busy: policyOf => !consent() && !released(policyOf),
    // While a consent dialog waits, the résumé is not sent again (on a resumed run it would open a second dialog over the first).
    custom: e => dropdown(e) || radio(e) || agreement(e) || !!signIn()?.contains(e) || e?.type === 'file' && !!consent(),
    choose: (e, p) => signIn()?.contains(e) || e.type === 'file' ? Promise.resolve(false) : agreement(e) ? accept(e, p) : radio(e) ? press(e, p) : pick(e, p),
    options: e => dropdown(e) ? choices(e) : [],
    async script({setMessage}) {
      // Proposes Submit application: the runtime records it, and only the desktop clicks it after verifying every field.
      const submit = [...document.querySelectorAll('button[data-test-id=submitApplicationButton]')].find(visible);
      if (submit) R.call(submit, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
