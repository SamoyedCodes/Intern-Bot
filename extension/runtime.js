/* Adapter writes are proposals; only exact desktop-resolved facts may reach the DOM. */
(() => {
  const normalize = value => String(value ?? '').trim().replace(/[\s*:✱✳]+$/g, '').replace(/\s+/g, ' ').toLowerCase();
  const native = {MutationObserver};
  for (const name of ['setTimeout','clearTimeout','setInterval','clearInterval','requestAnimationFrame','cancelAnimationFrame']) native[name]=window[name].bind(window);
  let active;
  function runtime(config, token, documentId) {
    const timers = new Set(), intervals = new Set(), frames = new Set(), observers = new Set();
    const abort = new AbortController(), policies = new WeakMap(), proposals = new Map(), denied = new WeakSet(), files = new Map();
    const handles = new Map(), rowActions = new Set();
    const events = [], problems = new Map(), actions = new Map();
    const url = location.href;
    let running = true, status = 'prepared', lastChange = performance.now(), started = false, sequence = 0, picker;
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
    const readable = e => e instanceof HTMLSelectElement ? (e.value ? e.selectedOptions[0]?.textContent || '' : '') : ['checkbox','radio'].includes(e.type) ? e.checked : e.value ?? e.textContent;
    const matches = (e, p) => e.type === 'radio' ? e.checked === (normalize(e.labels?.[0]?.textContent || e.value) === normalize(p.value)) : e.type === 'checkbox' ? e.checked === p.value : normalize(readable(e)) === normalize(p.value);
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
      if (existing !== '' && existing !== false && !matches(e,p) && !p.replace) {
        report('conflict', 'Existing browser value conflicts with the profile. Resolve it before resuming.', p.key); denied.add(e); return value;
      }
      let desired = p.value;
      if (e instanceof HTMLSelectElement) {
        const options = [...e.options].filter(o=>normalize(o.textContent)===normalize(desired));
        if (options.length !== 1) {report('answer', 'The exact approved option is not offered by this form.',p.key);return value;}
        desired = options[0].value;key='value';
      } else if (e.type === 'radio') {desired = normalize(e.labels?.[0]?.textContent || e.value) === normalize(p.value);key='checked';}
      else if (e.type === 'checkbox') {if(typeof desired!=='boolean'){report('answer','Approve a Boolean answer for this checkbox.',p.key);return value;}key='checked';}
      const proto = e instanceof HTMLInputElement ? HTMLInputElement.prototype : e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : null;
      const setter = proto && Object.getOwnPropertyDescriptor(proto,key)?.set;
      if (setter) setter.call(e, desired); else e[key] = desired;
      denied.delete(e); lastChange = performance.now();
      return value;
    }
    function classify(e) {
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
        const p = picker && policies.get(picker);
        if(picker && !p){proposals.set(picker,{key:'option',value:e});return;}
        if(!p || normalize(e.innerText || e.textContent)!==normalize(p.value)){report('answer','Choose the exact approved dropdown option manually.',p?.key||'');return;}
      }
      if (e.matches?.('[role=combobox],[aria-haspopup=listbox]')) picker=e;
      const text=normalize(e.innerText || e.getAttribute?.('aria-label'));
      if (!e.matches?.('input,select,textarea,[role=option],option,[data-automation-id=promptOption],[data-automation-id=menuItem],[role=combobox],[aria-haspopup=listbox]') && !/^(add|add another|add education|add experience|add work experience|add language|add website|add employment|add row|search|browse|upload resume)$/.test(text)) {
        report('browser','An unrecognized adapter action needs manual review.');return;
      }
      e.click();
    }
    const R = {
      environment, stop, live,
      waitFor(predicate, root, options) {
        return new Promise(resolve=>{if(!live())return;if(predicate()){resolve(true);return;}const observer=new environment.MutationObserver(()=>{if(predicate()){observer.disconnect();resolve(true);}});observer.observe(root,options);});
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
          if(denied.has(e))return false;
          if(args[0].type==='submit'){action(e,'submit');return false;}
          if(['Enter',' '].includes(args[0].key)){report('browser','A keyboard activation needs manual review.');return false;}
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
    async function upload(file, e) {
      if(!e || !live())return false;
      const p=policies.get(e);
      if(!p){proposals.set(e,{key:'files',value:file});return false;}
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
        files.set(e,descriptor.digest);return true;
      }
      const receipt=e.closest('[data-automation-id=resumeUpload],[aria-labelledby="Resume/CV-section"]')?.querySelector('[data-automation-id=file-upload-item]');
      if(receipt){report('conflict','The existing uploaded document must be checked manually.',p.key);return false;}
      const transfer=new DataTransfer();transfer.items.add(chosen);e.files=transfer.files;files.set(e,descriptor.digest);
      e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));lastChange=performance.now();return true;
    }
    const hex = buffer => [...new Uint8Array(buffer)].map(b=>b.toString(16).padStart(2,'0')).join('');
    async function scan() {
      handles.clear();
      const formRoots=[...document.querySelectorAll('form')].filter(e=>visible(e)&&!e.parentElement.closest('form'));
      if(formRoots.length>1)report('browser','More than one form is present. Choose a single application form before autofilling.');
      const root=formRoots.length===1?formRoots[0]:document;
      if(formRoots.length>1){stop();return [];}
      const roots=[root];
      for(let i=0;i<roots.length;i++)for(const element of roots[i].querySelectorAll('*'))if(element.shadowRoot)roots.push(element.shadowRoot);
      const fields=roots.flatMap((root,index)=>scanInternFields(root).map(f=>{
        const element=root.querySelector(f.selector), selector=`control:${handles.size}`;
        handles.set(selector,element);f.selector=selector;
        if(index)f.key=`shadow:${root.host.id||index}:`+f.key;
        f.file_digest=files.get(element)||'';
        return f;
      }));
      for(const field of fields.filter(f=>f.kind==='file')){
        const e=handles.get(field.selector), selected=e.files?.[0];
        if(selected){
          const digest=hex(await crypto.subtle.digest('SHA-256',await selected.arrayBuffer()));
          field.file_digest=e.files.length===1?digest:'';
          const container=e.closest('[data-automation-id=resumeUpload],#s3_upload_for_resume,[data-upload]')||e.closest('label')||e.parentElement;
          const receipts=[...container.querySelectorAll('[data-automation-id=file-upload-successful],.file-upload-success,.filename,[role=status]')];
          const accepted=receipts.some(r=>visible(r)&&(r.getAttribute('data-automation-id')==='file-upload-successful'||r.classList.contains('filename')&&r.textContent.includes(selected.name)||r.textContent.includes(selected.name)&&/uploaded|attached|complete|success/i.test(r.textContent)));
          field.invalid=field.invalid||!accepted;
        }
      }
      return fields;
    }
    const observer=new native.MutationObserver(records=>{if(records.some(r=>r.type==='childList'||r.attributeName!=='data-intern-control'))lastChange=performance.now();});
    observer.observe(document,{subtree:true,childList:true,attributes:true,attributeFilter:['aria-invalid','disabled','hidden','aria-busy']});observers.add(observer);
    timers.add(native.setTimeout(()=>{if(live()){report('browser','The adapter reached its bounded wait limit. Inspect the form and resume.');stop();}},20000));
    window.addEventListener('unhandledrejection',fail,{signal:abort.signal});
    const authControls=()=>({
      emails:[...document.querySelectorAll('input[type=email],input[autocomplete=email],input[autocomplete=username],input[data-automation-id=email]')].filter(visible),
      passwords:[...document.querySelectorAll('input[type=password]')].filter(visible),
      buttons:[...document.querySelectorAll('[data-automation-id="signInSubmitButton"],[data-automation-id="createAccountSubmitButton"]')].filter(visible),
    });
    return {
      token,document:documentId,R,
      scan,
      authorize(policiesBySelector) {
        if(!live())return;
        for(const [selector,p]of Object.entries(policiesBySelector)) {const e=handles.get(selector);if(e)policies.set(e,p);}
        for(const [e,proposal]of proposals){if(!e.isConnected){proposals.delete(e);continue;}if(!policies.has(e))continue;proposals.delete(e);if(proposal.key==='option'){picker=e;action(proposal.value);continue;}assign(e,proposal.key,proposal.value);if(!denied.has(e)&&e.type!=='file'){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();}}
        for(const [selector,p]of Object.entries(policiesBySelector)){
          const e=handles.get(selector);
          if(e && (p.ref?.startsWith('answer:') || p.ref==='profile:cover_letter' || p.ref==='profile:cover_letter_path')){
            if(e.type==='file')void upload(null,e);
            else if(!matches(e,p)){assign(e,'value',p.value);if(!denied.has(e)){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();}}
          }
        }
        for(const e of rowActions)if(e.isConnected)action(e);
      },
      start() {
        if(started)throw Error('Adapter already started');started=true;status='in-progress';
        const adapter=createSpeedyAdapters(R).find(a=>a.id===config.adapter);
        if(!adapter)throw Error('Unknown adapter');
        const ctx={addEventListener:(target,...args)=>R.call(target,'addEventListener',args),onInvalidated:fn=>abort.signal.addEventListener('abort',fn,{once:true})};
        Promise.resolve(adapter.script({getProfile:async()=>config.profile,setMessage:message=>{if(live())status=message||status;},autofillSettings:{autoClickNextPage:true,autoSubmit:true,saveApplications:false,saveResponses:false},accountSettings:{accountEmail:"",accountPassword:""},ctx})).catch(fail);
      },
      snapshot(){return {summary:[...document.querySelectorAll('[data-automation-id="reviewField"],dl>dt')].filter(visible).map(e=>({
        label:(e.querySelector('label,dt')?.textContent||(e.tagName==='DT'?e.textContent:'')).trim(),
        value:(e.querySelector('dd,[data-value]')?.textContent||(e.tagName==='DT'?e.nextElementSibling?.textContent:'')||'').trim(),
        group:e.getAttribute('data-group')||'',row:Number(e.getAttribute('data-row')||0)
      })),errors:(/\bVPS\|[0-9a-f-]{36}\b/i.test(document.body.innerText)||/something went wrong[\s\S]*please refresh the page and then try again/i.test(document.body.innerText)?1:0)+[...document.querySelectorAll('[role=alert],.field-error-msg,.form-error,[data-automation-id=inputError]')].filter(e=>visible(e)&&e.textContent.trim()).length,status,live:live(),settled:performance.now()-lastChange>350&&timers.size<=1,proposals:proposals.size,events,problems:[...problems.values()],actions:[...actions].filter(([,a])=>a.element.isConnected&&visible(a.element)&&!a.element.disabled).map(([id,a])=>({id,kind:a.kind})),url};},
      openAuthLink(id){
        const links=[...document.querySelectorAll(`[data-automation-id="${id}"]`)].filter(visible);
        if(config.adapter!=='workday'||!live()||!['signInLink','createAccountLink'].includes(id)||links.length!==1)return false;
        links[0].click();return true;
      },
      // Which Workday authentication form is shown, and which scanned controls receive the saved login.
      authPage(){
        if(config.adapter!=='workday')return {page:'',credentials:[]};
        const {emails,passwords,buttons}=authControls();
        const page=buttons.length!==1?'':buttons[0].matches('[data-automation-id="createAccountSubmitButton"]')?'create':'sign_in';
        return {page,credentials:[...handles].filter(([,e])=>e===emails[0]||passwords.includes(e)).map(([selector])=>selector)};
      },
      authenticate(credential){
        if(config.adapter!=='workday'||!live())throw Error('Authentication not authorized');
        const {emails,passwords,buttons}=authControls();
        if(emails.length!==1||!passwords.length||buttons.length!==1||!credential.username||!credential.password)throw Error('Ambiguous authentication');
        if(emails[0].value&&emails[0].value!==credential.username||passwords.some(e=>e.value&&e.value!==credential.password))throw Error('Existing authentication value conflicts with saved credentials');
        for(const [selector,element] of handles){
          if(element===emails[0]||passwords.includes(element))continue;
          const p=policies.get(element);
          if(!p||p.value==null&&!p.omit)throw Error('Unapproved authentication question');
          if(p.omit){if(readable(element)!==''&&readable(element)!==false)throw Error('Existing omitted answer');continue;}
          assign(element,'value',p.value);
          element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));
          if(!matches(element,p)||element.validity&&!element.validity.valid)throw Error('Unverified authentication answer');
        }
        const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        for(const [element,value]of [[emails[0],credential.username],...passwords.map(e=>[e,credential.password])]){setter.call(element,value);element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));}
        let button=buttons[0];
        if(button.getAttribute('aria-hidden')==='true'){
          const overlays=[...button.parentElement.querySelectorAll('[role=button]')].filter(e=>visible(e)&&/^(sign in|create account)$/.test(normalize(e.getAttribute('aria-label')||e.textContent)));
          if(overlays.length!==1)throw Error('Ambiguous authentication button');button=overlays[0];
        }
        if(!live())return;
        stop();button.click();
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
      if(message.command==='detect') {
        // Registry construction only; no adapter starts and no profile is requested.
        const inert={environment:native,call:(o,k,a,opt)=>opt&&o?.[k]==null?undefined:o[k](...a),assign:(o,k,v)=>(o[k]=v),update:(o,k,op,rhs)=>o[k]??(o[k]=rhs())};
        const adapters=createSpeedyAdapters(inert).filter(a=>(!a.pattern||a.pattern.test(location.href))&&(!a.selector||document.querySelector(a.selector))).map(a=>({id:a.id,name:a.name}));
        respond({adapters,document:message.document});return;
      }
      if(message.command==='prepare') {active?.R.stop();active=runtime(message.payload,message.token,message.document);}
      if(!active||active.token!==message.token||active.document!==message.document)throw Error('Stale document or run');
      let result={};
      if(message.command==='scan'||message.command==='prepare'){
        result.fields=await active.scan();
        result.section=[...document.querySelectorAll('h1,h2,[aria-current=step],[data-automation-id=pageHeader]')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()).join('|');
      }
      else if(message.command==='authorize')active.authorize(message.payload.policies);
      else if(message.command==='start')active.start();
      else if(message.command==='snapshot')result=active.snapshot();
      else if(message.command==='stop')active.R.stop();
      else if(message.command==='action')await active.action(message.payload.id,message.payload.fields,message.payload.summary);
      else if(message.command==='open_sign_in')result.opened=active.openAuthLink('signInLink');
      else if(message.command==='open_create_account')result.opened=active.openAuthLink('createAccountLink');
      else if(message.command==='auth_page')result=active.authPage();
      else if(message.command==='authenticate')active.authenticate(message.payload.credential);
      respond({...result,token:message.token,document:message.document});
    }catch {respond({error:'Local adapter command failed. Reopen or inspect the application.',token:message.token,document:message.document});}})();
    return true;
  });
})();
