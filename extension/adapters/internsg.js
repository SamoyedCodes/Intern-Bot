/* InternSG (www.internsg.com): every listing's "Apply for this position" opens the same one-page form at /job-apply/<id>, with
   no account. fill:'direct' lets the runtime write approved values into the plain inputs; this file names the fields, picks
   a country in the two country pickers and writes the summary into its rich-text editor. It never chooses a value itself.
   The form ends in a reCAPTCHA only you can tick; the desktop asks for it before it sends (engine.py UNSOLVED_CAPTCHA). */
(() => {
(globalThis.internAdapters ||= []).push(R => {
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };
  // The profile's wording for the form's labels ("Your name", "Your contact number"); a trailing star marks what the form requires.
  const LABELS = {applicant_name: 'Name *', applicant_nationality: 'Nationality', applicant_campus: 'Country of study',
    campus_same_nationality: 'I study or graduated in my country of nationality', applicant_email: 'Email address *',
    applicant_contact: 'Phone number *', applicant_period: 'Availability period *'};

  // Country picker (country-select-js): a text input beside a flag list. Names read "China (中国)"; the profile says "China".
  const country = e => !!e?.matches?.('#applicant_nationality, #applicant_campus');
  const plain = name => String(name).replace(/\s*\(.*\)\s*$/, '').trim();
  const countries = e => [...(e.closest('.country-select')?.querySelectorAll('li.country:not(.preferred)') || [])];
  const countryName = li => plain(li.querySelector('.country-name')?.textContent || '');
  async function pickCountry(e, p) {
    // The picker always holds a country (Singapore, or your last application's), so an approved one replaces it.
    if (norm(plain(e.value)) === norm(p.value)) return false;
    const box = e.closest('.country-select'), list = box?.querySelector('.country-list');
    const option = countries(e).find(li => norm(countryName(li)) === norm(p.value));
    if (!option) return false;
    if (list.classList.contains('hide')) box.querySelector('.selected-flag').click();  // The list takes clicks only while open.
    if (!await until(() => !list.classList.contains('hide'), 1000)) return false;
    option.click();
    return until(() => norm(plain(e.value)) === norm(p.value), 1000);
  }

  // Summary: a Quill editor over a hidden textarea. One paragraph per line; Quill takes pasted text as its own edit.
  const editor = e => !!e?.matches?.('.isg-quill-box .ql-editor');
  const written = e => [...e.children].map(c => c.textContent).join('\n').trim();
  async function write(e, p) {
    const have = written(e), same = () => norm(written(e)) === norm(p.value);
    if (same() || have && !p.replace) return false;  // Never replace text it did not write; verification reports it.
    e.focus();
    getSelection().selectAllChildren(e);
    const data = new DataTransfer();
    data.setData('text/plain', String(p.value));
    e.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
    const done = await until(same, 1500);
    e.blur();
    return done;
  }

  return {
    id: 'internsg', name: 'InternSG', fill: 'direct',
    pattern: /^https:\/\/www\.internsg\.com\/(job|job-apply)\//,
    open: 'a.btn-apply[href*="/job-apply/"]',
    annotate() {
      // data-intern-* attributes are read by core/automation/scan.js; the site renders nothing from them.
      for (const [id, label] of Object.entries(LABELS)) document.getElementById(id)?.setAttribute('data-intern-label', label);
      for (const e of document.querySelectorAll('#applicant_nationality, #applicant_campus')) {
        e.setAttribute('data-intern-kind', 'combobox');
        e.setAttribute('data-intern-value', plain(e.value));
      }
      document.getElementById('applicant_contact')?.setAttribute('data-intern-kind', 'tel');
      const summary = document.querySelector('.isg-quill-box .ql-editor');
      if (summary) {
        summary.setAttribute('data-intern-label', 'Executive summary of your resume *');
        summary.setAttribute('data-intern-kind', 'textarea');
        summary.setAttribute('data-intern-value', written(summary));
      }
    },
    custom: e => country(e) || editor(e),
    choose: (e, p) => country(e) ? pickCountry(e, p) : write(e, p),
    options: e => country(e) ? countries(e).map(countryName) : [],
    async script({setMessage}) {
      // Proposes Submit: the runtime records it, and only the desktop clicks it after verifying every field.
      const submit = document.getElementById('btnSubmit');
      if (submit) R.call(submit, 'click', []);
      else setMessage('complete-manually');
    },
  };
});
})();
