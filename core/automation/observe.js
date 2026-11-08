(scan) => {
  // One page as plain data for teach mode and self-teach. Runs in the page; reads only, apart from scan.js's handles
  // (data-intern-control) and data-intern-button on each visible button so the app can click the one chosen.
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const text = e => (e?.innerText || e?.textContent || e?.value || e?.getAttribute?.('aria-label') || '').trim().replace(/\s+/g, ' ');
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  // A selector that survives a reload: an id that isn't generated, else a unique name. Otherwise the label finds it.
  const stable = e => {
    if (e.id && !/\d{3,}|:|^\d/.test(e.id) && document.querySelectorAll('#' + CSS.escape(e.id)).length === 1) return '#' + CSS.escape(e.id);
    const tag = e.tagName.toLowerCase(), name = e.getAttribute('name');
    if (name && document.querySelectorAll(`${tag}[name="${CSS.escape(name)}"]`).length === 1) return `${tag}[name="${CSS.escape(name)}"]`;
    return '';
  };
  // A custom dropdown shows its choice in its box, not in its (search) input. Mirrors shownValue in extension/adapters/recipe.js.
  const shownValue = e => {
    let box = e;
    const controls = el => el.querySelectorAll('input:not([type=hidden]),select,textarea,[role=combobox]').length;
    while (box.parentElement && !box.parentElement.matches('form,body,fieldset') && controls(box.parentElement) === 1) box = box.parentElement;
    const copy = box.cloneNode(true);
    copy.querySelectorAll('label,legend,input,[class*=placeholder],[role=listbox],[role=option],[aria-live]').forEach(n => n.remove());
    const shown = (copy.textContent || '').trim().replace(/\s+/g, ' ');
    return /^(select( one| an option)?|choose)(\.\.\.|…)?$/i.test(shown) ? '' : shown;
  };
  // Mirrors classify() in extension/runtime.js: the agent may click only what that would not call a submission.
  const classify = e => {
    const label = norm(e.innerText || e.value || e.getAttribute('aria-label'));
    const id = `${e.id} ${e.getAttribute('data-automation-id') || ''}`.toLowerCase();
    if (/submit|send application|apply now|finish application/.test(label) || label === 'apply' || /submit|btn-submit/.test(id)) return 'submit';
    if (/^(next|continue|save and continue|save & continue|apply manually|start application)$/.test(label) || e.name === 'next') return 'next';
    if (e.type === 'submit' && (e.form || e.getAttribute('type') === 'submit')) return 'submit';
    return '';
  };
  const fields = scan(null).map(f => {
    const e = document.querySelector(f.selector);
    const custom = e && e.tagName !== 'SELECT' && (e.getAttribute('role') === 'combobox' || e.getAttribute('aria-haspopup') === 'listbox');
    return {...f, css: e ? stable(e) : '', widget: custom ? 'aria-combobox' : 'native', value: custom && !f.value ? shownValue(e) : f.value,
      named: !!e && (f.label === e.getAttribute('name') || f.label === e.id),
      outline: e ? `${e.tagName.toLowerCase()} role=${e.getAttribute('role') || ''} class=${String(e.className || '').slice(0, 60)}` : ''};
  });
  const buttons = [...document.querySelectorAll('button,input[type=submit],input[type=button],a[role=button],[role=button]')]
    .filter(e => visible(e) && !e.disabled && !e.closest('[role=listbox]') && text(e))
    .map((e, i) => {
      e.setAttribute('data-intern-button', 'b' + i);
      return {id: 'b' + i, text: text(e).slice(0, 120), kind: classify(e),
        css: stable(e) || e.tagName.toLowerCase() + (e.getAttribute('type') === 'submit' ? '[type=submit]' : '')};
    });
  const headings = [...document.querySelectorAll('h1,h2,[role=status]')].filter(visible).map(text).filter(Boolean).slice(0, 5);
  return {url: location.href, fields, buttons, headings};
}
