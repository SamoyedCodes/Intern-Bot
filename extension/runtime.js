/* Adapter writes are proposals; only exact desktop-resolved facts may reach the DOM. */
(() => {
  const normalize = value => String(value ?? '').trim().replace(/[\s*:✱✳]+$/g, '').replace(/\s+/g, ' ').toLowerCase();
  const native = {MutationObserver};
  for (const name of ['setTimeout','clearTimeout','setInterval','clearInterval','requestAnimationFrame','cancelAnimationFrame']) native[name]=window[name].bind(window);
  let active;
  // Workday clears the file input after upload; bind its digest to that exact receipt for this document.
  const verifiedUploads = new WeakMap();
  // Native adapters (extension/adapters/*.js) mark their own upload widgets and receipts the same way.
  const UPLOADS = '[data-automation-id=resumeUpload],[aria-labelledby="Resume/CV-section"],[data-intern-upload]';
  const RECEIPTS = '[data-automation-id=file-upload-item],[data-intern-receipt]';
  // A native adapter marks values the site filled in itself (Monee's resume parser); approved values may replace those.
  const siteFilled = e => !!e.hasAttribute?.('data-intern-site-filled');
  const receiptName = r => r.getAttribute('data-intern-receipt') || r.querySelector('[data-automation-id=file-upload-item-name]')?.textContent.trim();
  // Hand-written adapters register factories beside the extracted vendor adapters.
  const nativeAdapters = R => (globalThis.internAdapters || []).map(make => make(R));
  // Site recipes the desktop passes in (extension/adapters/recipe.js), used only where no other adapter matches.
  const recipeAdapters = (R, recipes) => (recipes || []).map(recipe => globalThis.internRecipeAdapter(R, recipe));
  function runtime(config, token, documentId) {
    const timers = new Set(), intervals = new Set(), frames = new Set(), observers = new Set();
    const abort = new AbortController(), policies = new WeakMap(), proposals = new Map(), denied = new WeakSet();
    const handles = new Map(), rowActions = new Set(), uploading = new WeakSet();
    const events = [], problems = new Map(), actions = new Map();
    const url = location.href;
    // expired: the adapter ran out of time on this page; the desktop then fills what it has approved without it (config.direct).
    let running = true, expired = false, status = 'prepared', lastChange = performance.now(), started = false, sequence = 0, picker;
    const live = () => {if(running && location.href !== url)stop();return running;};
    const report = (kind, message, field = '') => problems.set(`${kind}:${field}:${message}`, {kind, message, field});
    const stop = () => {
      running = false;
      abort.abort();
      timers.forEach(native.clearTimeout); intervals.forEach(native.clearInterval); frames.forEach(native.cancelAnimationFrame); observers.forEach(o => o.disconnect());
      timers.clear(); intervals.clear(); frames.clear(); observers.clear(); proposals.clear();
    };
    window.addEventListener('hashchange',stop,{signal:abort.signal});
    window.addEventListener('popstate',stop,{signal:abort.signal});
    const safe = fn => (...args) => { if (live()) { try { Promise.resolve(fn(...args)).catch(fail); } catch { fail(); } } };
    const fail = () => { if(live()) report('browser', 'The site adapter could not complete this layout. Inspect the application and resume.'); };
    const environment = {
      MutationObserver: class {
        constructor(fn) { this.observer = new native.MutationObserver(safe(fn)); observers.add(this.observer); }
        observe(...args) { if(live()) this.observer.observe(...args); }
        disconnect() { this.observer.disconnect(); observers.delete(this.observer); }
        takeRecords() { return this.observer.takeRecords(); }
      },
      setTimeout(fn, delay=0, ...args) { if(!live()) return 0; const id=native.setTimeout(() => {timers.delete(id); safe(fn)(...args);}, delay);timers.add(id);return id; },
      clearTimeout(id) {timers.delete(id);native.clearTimeout(id);},
      setInterval(fn,delay=0,...args) {if(!live())return 0;const id=native.setInterval(safe(fn),delay,...args);intervals.add(id);return id;},
      clearInterval(id) {intervals.delete(id);native.clearInterval(id);},
      requestAnimationFrame(fn) {if(!live())return 0;const id=native.requestAnimationFrame(t=>{frames.delete(id);safe(fn)(t);});frames.add(id);return id;},
      cancelAnimationFrame(id) {frames.delete(id);native.cancelAnimationFrame(id);}
    };
    const dom = e => e instanceof Node || e instanceof CSSStyleDeclaration || e instanceof DOMTokenList || (typeof DOMStringMap!=='undefined' && e instanceof DOMStringMap) || e === window || e === location;
    const visible = e => e instanceof Element && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
    const isError = e => {
      const upload=e.closest('[data-automation-id=file-upload-item]');
      const uploaded=upload?.querySelector('[data-automation-id=file-upload-item-name]')?.textContent.trim();
      const notice=e.matches('[data-automation-id=ariaLiveMessage]')&&uploaded&&normalize(e.textContent)===normalize(`${uploaded} successfully uploaded`);
      return visible(e)&&e.textContent.trim()&&!notice;
    };
    // A Workday dropdown button shows its choice; its value is the option's internal ID once saved.
    const shownChoice = e => { const text = normalize(e.innerText || e.textContent); return text === 'select one' ? '' : text; };
    const readable = e => e instanceof HTMLSelectElement ? (e.value ? e.selectedOptions[0]?.textContent || '' : '') : ['checkbox','radio'].includes(e.type) ? e.checked : e.matches?.('button[aria-haspopup=listbox]') ? shownChoice(e) : e.value ?? e.textContent;
    // Employers reformat phone numbers ("55512345" becomes "5551 2345").
    const phone = p => /^profile:phone(_number)?$/.test(p.ref || ''), digits = v => String(v ?? '').replace(/\D/g, '');
    const matches = (e, p) => e.type === 'radio' ? e.checked === (normalize(e.labels?.[0]?.textContent || e.getAttribute('aria-label') || e.value) === normalize(p.value)) : e.type === 'checkbox' ? e.checked === p.value : phone(p) || e.type === 'tel' ? digits(readable(e)) === digits(p.value) : normalize(readable(e)) === normalize(p.value);
    function assign(e, key, value) {
      if (!dom(e)) { e[key] = value; return value; }
      if (!live()) return value;
      if (e === location || e === window || ['innerHTML','outerHTML','textContent','innerText'].includes(key)) {
        report('browser', 'Adapter requested an unverified document change. Continue manually.'); return value;
      }
      if (!['value','checked','files','selectedIndex'].includes(key)) { report('browser', 'Adapter requested an unsupported control mutation.'); return value; }
      if(e.disabled || e.readOnly || !e.isConnected)return value;
      const p = policies.get(e);
      if (!p) { proposals.set(e, {key,value}); denied.add(e); return value; }
      if (p.omit || p.value === null || p.value === undefined) { denied.add(e); return value; }
      if (e.type === 'password') { report('verification', 'Complete employer sign-in in the browser.'); return value; }
      if (e.type === 'file' || key === 'files') { void upload(value, e); return value; }
      const existing = readable(e);
      if (existing !== '' && existing !== false && !matches(e,p) && !p.replace && !siteFilled(e)) {
        report('conflict', 'Existing browser value conflicts with the profile. Resolve it before resuming.', p.key); denied.add(e); return value;
      }
      let desired = p.value;
      if (e instanceof HTMLSelectElement) {
        const options = [...e.options].filter(o=>normalize(o.textContent)===normalize(desired));
        if (options.length !== 1) {report('answer', 'The exact approved option is not offered by this form.',p.key);return value;}
        desired = options[0].value;key='value';
      } else if (e.type === 'radio') {desired = normalize(e.labels?.[0]?.textContent || e.getAttribute('aria-label') || e.value) === normalize(p.value);key='checked';}
      else if (e.type === 'checkbox') {if(typeof desired!=='boolean'){report('answer','Approve a Boolean answer for this checkbox.',p.key);return value;}key='checked';}
      const proto = e instanceof HTMLInputElement ? HTMLInputElement.prototype : e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : null;
      const setter = proto && Object.getOwnPropertyDescriptor(proto,key)?.set;
      // React (Workday) only notices checkbox and radio changes made by a click; a radio cannot be clicked off.
      if (key === 'checked') {if (e.checked !== desired && (desired || e.type === 'checkbox')) e.click();}
      else if (setter) {
        // Workday saves date parts and textareas on blur, and blur() only fires on a focused control.
        if(e instanceof HTMLTextAreaElement||e.matches('[role=spinbutton]')&&e.closest('[data-automation-id=dateInputWrapper]'))e.focus();
        // A typeahead opens its suggestions only on a change, so retyping its current value (a resumed Ashby location) would leave the adapter waiting for them.
        if(e.matches('input[role=combobox],input[aria-haspopup=listbox]')&&e.value===String(desired)){setter.call(e,'');e.dispatchEvent(new Event('input',{bubbles:true}));}
        setter.call(e, desired);
      } else e[key] = desired;
      denied.delete(e); lastChange = performance.now(); e.removeAttribute('data-intern-site-filled');
      return value;
    }
    function classify(e) {
      // A recipe's button hint may raise a click to a submission, but lower one to Next only when you were seen doing that.
      const hint = config.recipe && e.getAttribute('data-intern-action');
      if (hint === 'submit') return 'submit';
      const natural = siteClassify(e);
      return hint === 'next' && (natural !== 'submit' || config.recipe.origin === 'taught') ? 'next' : natural;
    }
    function siteClassify(e) {
      const text = normalize(e.innerText || e.value || e.getAttribute('aria-label'));
      const id = `${e.id} ${e.getAttribute('data-automation-id') || ''}`.toLowerCase();
      if (/submit|send application|apply now|finish application/.test(text) || text==='apply' || /submit|btn-submit/.test(id)) return 'submit';
      if (/^(next|continue|save and continue|save & continue|apply manually|start application)$/.test(text) || /navigation-next|footernext|applymanually|btnnext|footer-next|continue-button|application-next-step|ja_sv_cw_next_footer_btn/.test(id) || e.name === 'next') return 'next';
      if(e.type === 'submit' && (e.form || e.getAttribute('type') === 'submit'))return 'submit';
      return '';
    }
    function action(e, method='click') {
      if(!live() || !e?.isConnected)return;
      if(e.matches?.('[data-automation="career-history-save-button"],[data-automation="education-save-button"],[data-automation="skills-save-button"],[data-automation="save-button"]')) {
        const container=e.closest('[data-automation$="form-drawer"],li,form');
        const controls=container?[...container.querySelectorAll('input:not([type=hidden]),select,textarea')]:[];
        if(!controls.length || controls.some(c=>!policies.has(c))) {rowActions.add(e);return;}
        if(controls.some(c=>!matches(c,policies.get(c)) || c.validity&&!c.validity.valid)) {report('validation','Verify every row field before saving it.');return;}
        rowActions.delete(e);e.click();return;
      }
      const kind = method === 'submit' || method === 'requestSubmit' ? 'submit' : classify(e);
      if (kind) {
        let id = [...actions].find(([,a])=>a.element===e)?.[0];
        if(!id){id=crypto.randomUUID();actions.set(id,{element:e,kind,method});}
        status='action-pending'; return;
      }
      if (/delete|remove|reset/i.test(`${e.id} ${e.getAttribute?.('data-automation-id')} ${e.innerText || ''}`)) {report('conflict','Existing rows or attachments must be removed manually.');return;}
      const control = e.matches?.('input,select,textarea,[role=checkbox],[role=radio]') ? e : e.closest?.('label')?.control;
      if (control && ['checkbox','radio'].includes(control.type)) {
        assign(control,'checked',!control.checked);
        if(!denied.has(control)){control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));}
        return;
      }
      if (e.matches?.('[role=option],option,[data-automation-id=promptOption],[data-automation-id=menuItem]')) {
        // An option belongs to the dropdown that controls its list, not to whichever picker was clicked last (a replayed proposal can move that).
        const list = e.closest('[role=listbox]'), owner = list?.id && document.querySelector(`[aria-controls="${CSS.escape(list.id)}"]`);
        if (owner) picker = owner;
        const p = picker && policies.get(picker);
        if(picker && !p){proposals.set(picker,{key:'option',value:e});return;}
        // A react-select left blank on purpose or still unanswered: the adapter's guess is dropped and its menu closed; verification asks.
        if(p&&(p.omit||p.value==null)&&reactSelect(picker)){close(picker);return;}
        if(!p || normalize(e.innerText || e.textContent)!==normalize(p.value)){
          // The adapter guesses options from the profile; an approved value selects its own exact option instead.
          const exact=p&&!p.omit&&p.value!=null&&p.value!==''?[...(e.closest('[role=listbox]')?.querySelectorAll('[role=option]')||[])].filter(o=>normalize(o.innerText||o.textContent)===normalize(p.value)):[];
          if(exact.length!==1){report('answer','Choose the exact approved dropdown option manually.',p?.key||'');return;}
          e=exact[0];
        }
      }
      if (e.matches?.('[role=combobox],[aria-haspopup=listbox]')) picker=e;
      const text=normalize(e.innerText || e.getAttribute?.('aria-label'));
      // Lever's location typeahead lists its suggestions as plain divs.
      if (!e.matches?.('input,select,textarea,[role=option],option,[data-automation-id=promptOption],[data-automation-id=menuItem],[role=combobox],[aria-haspopup=listbox],.dropdown-results > div') && !/^(add|add another|add education|add experience|add work experience|add language|add website|add employment|add row|search|browse|upload resume)$/.test(text)) {
        report('browser','An unrecognized adapter action needs manual review.');return;
      }
      e.click();
      // The adapter picked the approved react-select option itself: note it for the read-back, now and once the display has updated.
      if(e.matches?.('[role=option]')&&reactSelect(picker)){const input=picker,text=(e.innerText||e.textContent).trim();noteChoice(input,text);native.setTimeout(()=>input.isConnected&&noteChoice(input,text),250);}
    }
    const R = {
      environment, stop, live,
      // Vendor waits have no deadline. Workday's search popup stays open with its results, so without one the rest of the section (the resume upload) never runs.
      waitFor(predicate, root, options, timeout=5000) {
        return new Promise(resolve=>{if(!live())return;if(predicate()){resolve(true);return;}const observer=new environment.MutationObserver(()=>{if(predicate()){observer.disconnect();resolve(true);}});observer.observe(root,options);
          environment.setTimeout(()=>{observer.disconnect();resolve(false);},timeout);});
      },
      emit(type, data={}) {if(live())events.push({sequence:++sequence,type,...data});if(events.length>100)events.shift();},
      update(e,key,op,rhs){if(dom(e)){report('browser','Unverified compound DOM mutation blocked.');return e[key];}if(op==='??=')return e[key]??(e[key]=rhs());if(op==='||=')return e[key]||(e[key]=rhs());if(op==='&&=')return e[key]&&(e[key]=rhs());if(op==='+=')return e[key]+=rhs();throw Error('Unsupported compound assignment');},
      assign,
      mutate(e,key,op,prefix){
        if(dom(e)){report('browser','An unverified DOM mutation was blocked.');return;}
        if(op==='delete')return delete e[key];
        if(op==='++')return prefix?++e[key]:e[key]++;
        if(op==='--')return prefix?--e[key]:e[key]--;
        throw Error('Unsupported mutation');
      },
      call(e,key,args,optional=false) {
        if(optional&&(e==null||e[key]==null))return;
        if(typeof e==='function' && key==='bind' && dom(args[0]))return (...tail)=>R.call(e,'call',[...args,...tail]);
        if(typeof e === 'function' && ['call','apply'].includes(key) && dom(args[0])) {
          const target=args[0], values=key==='apply'?args[1]:args.slice(1);
          if(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)return assign(target,'value',values[0]);
          if(!live())return;
          report('browser','An unrecognized native DOM operation was blocked.');return;
        }
        if(e===Object && ['assign','defineProperty','defineProperties'].includes(key) && dom(args[0])){report('browser','Unverified DOM property mutation blocked.');return args[0];}
        if(!dom(e))return e[key](...args);
        if(!live())return;
        if(key==='addEventListener'){e.addEventListener(args[0],safe(args[1]),{...(typeof args[2]==='object'?args[2]:{capture:!!args[2]}),signal:abort.signal});return;}
        if(['click','submit','requestSubmit'].includes(key))return action(e,key);
        if(key==='dispatchEvent') {
          // react-select opens on the press itself, which action()'s click() never sends; without its menu the adapter waits forever.
          // Opening writes nothing, so it is allowed even where the adapter's value was refused; choosing an option is still checked.
          if(/^(click|mousedown|mouseup)$/.test(args[0].type)&&reactSelect(e)){picker=e;return e.dispatchEvent(...args);}
          if(denied.has(e))return false;
          if(args[0].type==='submit'){action(e,'submit');return false;}
          if(['Enter',' '].includes(args[0].key)){
            const event=args[0], p=policies.get(e);
            if(config.adapter==='workday'&&event.key==='Enter'&&event.cancelable&&prompt(e)&&p&&!p.omit&&p.value!=null&&
              (normalize(e.value)===normalize(p.value)||selections(e).includes(normalize(p.value)))){
              event.preventDefault();return e.dispatchEvent(event);
            }
            report('browser','A keyboard activation needs manual review.',p?.key||'');return false;
          }
          if(/^(click|mousedown|mouseup)$/.test(args[0].type)){action(e);return false;}
          return e.dispatchEvent(...args);
        }
        if(['setAttribute','removeAttribute','append','appendChild','prepend','remove','replaceWith','insertAdjacentHTML','write','writeln','execCommand','assign','replace','reload'].includes(key)) {report('browser','An unverified document or navigation change was blocked.');return;}
        if(!['querySelector','querySelectorAll','getElementById','getElementsByTagName','getElementsByClassName','evaluate','contains','matches','closest','getAttribute','hasAttribute','getBoundingClientRect','getClientRects','compareDocumentPosition','cloneNode','focus','blur','removeEventListener','getComputedStyle','getPropertyValue','scrollTo','scrollIntoView'].includes(key)){report('browser','An unrecognized DOM operation was blocked.');return;}
        return e[key](...args);
      },
      file(base64,name) {
        const descriptor=Object.values(config.files||{}).find(f=>f.fileName===name && f.resumeBase64===base64);
        if(!descriptor)return null;
        return new File([Uint8Array.from(atob(base64),c=>c.charCodeAt(0))],name,{type:descriptor.mime});
      },
      upload,
      resolveQuestions(questions) {
        return questions.flatMap((q,index)=>{
          let label=normalize(q.question);
          const choices=q.options?.map(normalize).join(' ');
          if(choices&&label.endsWith(choices))label=normalize(label.slice(0,-choices.length));
          const candidates=[...handles.values()].map(e=>policies.get(e)).filter(p=>p&&normalize(p.label)===label);
          const values=new Set(candidates.map(p=>JSON.stringify([p.value,p.omit])));
          const p=candidates.length?(values.size===1?candidates[0]:null):config.answers?.[label];
          return p&&!p.omit&&p.value!=null?[{index,answer:typeof p.value==='boolean'?(p.value?'Yes':'No'):String(p.value)}]:[];
        });
      }
    };
    // A native adapter's hooks: annotate (labels the scanner can't infer), custom/choose/options (its own widgets), open (link to the form).
    const site = [...nativeAdapters(R), ...recipeAdapters(R, config.recipe && [config.recipe])].find(a => a.id === config.adapter);
    // hold/busy: the adapter defers fills while the site rewrites the form itself (Monee parses the uploaded resume).
    const policyOf = e => policies.get(e);
    async function upload(file, e) {
      if(!e || !live() || uploading.has(e))return false;
      const p=policies.get(e);
      if(!p){proposals.set(e,{key:'files',value:file});return false;}
      if(p.omit||p.value==null)return false;  // Left blank on purpose, or unanswered: verification asks for it.
      const descriptor=config.files?.[p.value];
      if(!descriptor){report('profile','Choose a supported resume or cover letter file.',p.key);return false;}
      const chosen=R.file(descriptor.resumeBase64,descriptor.fileName);
      if(!chosen)return false;
      const accepted=e.accept?.split(',').map(x=>x.trim().toLowerCase()).filter(Boolean)||[];
      if(accepted.length&&!accepted.some(a=>a===descriptor.mime||a===('.'+descriptor.fileName.split('.').pop().toLowerCase())||a.endsWith('/*')&&descriptor.mime.startsWith(a.slice(0,-1)))){report('profile','The form does not accept this document type. Choose a matching file.',p.key);return false;}
      if(e.files?.length){
        const digest=await crypto.subtle.digest('SHA-256',await e.files[0].arrayBuffer());
        if(!live())return false;
        if(e.files.length!==1||hex(digest)!==descriptor.digest){report('conflict','An existing upload differs from the selected file.',p.key);return false;}
        // A site can reject a file it wasn't ready for (Greenhouse loads its upload settings after the page): send ours once more.
        const last=sent.get(e);
        if(!last||last.tries>1||performance.now()-last.at<5000||acceptedUpload(e,e.files[0]))return true;
      }
      const container=e.closest(UPLOADS);
      const receipt=container?.querySelector(RECEIPTS), proof=container&&verifiedUploads.get(container);
      // The site may still be processing this exact file (Monee parses it; Workday shows it loading, with no delete button yet); sending it again would duplicate it.
      if(!proof?.receipt&&proof?.digest===descriptor.digest&&performance.now()-proof.at<30000)return false;
      if(receipt){
        if(proof?.receipt===receipt&&proof.digest===descriptor.digest)return true;
        const remove=receipt.querySelector('button[data-automation-id=delete-file]');
        if(!p.replace||!remove){report('conflict','The existing uploaded document must be checked manually, or approve the selected file as its replacement.',p.key);return false;}
        uploading.add(e);
        try {
          remove.click();
          for(let i=0;i<20&&receipt.isConnected&&live();i++)await pause(100);
          if(!live()||receipt.isConnected||!e.isConnected||container.querySelector('[data-automation-id=file-upload-item]'))return false;
        } finally {uploading.delete(e);}
      }
      if(container)verifiedUploads.set(container,{digest:descriptor.digest,name:descriptor.fileName,receipt:null,at:performance.now()});
      sent.set(e,{at:performance.now(),tries:(sent.get(e)?.tries||0)+1});
      const transfer=new DataTransfer();transfer.items.add(chosen);e.files=transfer.files;
      e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));lastChange=performance.now();return true;
    }
    const hex = buffer => [...new Uint8Array(buffer)].map(b=>b.toString(16).padStart(2,'0')).join('');
    const pause = ms => new Promise(resolve=>native.setTimeout(resolve,ms));
    // Whether the site shows this selected file as received.
    function acceptedUpload(e,selected){
      const container=e.closest('[data-automation-id=resumeUpload],#s3_upload_for_resume,[data-upload]')||e.closest('label')||e.parentElement;
      const receipts=[...container.querySelectorAll('[data-automation-id=file-upload-successful],.file-upload-success,.filename,.ashby-application-form-input-file-item-name,[role=status]')];
      return receipts.some(r=>visible(r)&&(r.getAttribute('data-automation-id')==='file-upload-successful'||r.matches('.filename,.ashby-application-form-input-file-item-name')&&r.textContent.includes(selected.name)||r.textContent.includes(selected.name)&&/uploaded|attached|complete|success/i.test(r.textContent)));
    }
    const sent=new WeakMap();  // File input → when this runtime last sent it a file, and how often.
    // Workday renders a dropdown's options only while it is open.
    async function listbox(e){
      if(!e?.isConnected||!e.matches('button[aria-haspopup=listbox]'))return [];
      const items=()=>[...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('[role=option]:not(#select-one)')||[])].filter(o=>normalize(o.textContent)!=='select one');
      if(!items().length)e.click();
      for(let i=0;i<20&&!items().length;i++)await pause(100);
      return items();
    }
    const close = e => e.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    // Workday prompts load their options from the server only after Enter. Results with a radio or checkbox are choices; categories have none.
    const prompt = e => e?.isConnected && e.matches('[data-uxi-widget-type=selectinput][data-uxi-multiselect-id]');
    const selections = e => [...(e.closest('[data-automation-id=multiselectInputContainer]')?.querySelectorAll('[data-automation-id=selectedItem] [data-automation-id=promptOption]')||[])].map(o=>normalize(o.textContent));
    const choice = o => o.querySelector('input[type=radio],input[type=checkbox]');
    const optionText = o => (o.querySelector('[data-automation-id=promptOption]')||o).textContent.trim();
    const typeText = (e,text) => {Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,text);e.dispatchEvent(new Event('input',{bubbles:true}));};
    // react-select (Greenhouse): a search input in a [data-value] container; the choice shows beside it and opens on a press.
    const reactSelect = e => e?.isConnected && e.matches('input[role=combobox]') && e.parentElement?.matches('[data-value]');
    const reactShown = e => (e.parentElement.parentElement.querySelector('[class*="-singleValue"]')?.textContent || '').trim();
    // The picked option can show abbreviated ("Singapore +65" shows "+65"); the scanner reads it back while that display stands.
    const noteChoice = (e,text) => {e.setAttribute('data-intern-chosen',text);e.setAttribute('data-intern-shown',reactShown(e));};
    const reactItems = e => [...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('[role=option]')||[])];
    const press = e => {for(const type of ['mouseover','mousedown','mouseup','click'])e.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window}));};
    async function reactOptions(e,query){
      press(e);
      for(let i=0;i<10&&!reactItems(e).length;i++)await pause(100);
      // A location search lists nothing until typed.
      if(!reactItems(e).length&&query){e.focus();typeText(e,query);for(let i=0;i<20&&!reactItems(e).length;i++)await pause(100);}
      return reactItems(e);
    }
    async function reactChoose(e,p){
      const shown=reactShown(e);
      if(normalize(e.getAttribute('data-intern-chosen'))===normalize(p.value)&&e.getAttribute('data-intern-shown')===shown||normalize(shown)===normalize(p.value))return false;
      if(shown&&!p.replace)return false;
      const exact=(await reactOptions(e,String(p.value))).filter(o=>normalize(o.textContent)===normalize(p.value));
      if(exact.length!==1){typeText(e,'');e.blur();return false;}
      exact[0].click();lastChange=performance.now();
      for(let i=0;i<10&&reactShown(e)===shown;i++)await pause(100);
      e.blur();
      if(reactShown(e)===shown)return false;
      noteChoice(e,exact[0].textContent.trim());
      return true;
    }
    async function search(e,query){
      const id=CSS.escape(e.getAttribute('data-uxi-multiselect-id'));
      const results=()=>[...document.querySelectorAll(`[data-uxi-popup-anchor="${id}"] [role=option],[data-associated-widget="${id}"] [role=option]`)];
      e.focus();typeText(e,query);
      const stale=new Set(results());
      for(const name of ['keydown','keypress','keyup'])e.dispatchEvent(new KeyboardEvent(name,{key:'Enter',code:'Enter',keyCode:13,bubbles:true,cancelable:true}));
      let fresh=[];
      for(let i=0;i<30&&!(fresh=results().filter(o=>!stale.has(o))).length;i++)await pause(100);
      return fresh.filter(choice);
    }
    // Restore the search text and close the results without choosing.
    const dismiss = (e,text) => {typeText(e,text);close(e);};
    async function pick(e,value){
      const chosen=()=>selections(e).includes(normalize(value));
      // A prompt that already shows a selection is left to verification.
      if(selections(e).length)return false;
      const text=e.value, exact=(await search(e,value)).filter(o=>normalize(optionText(o))===normalize(value));
      if(chosen())return true; // Workday may select a lone result itself.
      if(exact.length!==1){dismiss(e,text);return false;}
      choice(exact[0]).click();lastChange=performance.now();
      for(let i=0;i<10&&!chosen();i++)await pause(100);
      return chosen();
    }
    function alignRows(fields){
      if(config.adapter!=='workday')return fields;
      for(const [group,data,labels,property] of [['experience','jobData',['company','employer'],'company'],['education','educationData',['school or university','school'],'school']]){
        const rows=config.profile[data]||[], groups=new Map(), mapping=new Map(), used=new Set();
        for(const field of fields.filter(f=>f.group===group)){
          if(!groups.has(field.row))groups.set(field.row,[]);
          groups.get(field.row).push(field);
        }
        for(const [index,values] of groups){
          const identity=values.find(f=>labels.includes(normalize(f.label)));
          if(!identity||!identity.value)continue;
          let candidates=rows.map((row,i)=>({row,i})).filter(({row})=>normalize(row[property])===normalize(identity.value));
          const title=values.find(f=>normalize(f.label)==='job title');
          if(candidates.length>1&&title?.value)candidates=candidates.filter(({row})=>normalize(row.jobTitle)===normalize(title.value));
          const match=candidates.length===1&&!used.has(candidates[0].i)?candidates[0].i:rows.length+index;
          mapping.set(index,match);used.add(match);
        }
        for(const [index,values] of groups){
          if(!mapping.has(index)){
            const remaining=rows.findIndex((_,i)=>!used.has(i));
            mapping.set(index,remaining<0?rows.length+index:remaining);used.add(mapping.get(index));
          }
          for(const field of values){
            if(field.key)field.key=field.key.replace(`${group}:${field.row}:`,`${group}:${mapping.get(index)}:`);
            field.row=mapping.get(index);
          }
        }
      }
      return fields;
    }
    async function scan() {
      handles.clear();
      const formRoots=[...document.querySelectorAll('form')].filter(e=>visible(e)&&!e.parentElement.closest('form'));
      if(formRoots.length>1)report('browser','More than one form is present. Choose a single application form before autofilling.');
      const root=config.adapter==='account'?internAccount.controls().root:formRoots.length===1?formRoots[0]:document;
      if(formRoots.length>1&&config.adapter!=='account'){stop();return [];}
      site?.annotate?.(root);
      const roots=[root];
      for(let i=0;i<roots.length;i++)for(const element of roots[i].querySelectorAll('*'))if(element.shadowRoot)roots.push(element.shadowRoot);
      const fields=roots.flatMap((root,index)=>scanInternFields(root).map(f=>{
        const element=root.querySelector(f.selector), selector=`control:${handles.size}`;
        handles.set(selector,element);f.selector=selector;
        if(index)f.key=`shadow:${root.host.id||index}:`+f.key;
        f.file_digest='';
        return f;
      }));
      for(const field of fields.filter(f=>f.kind==='file')){
        const e=handles.get(field.selector), selected=e.files?.[0];
        const uploadContainer=e.closest(UPLOADS);
        const proof=uploadContainer&&verifiedUploads.get(uploadContainer), receipts=uploadContainer?.querySelectorAll(RECEIPTS);
        const receipt=receipts?.length===1?receipts[0]:null;
        if(proof?.receipt&&proof.receipt!==receipt){field.invalid=true;continue;}
        if(proof&&receipt&&!field.invalid&&receiptName(receipt)===proof.name){
          if(!proof.receipt)proof.receipt=receipt;
          if(proof.receipt===receipt)field.file_digest=proof.digest;
        }
        if(selected){
          const digest=hex(await crypto.subtle.digest('SHA-256',await selected.arrayBuffer()));
          field.file_digest=e.files.length===1?digest:'';
          field.invalid=field.invalid||!acceptedUpload(e,selected);
        }
      }
      return alignRows(fields);
    }
    function reviewSummary(){
      const root=document.querySelector('[data-automation-id=applyFlowReviewPage]');
      if(!root)return [...document.querySelectorAll('[data-automation-id="reviewField"],dl>dt')].filter(visible).map(e=>({
        label:(e.querySelector('label,dt')?.textContent||(e.tagName==='DT'?e.textContent:'')).trim(),
        value:(e.querySelector('dd,[data-value]')?.textContent||(e.tagName==='DT'?e.nextElementSibling?.textContent:'')||'').trim(),
        group:e.getAttribute('data-group')||'',row:Number(e.getAttribute('data-row')||0)
      }));
      const result=[], seen=new Set();
      const add=(label,value,node)=>{
        if(!node||!visible(node)||seen.has(node))return;
        seen.add(node);
        const container=node.closest('[aria-labelledby="Work-Experience-section"],[aria-labelledby="Education-section"],[aria-labelledby="Languages-section"]');
        const group={'Work-Experience-section':'experience','Education-section':'education','Languages-section':'language_proficiency'}[container?.getAttribute('aria-labelledby')]||'';
        const rows=container?[...container.querySelectorAll('[role=group][aria-labelledby$="-panel"]')]:[];
        if(group==='education'&&normalize(label)==='to (actual or expected)')label='To';
        result.push({label,value:normalize(value)==='no response'?'':value,group,row:Math.max(0,rows.findIndex(r=>r.contains(node))),layout:'workday'});
      };
      for(const label of root.querySelectorAll('label[for]')){
        const value=label.parentElement.querySelector(`#${CSS.escape(label.htmlFor)}`);
        if(value)add(label.innerText,value.innerText.trim(),value);
      }
      for(const label of root.querySelectorAll('[id^="rich-label"]')){
        const value=label.nextElementSibling;
        if(value)add(label.innerText,value.querySelector('ul')?[...value.querySelectorAll('li')].map(e=>e.innerText.trim()).join('; '):value.innerText.trim(),value);
      }
      for(const id of ['Legal-Name-section','Address-section','Email-Address-section','Phone-section']){
        const section=root.querySelector(`[aria-labelledby="${id}"]`), value=section?.querySelector('span[id]');
        if(value)add(section.querySelector('h4').innerText,value.innerText.trim(),value);
      }
      const skills=root.querySelector('[data-automation-id=skills]');
      if(skills)add('Skills',[...skills.querySelectorAll('li')].map(e=>e.innerText.trim()).join('; '),skills);
      const resume=root.querySelector('[aria-labelledby="Resume/CV-section"]');
      if(resume)add('Resume/CV',[...resume.querySelectorAll('[data-automation-id=file-upload-item-name]')].map(e=>e.innerText.trim()).join('; '),resume);
      return alignRows(result);
    }
    const observer=new native.MutationObserver(records=>{if(records.some(r=>r.type==='childList'||r.attributeName!=='data-intern-control'))lastChange=performance.now();});
    observer.observe(document,{subtree:true,childList:true,attributes:true,attributeFilter:['aria-invalid','disabled','hidden','aria-busy']});observers.add(observer);
    timers.add(native.setTimeout(()=>{if(live()){report('browser','The adapter reached its bounded wait limit. Inspect the form and resume.');stop();expired=true;}},20000));
    window.addEventListener('unhandledrejection',fail,{signal:abort.signal});
    const authControls=()=>internAccount.controls();
    return {
      token,document:documentId,R,
      scan,
      authorize(policiesBySelector) {
        if(!live())return;
        for(const [selector,p]of Object.entries(policiesBySelector)) {const e=handles.get(selector);if(e)policies.set(e,p);}
        for(const [e,proposal]of proposals){if(!e.isConnected){proposals.delete(e);continue;}if(!policies.has(e)||site?.hold?.(e,policyOf))continue;proposals.delete(e);if(proposal.key==='option'){picker=e;action(proposal.value);continue;}assign(e,proposal.key,proposal.value);if(!denied.has(e)&&e.type!=='file'){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();}}
        for(const [selector,p]of Object.entries(policiesBySelector)){
          const e=handles.get(selector);
          // A pressed-state choice button (Ashby yes/no): press the one whose text is the approved answer.
          if(e?.matches('button[aria-pressed]')){if(p.value!=null&&!p.omit&&normalize(e.innerText)===normalize(String(p.value))&&e.getAttribute('aria-pressed')!=='true')e.click();continue;}
          // A native adapter's own widgets are set by its choose(); a direct-fill adapter leaves every plain control to approved values.
          // Workday dropdown buttons are chosen by choose(): writing their value changes nothing visible, and the blur closes an open listbox.
          if(e && !site?.custom?.(e) && !e.matches('button[aria-haspopup=listbox]') && (p.ref?.startsWith('answer:') || p.ref==='profile:cover_letter' || p.ref==='profile:cover_letter_path' ||
            config.adapter==='workday' && !authControls().passwords.length && p.ref?.startsWith('profile:') && e.matches('input:not([type=file]),textarea,select') && !prompt(e) ||
            (site?.fill==='direct'||config.direct) && p.ref?.startsWith('profile:') && e.matches('input,textarea,select') && !prompt(e))){
            if(e.type==='file')void upload(null,e);
            else if(site?.hold?.(e,policyOf))proposals.set(e,{key:'value',value:p.value});
            else if(!matches(e,p)){assign(e,'value',p.value);if(!denied.has(e)){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();}}
          }
        }
        for(const e of rowActions)if(e.isConnected)action(e);
      },
      start() {
        if(started)throw Error('Adapter already started');started=true;status='in-progress';
        const adapter=site||createSpeedyAdapters(R).find(a=>a.id===config.adapter);
        if(!adapter)throw Error('Unknown adapter');
        const ctx={addEventListener:(target,...args)=>R.call(target,'addEventListener',args),onInvalidated:fn=>abort.signal.addEventListener('abort',fn,{once:true})};
        Promise.resolve(adapter.script({getProfile:async()=>config.profile,setMessage:message=>{if(live())status=message||status;},autofillSettings:{autoClickNextPage:true,autoSubmit:true,saveApplications:false,saveResponses:false},accountSettings:{accountEmail:"",accountPassword:""},ctx})).catch(fail);
      },
      snapshot(){return {summary:reviewSummary(),errors:(/\bVPS\|[0-9a-f-]{36}\b/i.test(document.body.innerText)||/something went wrong[\s\S]*please refresh the page and then try again/i.test(document.body.innerText)?1:0)+[...document.querySelectorAll('[role=alert],.field-error-msg,.form-error,[data-automation-id=inputError],[data-automation-id=inputAlert]')].filter(isError).length,status,live:live(),settled:performance.now()-lastChange>350&&timers.size<=1&&!site?.busy?.(policyOf),proposals:proposals.size,expired,events,problems:[...problems.values()],actions:[...actions].filter(([,a])=>a.element.isConnected&&visible(a.element)&&!a.element.disabled).map(([id,a])=>({id,kind:a.kind})),url};},
      async options(selector,query){
        const e=handles.get(selector);
        if(site?.custom?.(e))return site.options(e,query);
        if(prompt(e)){
          const text=e.value;
          if(!(query||text))return [];
          const found=await search(e,query||text);dismiss(e,text);
          return found.map(optionText);
        }
        // A typeahead (Ashby's location) lists suggestions only for typed text: the approved answer, else what is already typed.
        if(e?.isConnected&&e.matches('input[role=combobox],input[aria-haspopup=listbox]')){
          const text=e.value;
          const items=()=>[...(document.getElementById(e.getAttribute('aria-controls'))?.querySelectorAll('[role=option]')||[])];
          // A react-select dropdown (Greenhouse) lists every choice when pressed, so a wrong saved answer can't hide them.
          if(reactSelect(e)){
            const found=(await reactOptions(e,query||text)).map(o=>o.textContent.trim());typeText(e,'');e.blur();
            return found;
          }
          // A typeahead lists nothing until typed.
          if(!(query||text))return [];
          e.focus();typeText(e,'');typeText(e,query||text);
          for(let i=0;i<20&&!items().length;i++)await pause(100);
          const found=items().map(o=>o.textContent.trim());dismiss(e,text);
          return found;
        }
        const items=await listbox(e);
        if(items.length)close(e);
        return items.map(o=>o.textContent.trim());
      },
      // The adapter fills Workday dropdowns only from profile guesses and cannot search prompts; select the approved options it left unset.
      // ponytail: stops starting new controls after 5 s to stay inside the bridge's 8 s command limit (a Workday prompt can take ~4 s);
      // the engine calls choose again while it still selects something. Batch per control if one control ever needs more.
      async choose(){
        let chosen=0;const deadline=performance.now()+5000;
        for(const e of handles.values()){
          if(!live()||performance.now()>deadline)break;
          const p=policies.get(e), shown=()=>normalize(e.innerText||e.textContent);
          if(!p||p.omit||p.value==null||p.value===''||!e.isConnected)continue;
          if(site?.custom?.(e)){
            if(site.hold?.(e,policyOf))continue;
            if(await site.choose(e,siteFilled(e)?{...p,replace:true}:p)){chosen++;e.removeAttribute('data-intern-site-filled');}
            continue;
          }
          if(prompt(e)){if(await pick(e,String(p.value)))chosen++;continue;}
          if(reactSelect(e)){if(await reactChoose(e,p))chosen++;continue;}
          if(!e.matches('button[aria-haspopup=listbox]')||shown()===normalize(p.value))continue;
          if(shown()&&shown()!=='select one'&&!p.replace)continue;
          const exact=(await listbox(e)).filter(o=>normalize(o.innerText||o.textContent)===normalize(p.value));
          if(exact.length!==1){close(e);continue;}
          exact[0].click();chosen++;lastChange=performance.now();
          for(let i=0;i<10&&shown()!==normalize(p.value);i++)await pause(100);
        }
        return chosen;
      },
      openLink(id){
        if(config.adapter==='account'&&['signInLink','createAccountLink'].includes(id)&&live())return internAccount.open(id==='createAccountLink'?'create':'sign_in');
        const links=[...document.querySelectorAll(`[data-automation-id="${id}"]`)].filter(visible);
        if(config.adapter!=='workday'||!live()||!['signInLink','createAccountLink','adventureButton','applyManually','continueButton'].includes(id)||links.length!==1)return false;
        links[0].click();return true;
      },
      async openApplication(){
        // The posting renders after the document loads. Apply stays visible behind its Start Your Application dialog, so Apply Manually goes first.
        // A signed-in candidate with a saved draft gets Continue Application instead of Apply.
        // A native adapter names its own link from the posting to the form.
        if(config.adapter!=='workday'&&!site?.open){
          const links=[...document.querySelectorAll('a,button,[role=button]')].filter(e=>visible(e)&&/^(?:apply(?: now| for .+| to .+)?|start (?:your )?application)[\s»›→]*$/i.test((e.innerText||e.getAttribute('aria-label')||'').trim()));
          if(links.length===1||links.length&&links[0].href&&new Set(links.map(e=>e.href||'')).size===1){links[0].click();return 'native';}
          return '';
        }
        for(let attempt=0;attempt<50&&live();attempt++){
          // 'ready': the form rendered after this section was scanned, so the engine scans it again.
          if(site?.open){const links=[...document.querySelectorAll(site.open)].filter(visible);if(links.length===1){links[0].click();return 'native';}if(document.querySelector('form'))return 'ready';}
          else for(const id of ['applyManually','continueButton','adventureButton'])if(this.openLink(id))return id;
          await new Promise(resolve=>native.setTimeout(resolve,100));
        }
        return '';
      },
      // Which Workday authentication form is shown, and which scanned controls receive the saved login.
      authPage(){
        if(!['workday','account'].includes(config.adapter))return {page:'',credentials:[]};
        const {emails,passwords,buttons}=authControls();
        return {...internAccount.inspect(),credentials:[...handles].filter(([,e])=>emails.includes(e)||passwords.includes(e)).map(([selector])=>selector),required_terms:[...handles].filter(([,e])=>e.type==='checkbox'&&(e.required||e.matches('[data-automation-id=createAccountCheckbox]'))).map(([selector])=>selector),marketing:[...handles].filter(([,e])=>e.type==='checkbox'&&!e.required&&e.parentElement.tagName!=='FORM'&&e.parentElement.textContent.length<600&&/marketing|newsletter|receive emails about job|job alerts|promotional/i.test(e.parentElement.textContent)).map(([selector])=>selector)};
      },
      async authenticate(credential,submit=true){
        if(!['workday','account'].includes(config.adapter)||!live())throw Error('Authentication not authorized');
        const {emails,passwords,buttons}=authControls();
        if(!['create','sign_in'].includes(internAccount.inspect().page)||!credential.username||!credential.password)throw Error('Ambiguous authentication');
        const auth=internAccount.inspect();
        if(auth.page==='create'&&(credential.password.length<auth.policy.minimum||credential.password.length>auth.policy.maximum))throw Error('Password length does not meet the form rules');
        if(auth.page==='create'&&(auth.policy.upper&&!/[A-Z]/.test(credential.password)||auth.policy.lower&&!/[a-z]/.test(credential.password)||auth.policy.digit&&!/\d/.test(credential.password)||auth.policy.symbol&&!/[^a-z\d]/i.test(credential.password)))throw Error('Password characters do not meet the form rules');
        if(emails.some(e=>e.value&&e.value!==credential.username)||passwords.some(e=>e.value&&e.value!==credential.password))throw Error('Existing authentication value conflicts with saved credentials');
        for(const [selector,element] of handles){
          if(emails.includes(element)||passwords.includes(element))continue;
          const p=policies.get(element);
          if(!p||p.value==null&&!p.omit)throw Error('Unapproved authentication question');
          if(p.omit){if(readable(element)!==''&&readable(element)!==false)throw Error('Existing omitted answer');continue;}
          assign(element,'value',p.value);
          element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));
          if(!matches(element,p)||element.validity&&!element.validity.valid)throw Error('Unverified authentication answer');
        }
        const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        for(const [element,value]of [...emails.map(e=>[e,credential.username]),...passwords.map(e=>[e,credential.password])]){setter.call(element,value);element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));if(element.validity&&!element.validity.valid)throw Error('Credential does not meet this form’s rules');}
        if(!submit)return;
        // SAP SuccessFactors keeps its required terms in a dialog, not a checkbox (seen on Halliburton): accept it as a required terms box is ticked.
        const terms=document.getElementById('dataPrivacyId'),accepted=document.getElementById('fbclc_dpcsId');
        if(auth.page==='create'&&terms&&visible(terms)&&accepted&&!accepted.value){
          terms.click();
          for(let attempt=0,clicked=false;attempt<100&&!accepted.value;attempt++){
            await new Promise(resolve=>native.setTimeout(resolve,100));
            if(!live())throw Error('Authentication stopped');
            const accept=[...document.querySelectorAll('button,[role=button]')].filter(e=>visible(e)&&/^accept$/i.test((e.innerText||'').trim()));
            if(!clicked&&accept.length===1){accept[0].click();clicked=true;}
          }
          if(!accepted.value)throw Error('Terms were not accepted');
        }
        const buttonId=buttons[0].getAttribute('data-automation-id');
        // Workday silently drops a sign-in submitted within 500ms of the form appearing (its spam-bot timer), and the bot may have just opened it.
        const earliest=performance.now()+1000;
        // Workday may enable or replace the submit control after processing input events.
        for(let attempt=0;attempt<60;attempt++){
          await new Promise(resolve=>native.setTimeout(resolve,50));
          if(!live())throw Error('Authentication stopped');
          const current=authControls();
          if(current.emails.length!==emails.length||current.passwords.length!==passwords.length||current.buttons.length!==1)continue;
          if(current.emails.some(e=>e.value!==credential.username)||current.passwords.some(e=>e.value!==credential.password))throw Error('Authentication values changed');
          let button=current.buttons[0];
          if(button.getAttribute('data-automation-id')!==buttonId)throw Error('Authentication form changed');
          if(button.getAttribute('aria-hidden')==='true'){
            const overlays=[...button.parentElement.querySelectorAll('[role=button]')].filter(e=>visible(e)&&/^(sign in|create account)$/.test(normalize(e.getAttribute('aria-label')||e.textContent)));
            if(overlays.length!==1)throw Error('Ambiguous authentication button');button=overlays[0];
          }
          if(performance.now()<earliest||!button.isConnected||!visible(button)||button.disabled||button.getAttribute('aria-disabled')==='true')continue;
          stop();button.click();return;
        }
        throw Error('Authentication button did not become ready');
      },
      async action(id, expectedFields, expectedSummary){
        const a=actions.get(id);
        if(!live()||!a||!a.element.isConnected||!visible(a.element)||a.element.disabled||!Array.isArray(expectedFields))throw Error('Expired action');
        const current=await scan();
        const keys=['key','label','kind','value','option','options','required','disabled','invalid','readonly','group','row','file_digest'];
        if(current.length!==expectedFields.length||current.some((f,i)=>keys.some(k=>JSON.stringify(f[k])!==JSON.stringify(expectedFields[i][k]))))throw Error('Form changed after verification');
        const snapshot=this.snapshot();
        if(!live()||snapshot.errors||snapshot.problems.length||JSON.stringify(snapshot.summary)!==JSON.stringify(expectedSummary))throw Error('Review changed after verification');
        if(a.method==='click'&&classify(a.element)!==a.kind)throw Error('Action changed after verification');
        const e=a.element,method=a.method;stop();e[method]();
      },
    };
  }
  chrome.runtime.onMessage.addListener((message,sender,respond)=>{
    if(sender.id!==chrome.runtime.id)return;
    (async()=>{try {
      if(message.command==='identify'){respond({matches:document.documentElement.dataset.internBotPage===message.nonce});return;}
      if(message.command==='detect') {
        // Registry construction only; no adapter starts and no profile is requested.
        const inert={environment:native,call:(o,k,a,opt)=>opt&&o?.[k]==null?undefined:o[k](...a),assign:(o,k,v)=>(o[k]=v),update:(o,k,op,rhs)=>o[k]??(o[k]=rhs())};
        const fits=a=>(!a.pattern||a.pattern.test(location.href))&&(!a.selector||document.querySelector(a.selector));
        let adapters=[...createSpeedyAdapters(inert),...nativeAdapters(inert)].filter(fits);
        if(!adapters.length)adapters=recipeAdapters(inert,message.recipes).filter(fits);
        adapters=adapters.map(a=>({id:a.id,name:a.name}));
        respond({adapters,account:internAccount.inspect(),document:message.document});return;
      }
      if(message.command==='prepare') {active?.R.stop();active=runtime(message.payload,message.token,message.document);}
      if(!active||active.token!==message.token||active.document!==message.document)throw Error('Stale document or run');
      let result={};
      if(message.command==='scan'||message.command==='prepare'){
        result.fields=await active.scan();
        // Workday keeps one URL and job-title heading across steps; only its active progress step tells them apart.
        result.section=[...document.querySelectorAll('h1,h2,[aria-current=step],[data-automation-id=pageHeader],[data-automation-id=progressBarActiveStep]')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()).join('|');
        // The site's own step list (Workday's progress bar, or any aria-current=step list) for the progress stepper.
        const step=document.querySelector('[data-automation-id=progressBarActiveStep],[aria-current=step]'),items=step?[...(step.closest('ol,ul')?.children||[step])]:[];
        result.steps=items.map(e=>e.textContent.replace(/^.*?step\s+\d+\s+of\s+\d+/i,'').trim());
        result.step=items.indexOf(step);
      }
      else if(message.command==='authorize')active.authorize(message.payload.policies);
      else if(message.command==='start')active.start();
      else if(message.command==='snapshot')result=active.snapshot();
      else if(message.command==='stop')active.R.stop();
      else if(message.command==='action')await active.action(message.payload.id,message.payload.fields,message.payload.summary);
      else if(message.command==='open_sign_in')result.opened=active.openLink('signInLink');
      else if(message.command==='open_create_account')result.opened=active.openLink('createAccountLink');
      else if(message.command==='open_application')result.opened=await active.openApplication();
      else if(message.command==='auth_page')result=active.authPage();
      else if(message.command==='options')result.options=await active.options(message.payload.selector,message.payload.query);
      else if(message.command==='choose')result.chosen=await active.choose();
      else if(message.command==='authenticate')await active.authenticate(message.payload.credential);
      else if(message.command==='validate_authentication')await active.authenticate(message.payload.credential,false);
      respond({...result,token:message.token,document:message.document});
    }catch {respond({error:'Local adapter command failed. Reopen or inspect the application.',token:message.token,document:message.document});}})();
    return true;
  });
})();
