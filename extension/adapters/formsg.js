/* FormSG (form.gov.sg): the Singapore government's form builder, which agencies use for internship applications (IMDA's, say).
   One page, no account. fill:'direct' lets the runtime write approved values into plain inputs, radios and checkboxes; this file
   picks options in FormSG's searchable dropdowns and stands in for an attachment's file input, which FormSG replaces with a
   receipt once a file is attached. It never chooses a value itself. Nothing reaches FormSG before Submit, which only the desktop clicks. */
(() => {
(globalThis.internAdapters ||= []).push(R => {
  const text = e => (e?.innerText || e?.textContent || '').trim().replace(/\s+/g, ' ');
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const visible = e => !!e?.getClientRects().length;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };
  const typeText = (e, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', {bubbles: true}));
  };

  // Dropdown (downshift): an input[role=combobox] owning a ul[role=listbox]. A pick shows beside the input, which stays empty.
  const dropdown = e => !!e?.matches?.('input[role=combobox][aria-controls^="downshift-"]');
  const shown = e => e.value.trim() || text(e.parentElement);
  const items = e => [...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('[role=option]') || [])];
  const open = async e => { if (!items(e).length) { e.focus(); e.click(); } return until(() => items(e).length, 1000); };
  const close = e => { e.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); e.blur(); };
  async function pick(e, p) {
    const have = norm(shown(e)), want = norm(p.value);
    if (have === want || have && !p.replace) return false;  // Never replace a choice it did not make; verification reports it.
    await open(e);
    typeText(e, String(p.value));  // Filters a long list down to the answer.
    const option = () => items(e).find(o => norm(text(o)) === want);
    if (!await until(option, 1500)) { typeText(e, ''); close(e); return false; }
    option().click();
    return until(() => norm(shown(e)) === want, 1000);
  }
  async function choices(e) {
    if (!await open(e)) return [];
    const seen = items(e).map(text);
    close(e);
    return seen;
  }

  // Attachment: the file input sits in its question's group until a file is attached; then FormSG removes it and shows
  // "File attached: <name> with file size of <size>". The group names the slot, so the runtime's upload proof survives the swap.
  const ATTACHED = /^File attached: (.+) with file size of /;
  // ponytail: a question that mentions only a resume (or only a cover letter) is asked as that profile document; any other upload
  // is asked by its own wording. A form asking for "resume and transcript in one PDF" is asked by its wording.
  const documentLabel = q => /\b(resume|résumé|cv)\b/i.test(q) && !/cover letter|transcript|certificate|portfolio/i.test(q) ? 'Resume'
    : /cover letter/i.test(q) && !/\b(resume|résumé|cv)\b|transcript/i.test(q) ? 'Cover letter' : q;
  const receiptBox = e => !!e?.matches?.('[data-intern-kind=file]:not(input)');

  return {
    id: 'formsg', name: 'FormSG', fill: 'direct',
    pattern: /^https:\/\/form\.gov\.sg\/(?:#!\/)?[0-9a-f]{24}(?:[/?#]|$)/,
    // One page, whose section headings can themselves be conditional: it stays one section however its answers change it.
    section: () => 'Form',
    async annotate() {
      // The form renders about a second after the page loads (seen live); a scan before it would find nothing to fill.
      await until(() => document.querySelector('form [role=group]'), 5000);
      // data-intern-* attributes are read by core/automation/scan.js and runtime.js; the site renders nothing from them.
      for (const e of document.querySelectorAll('input[role=combobox][aria-controls^="downshift-"]')) {
        e.setAttribute('data-intern-kind', 'combobox');
        e.setAttribute('data-intern-value', shown(e));
      }
      // A mobile number field shows "91234567" as "9123 4567"; as tel it is compared by its digits.
      for (const e of document.querySelectorAll('input[autocomplete=tel]')) e.setAttribute('data-intern-kind', 'tel');
      // ponytail: the mobile field's country picker (default Singapore) is asked as your country of residence, so it isn't a question on every
      // form; a number from another country needs its own approved answer, and FormSG marks a number that doesn't fit the country.
      for (const e of document.querySelectorAll('select[aria-label="Country selector"]')) e.setAttribute('data-intern-label', 'Country');
      // Each question is a [role=group] holding its label; section headings and statements ("January 2027 - June 2027") sit between them.
      const questions = [...document.querySelectorAll('form [role=group]')].filter(g => g.querySelector('label[id$="-label"]'));
      const asked = g => text(g.querySelector('label > div')).replace(/^\d+\.\s*/, '');
      const section = g => {
        for (let item = g; item && !item.matches('form'); item = item.parentElement)
          for (let s = item.previousElementSibling; s; s = s.previousElementSibling) {
            if (s.matches('[role=group]') || s.querySelector('[role=group]')) continue;  // another question
            const title = (s.querySelector('h1,h2,h3,h4,p') || s).innerText?.trim().split('\n')[0].replace(/\s+/g, ' ');
            if (title) return title.slice(0, 80);
          }
        return '';
      };
      const repeats = new Map();
      for (const g of questions) repeats.set(norm(asked(g)), (repeats.get(norm(asked(g))) || 0) + 1);
      for (const g of questions) {
        const e = g.querySelector('input:not([type=file]):not([type=radio]):not([type=checkbox]),textarea');
        if (!e) continue;
        // A question asked once per section (MAS's First Choice for each internship period) is named by its section, so each has its own
        // answer. ponytail: radios keep their group's label (scan.js reads it first), so a repeated yes/no question shares one answer.
        let label = repeats.get(norm(asked(g))) > 1 && section(g) ? `${section(g)} — ${asked(g)}` : '';
        // A date field declares pattern="\d*" yet shows its date as "15/11/2026", so the browser calls every filled date invalid. Its value
        // is read as shown (FormSG's own aria-invalid still marks a date it refuses), and the question says the format it takes.
        if (e.matches('[placeholder="dd/mm/yyyy" i]')) {
          e.setAttribute('data-intern-value', e.value);
          label = (label || text(g.querySelector('label > div'))) + ' (dd/mm/yyyy)';
        }
        if (label) e.setAttribute('data-intern-label', label);
      }
      for (const group of document.querySelectorAll('[role=group]')) {
        const input = group.querySelector('input[type=file]');
        const receipt = [...group.querySelectorAll('span')].find(s => ATTACHED.test(text(s)));
        if (!input && !receipt) continue;
        // The question without its help text ("Documents must be uploaded in the following formats: …") or its number, which shifts
        // when a conditional question appears above it ("38.Attachment" becomes "41.Attachment", seen live) and would lose the upload's proof.
        const label = documentLabel(text(group.querySelector('label > div') || group.querySelector('label')).replace(/^\d+\.\s*/, ''));
        group.setAttribute('data-intern-upload', label);
        if (input) input.setAttribute('data-intern-label', label);
        if (!receipt) continue;
        const name = text(receipt).match(ATTACHED)[1], box = receipt.closest('[tabindex="0"]') || receipt.parentElement;
        receipt.setAttribute('data-intern-receipt', name);
        box.setAttribute('data-intern-kind', 'file');
        box.setAttribute('data-intern-label', label);
        box.setAttribute('data-intern-value', name);
      }
    },
    custom: e => dropdown(e) || receiptBox(e),
    // An attached receipt is never replaced here: verification compares it with the approved document.
    choose: (e, p) => dropdown(e) ? pick(e, p) : Promise.resolve(false),
    options: e => dropdown(e) ? choices(e) : [],
    async script({setMessage}) {
      // Proposes Submit: the runtime records it, and only the desktop clicks it after verifying every field.
      const submit = [...document.querySelectorAll('form button')].filter(visible).find(b => /\bsubmit now\b/i.test(text(b)));
      if (submit) R.call(submit, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
