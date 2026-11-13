globalThis.scanInternFields = (rootSelector) => {
  const root = typeof rootSelector === 'string' ? document.querySelector(rootSelector) : rootSelector || document;
  if (!root) return [];
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const text = e => (e?.innerText || e?.textContent || '').trim();
  const labelText = e => { const copy = e.cloneNode(true); copy.querySelectorAll('input,select,textarea,button,[role=listbox],[role=status],.filename,.file-upload-success,.application-field').forEach(c=>c.remove()); return text(copy).replace(/\s+/g, ' '); };
  const controls = [...root.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]),select,textarea,[role=combobox],[role=checkbox],[role=radio],[role=spinbutton],[contenteditable=true],button[aria-haspopup=listbox],[data-intern-kind],[data-automation-id="resumeUpload"]:not(:has(input[type=file])) [data-automation-id="file-upload-item"],[data-field-path] button[aria-pressed]')]
    // Workday's utility bar includes a language listbox, and Ashby's "Autofill from resume" pane an upload, neither an applicant question.
    // react-select (Greenhouse) keeps a hidden required text input beside its combobox; it is not a question.
    .filter(e => (visible(e) || e.type === 'file') && e.getAttribute('data-automation-id') !== 'beecatcher' && !(e.type === 'text' && e.matches('[aria-hidden=true][tabindex="-1"]')) && !e.closest('[role=listbox],[data-automation-id="utilityButtonBar"],[class*=_autofillPane]'));
  const counts = new Map();
  // Native validity misleads where the site keeps the answer elsewhere: an adapter-read dropdown's emptied search input,
  // or one box of a required checkbox group that another ticked box already satisfies. The site's own aria-invalid still counts.
  const nativeInvalid = e => !!(e.validity && !e.validity.valid) && !e.hasAttribute('data-intern-value') &&
    !(e.type === 'checkbox' && e.name && [...root.querySelectorAll('input[type=checkbox]')].some(c => c.name === e.name && c.checked));
  return controls.filter(e => !controls.some(p => p !== e && p.contains(e))).map((e, index) => {
    const labelled = (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => text((root.getElementById ? root : document).getElementById(id))).filter(Boolean).join(' ');
    const ownLabel = [...(e.labels || [])].map(labelText).join(' ');
    const fieldset = e.closest('fieldset,[role=radiogroup],[data-automation-id="formField"]');
    const uploadContainer = e.closest('[data-automation-id="resumeUpload"],[role="group"][aria-labelledby="Resume/CV-section"]');
    const receipt = e.getAttribute('data-automation-id') === 'file-upload-item' ? e : e.type === 'file' ? uploadContainer?.querySelector('[data-automation-id="file-upload-item"]') : null;
    const uploaded = !!receipt;
    const prompt = e.getAttribute('data-uxi-widget-type') === 'selectinput' ? e.closest('[data-automation-id="multiselectInputContainer"]') : null;
    const selected = prompt ? [...prompt.querySelectorAll('[data-automation-id="selectedItem"] [data-automation-id="promptOption"]')].map(text) : [];
    const resumeUpload = (e.type === 'file' || uploaded) && uploadContainer;
    // Workday listbox aria-labels include the selection; use the stable associated label.
    const listboxLabel = e.getAttribute('aria-haspopup') === 'listbox' ? ownLabel || text(fieldset?.querySelector('legend')) : '';
    // Greenhouse labels every upload input "Attach"; its group names the document ("Resume/CV", "Cover Letter").
    const uploadGroup = e.type === 'file' && e.closest('[role=group][aria-labelledby]');
    const uploadLabel = uploadGroup ? text((root.getElementById ? root : document).getElementById(uploadGroup.getAttribute('aria-labelledby'))) : '';
    // A question's own label beside its options or unlabelled input (Chakra forms such as FormSG, Lever's custom questions, Ashby's field entries).
    const choiceGroup = e.closest('[role=group],.application-question,[data-field-path]');
    const question = choiceGroup && [...choiceGroup.querySelectorAll('legend,label,.application-label')].find(l => !l.querySelector('input'));
    const groupQuestion = question ? labelText(question).replace(/\s*[*✱]\s*$/, '') : '';
    // A native adapter names controls the generic rules cannot (data-intern-label/-kind/-value).
    let label = e.getAttribute('data-intern-label') || listboxLabel || labelled || uploadLabel || e.getAttribute('aria-label') || ownLabel || text(fieldset?.querySelector('legend,label')) || (resumeUpload ? 'Resume' : '') || groupQuestion || e.getAttribute('data-automation-id') || e.name || '';
    if (e.type === 'checkbox' && e.closest('[data-automation-id$="-CheckboxGroup"]')) {
      const question = text(e.closest('[data-automation-id^="formField-"]')?.querySelector('legend'));
      if (question) label = question + ' — ' + label;
    }
    const dateGroup = e.closest('[data-automation-id="dateSection"],fieldset');
    let dateRequired = false;
    if (/^(month|day|year)$/i.test(label.trim()) && dateGroup) {
      const legend = text(dateGroup.querySelector('legend'));
      const context = legend.replace(/\s*\*\s*$/, '').replace(/\s*\(Actual or Expected\)$/i, '');
      if (/^(from|to|start date|end date)$/i.test(context)) {
        label = context + ' ' + label;
        dateRequired = /[*✱✳]/.test(legend);
      }
    }
    // Workday labels every website row just "URL"; its rows line up with the profile's links.
    const groupContainer = e.closest('[data-intern-group], [data-automation-id="workExperienceSection"], [data-automation-id="educationSection"], [role="group"][aria-labelledby="Work-Experience-section"], [role="group"][aria-labelledby="Education-section"], [role="group"][aria-labelledby="Languages-section"], [aria-labelledby="Websites-section"]');
    const group = groupContainer?.getAttribute('data-intern-group') || (groupContainer?.getAttribute('aria-labelledby') === 'Languages-section' ? 'language_proficiency' : groupContainer?.getAttribute('aria-labelledby') === 'Websites-section' ? 'websites' : groupContainer?.getAttribute('data-automation-id') === 'workExperienceSection' || groupContainer?.getAttribute('aria-labelledby') === 'Work-Experience-section' ? 'experience' : groupContainer ? 'education' : '');
    const rows = groupContainer ? [...groupContainer.querySelectorAll('[data-intern-row],[data-automation-id="workExperience"],[data-automation-id="education"],[role="group"][aria-labelledby$="-panel"],[aria-labelledby^="Websites-"][aria-labelledby$="-panel"]')] : [];
    const row = Math.max(0, rows.findIndex(r => r.contains(e)));
    // Ashby asks yes/no questions with a pair of pressed-state buttons.
    const pressed = e.matches('button[aria-pressed]');
    const type = e.getAttribute('data-intern-kind') || (pressed ? 'radio' : uploaded ? 'file' : prompt || e.getAttribute('aria-haspopup') === 'listbox' ? 'combobox' : e.getAttribute('role') || e.type || e.tagName.toLowerCase());
    const radio = type === 'radio';
    if (radio) label = (fieldset && (text(fieldset.querySelector('legend,[data-question]')) || fieldset.getAttribute('aria-label') || text(document.getElementById(fieldset.getAttribute('aria-labelledby'))) || labelText(fieldset.querySelector(':scope > label:not(:has(input))') || document.createElement('i')))) || groupQuestion || label;
    if (type === 'checkbox' && !e.closest('[data-automation-id$="-CheckboxGroup"]') && groupQuestion && choiceGroup.querySelectorAll('input[type=checkbox]').length > 1 && label !== groupQuestion)
      label = groupQuestion + ' — ' + label;
    const base = `${group}:${row}:${label.toLowerCase()}:${radio ? e.name : ''}`;
    const ordinal = counts.get(base) || 0;
    counts.set(base, ordinal + 1);
    const key = `${base}:${ordinal}`;
    // The selector is an ephemeral handle; durable identity uses section, row and label.
    e.setAttribute('data-intern-control', String(index));
    // Each radio is its own control; its options are every choice of its question, so an answer can be picked rather than typed.
    const choiceText = r => [...(r.labels || [])].map(labelText).join(' ') || r.getAttribute('aria-label') || r.value || text(r);
    const choices = !radio ? [] : pressed ? [...(choiceGroup?.querySelectorAll('button[aria-pressed]') || [e])]
      : e.name ? [...root.querySelectorAll('input[type=radio]')].filter(r => r.name === e.name) : [...(fieldset?.querySelectorAll('[role=radio],input[type=radio]') || [e])];
    const options = e.tagName === 'SELECT' ? [...e.options].map(o => o.text.trim()) : radio ? choices.map(choiceText) : selected;
    let value = e.isContentEditable ? e.textContent : ('value' in e ? e.value : text(e));
    if (type === 'combobox' && e.tagName === 'BUTTON') value = text(e);
    // react-select shows its choice beside the input, which only holds search text.
    // Its input sits in a [data-value] container; unchosen, typed search text is not an answer.
    if (type === 'combobox' && e.parentElement?.matches('[data-value]')) {
      value = text(e.parentElement.parentElement.querySelector('[class*="-singleValue"]'));
      // The runtime notes the option it picked, which may show abbreviated ("Singapore +65" shows "+65"), while that display stands.
      if (value && e.getAttribute('data-intern-shown') === value) value = e.getAttribute('data-intern-chosen');
    }
    if (prompt) value = selected.join(', ');
    if (e.tagName === 'SELECT') value = e.value ? e.selectedOptions[0]?.text.trim() || '' : '';
    if (type === 'combobox' && /^(select one|select an option|choose|select\.\.\.)$/i.test(value.trim())) value = '';
    if (type === 'checkbox' || radio) value = pressed ? e.getAttribute('aria-pressed') === 'true' : e.checked ?? e.getAttribute('aria-checked') === 'true';
    if (type === 'file') value = [...(e.files || [])].map(f => f.name).join(', ');
    if (uploaded) value = text(receipt.querySelector('[data-automation-id="file-upload-item-name"]'));
    if (e.hasAttribute('data-intern-value')) value = e.getAttribute('data-intern-value');
    if (e.type === 'password') value = ''; // Never return a password to the scanner.
    const option = radio ? choiceText(e) : '';
    return {key, label: label.replace(/\s*\*\s*$/, '').trim(), selector: `[data-intern-control="${index}"]`,
      kind: type, value, options, option, group, row, uploaded,
      split_phone: e.id === 'phoneNumber--phoneNumber' && !!root.querySelector('[id="phoneNumber--countryPhoneCode"]'),
      required: dateRequired || !!e.required || e.getAttribute('aria-required') === 'true' || /[*✱✳]/.test(label),
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
      invalid: [...(e.closest('fieldset,[data-automation-id="formField"]')?.querySelectorAll('[data-automation-id="inputAlert"]') || [])].some(a=>visible(a)&&text(a)) || e.getAttribute('aria-invalid') === 'true' || nativeInvalid(e) || (uploaded && (!receipt.querySelector('[data-automation-id="file-upload-successful"]') || uploadContainer.querySelectorAll('[data-automation-id="file-upload-item"]').length !== 1)),
      readonly: !!e.readOnly};
  });
}
;
