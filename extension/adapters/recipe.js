/* Site recipes (core/automation/recipes.py): one generic native adapter driven by data instead of a per-site file.
   A recipe names what the generic scanner can't (missing labels, custom dropdowns) and which buttons continue or submit.
   Like monee.js it sets only desktop-approved values and never chooses one itself. */
globalThis.internRecipeAdapter = (R, recipe) => {
  const text = e => (e?.innerText || e?.textContent || e?.value || '').trim().replace(/\s+/g, ' ');
  const norm = v => String(v ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  const visible = e => !!(e?.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (ready, ms = 1500) => { for (let t = 0; t < ms && !ready(); t += 50) await pause(50); return !!ready(); };
  const typeText = (e, value) => {
    if (!(e instanceof HTMLInputElement)) return;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', {bubbles: true}));
  };
  // A custom dropdown shows its choice in its box, not in its (search) input. Mirrors shownValue in core/automation/observe.js.
  // ponytail: the box is the largest ancestor holding only this control; a site that nests two dropdowns in one box needs a css entry per box.
  const shownValue = e => {
    let box = e;
    const controls = el => el.querySelectorAll('input:not([type=hidden]),select,textarea,[role=combobox]').length;
    while (box.parentElement && !box.parentElement.matches('form,body,fieldset') && controls(box.parentElement) === 1) box = box.parentElement;
    const copy = box.cloneNode(true);
    copy.querySelectorAll('label,legend,input,[class*=placeholder],[role=listbox],[role=option],[aria-live]').forEach(n => n.remove());
    const shown = (copy.textContent || '').trim().replace(/\s+/g, ' ');
    return /^(select( one| an option)?|choose)(\.\.\.|…)?$/i.test(shown) ? '' : shown;
  };
  // The control a label names: aria-label, its <label>, or its placeholder.
  const byLabel = match => {
    const want = norm(match);
    const own = [...document.querySelectorAll('[aria-label],[placeholder]')].filter(e => norm(e.getAttribute('aria-label')) === want || norm(e.placeholder) === want);
    const labelled = [...document.querySelectorAll('label')].filter(l => norm(text(l).replace(/\s*\*\s*$/, '')) === want)
      .map(l => l.control || l.querySelector('input,select,textarea,[role=combobox]')).filter(Boolean);
    const found = [...new Set([...own, ...labelled])].filter(e => visible(e) || e.type === 'file');
    return found.length === 1 ? found[0] : null;
  };
  const locate = f => {
    if (!f.css) return byLabel(f.match);
    const found = [...document.querySelectorAll(f.css)];
    return found.length === 1 ? found[0] : null;
  };
  const options = () => [...document.querySelectorAll('[role=option]')].filter(visible);
  const exact = value => options().find(o => norm(text(o)) === norm(value));
  const open = async e => {
    e.focus();
    e.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
    e.click();
    return until(() => options().length, 1000);
  };
  const close = e => { e.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); e.blur(); };
  const widget = e => e?.getAttribute?.('data-intern-widget');

  async function choose(e, p) {
    const have = norm(shownValue(e)), want = norm(p.value);
    if (have === want || (have && !p.replace)) return false;  // Never replace a choice it did not make; verification reports it.
    if (!await open(e) && widget(e) === 'click-list') return false;
    if (widget(e) === 'aria-combobox') { typeText(e, String(p.value)); await pause(200); }
    if (!await until(() => exact(p.value), 1500)) { close(e); return false; }
    exact(p.value).click();
    return until(() => norm(shownValue(e)) === want, 1000);
  }

  async function listChoices(e, query) {
    if (!await open(e)) return [];
    if (widget(e) === 'aria-combobox' && query) { typeText(e, String(query)); await pause(300); }
    const seen = options().map(text);
    if (widget(e) === 'aria-combobox') typeText(e, '');
    close(e);
    return seen;
  }

  return {
    id: 'recipe:' + recipe.host, name: recipe.name || recipe.host, fill: 'direct',
    // Detection compares the host itself: a recipe never matches a look-alike domain.
    pattern: {test: url => { try { const u = new URL(url); return u.protocol === 'https:' && u.hostname === recipe.host; } catch { return false; } }},
    open: recipe.open || undefined,
    annotate() {
      // data-intern-* attributes are read by core/automation/scan.js and runtime.js classify(); the site renders nothing from them.
      for (const f of recipe.fields) {
        const e = locate(f);
        if (!e) continue;
        if (f.label) e.setAttribute('data-intern-label', f.label);
        if (f.kind) e.setAttribute('data-intern-kind', f.kind);
        if (f.widget !== 'native') {
          e.setAttribute('data-intern-widget', f.widget);
          e.setAttribute('data-intern-value', shownValue(e));
        }
      }
      for (const b of recipe.buttons) {
        for (const e of document.querySelectorAll(b.css)) {
          if (visible(e) && (!b.text || norm(text(e) || e.getAttribute('aria-label')) === norm(b.text))) e.setAttribute('data-intern-action', b.action);
        }
      }
    },
    custom: e => !!widget(e) && widget(e) !== 'native',
    choose,
    options: (e, query) => listChoices(e, query),
    async script({setMessage}) {
      // Proposes the recipe's button: the runtime records it, and only the desktop clicks it after verifying every field.
      const button = ['submit', 'next'].map(a => [...document.querySelectorAll(`[data-intern-action=${a}]`)].find(visible)).find(Boolean);
      if (button) R.call(button, 'click', []);
      else setMessage('complete-manually');
    },
  };
};
