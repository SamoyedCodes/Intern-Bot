(rootSelector) => {
  const root = rootSelector ? document.querySelector(rootSelector) : document;
  if (!root) return [];
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const text = e => (e?.innerText || e?.textContent || '').trim();
  const labelText = e => { const copy = e.cloneNode(true); copy.querySelectorAll('input,select,textarea,button,[role=listbox]').forEach(c=>c.remove()); return text(copy).replace(/\s+/g, ' '); };
  const controls = [...root.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]),select,textarea,[role=combobox],[role=checkbox],[role=radio],[role=spinbutton],[contenteditable=true],button[aria-haspopup=listbox],[data-automation-id="resumeUpload"]:not(:has(input[type=file])) [data-automation-id="file-upload-item"]')]
    // Workday's utility bar includes a language listbox, not an applicant question.
    .filter(e => (visible(e) || e.type === 'file') && e.getAttribute('data-automation-id') !== 'beecatcher' && !e.closest('[role=listbox],[data-automation-id="utilityButtonBar"]'));
  const counts = new Map();
  return controls.filter(e => !controls.some(p => p !== e && p.contains(e))).map((e, index) => {
    const labelled = (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => text(document.getElementById(id))).filter(Boolean).join(' ');
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
    let label = listboxLabel || labelled || e.getAttribute('aria-label') || ownLabel || text(fieldset?.querySelector('legend,label')) || (resumeUpload ? 'Resume' : '') || e.getAttribute('data-automation-id') || e.name || '';
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
    const groupContainer = e.closest('[data-intern-group], [data-automation-id="workExperienceSection"], [data-automation-id="educationSection"], [role="group"][aria-labelledby="Work-Experience-section"], [role="group"][aria-labelledby="Education-section"]');
    const group = groupContainer?.getAttribute('data-intern-group') || (groupContainer?.getAttribute('data-automation-id') === 'workExperienceSection' || groupContainer?.getAttribute('aria-labelledby') === 'Work-Experience-section' ? 'experience' : groupContainer ? 'education' : '');
    const rows = groupContainer ? [...groupContainer.querySelectorAll('[data-intern-row],[data-automation-id="workExperience"],[data-automation-id="education"],[role="group"][aria-labelledby$="-panel"]')] : [];
    const row = Math.max(0, rows.findIndex(r => r.contains(e)));
    const type = uploaded ? 'file' : prompt || e.getAttribute('aria-haspopup') === 'listbox' ? 'combobox' : e.getAttribute('role') || e.type || e.tagName.toLowerCase();
    const radio = type === 'radio';
    if (radio && fieldset) label = text(fieldset.querySelector('legend,[data-question]')) || fieldset.getAttribute('aria-label') || label;
    const base = `${group}:${row}:${label.toLowerCase()}:${radio ? e.name : ''}`;
    const ordinal = counts.get(base) || 0;
    counts.set(base, ordinal + 1);
    const key = `${base}:${ordinal}`;
    // The selector is an ephemeral handle; durable identity uses section, row and label.
    e.setAttribute('data-intern-control', String(index));
    const options = e.tagName === 'SELECT' ? [...e.options].map(o => o.text.trim()) : selected;
    let value = e.isContentEditable ? e.textContent : ('value' in e ? e.value : text(e));
    if (type === 'combobox' && e.tagName === 'BUTTON') value = text(e);
    if (prompt) value = selected.join(', ');
    if (e.tagName === 'SELECT') value = e.value ? e.selectedOptions[0]?.text.trim() || '' : '';
    if (type === 'combobox' && /^(select one|select an option|choose|select\.\.\.)$/i.test(value.trim())) value = '';
    if (type === 'checkbox' || radio) value = e.checked ?? e.getAttribute('aria-checked') === 'true';
    if (type === 'file') value = [...(e.files || [])].map(f => f.name).join(', ');
    if (uploaded) value = text(receipt.querySelector('[data-automation-id="file-upload-item-name"]'));
    if (e.type === 'password') value = ''; // Never return a password to the scanner.
    const option = radio ? ownLabel || e.getAttribute('aria-label') || e.value : '';
    return {key, label: label.replace(/\s*\*\s*$/, '').trim(), selector: `[data-intern-control="${index}"]`,
      kind: type, value, options, option, group, row, uploaded,
      split_phone: e.id === 'phoneNumber--phoneNumber' && !!root.querySelector('[id="phoneNumber--countryPhoneCode"]'),
      required: dateRequired || !!e.required || e.getAttribute('aria-required') === 'true' || /[*✱✳]/.test(label),
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
      invalid: e.getAttribute('aria-invalid') === 'true' || !!(e.validity && !e.validity.valid) || (uploaded && (!receipt.querySelector('[data-automation-id="file-upload-successful"]') || uploadContainer.querySelectorAll('[data-automation-id="file-upload-item"]').length !== 1)),
      readonly: !!e.readOnly};
  });
}
