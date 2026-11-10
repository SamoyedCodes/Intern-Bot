/* Account discovery is independent of application adapters and never returns credential values. */
(() => {
  const visible=e=>!!e?.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
  const text=e=>([...(e?.labels||[])].map(l=>l.textContent).join(' ')+' '+(e?.getAttribute('aria-label')||'')+' '+(e?.placeholder||'')+' '+(e?.name||'')+' '+(e?.id||'')).trim();
  const caption=e=>(e.innerText||e.value||e.getAttribute('aria-label')||'').trim();
  function controls(){
    const passwords=[...document.querySelectorAll('input[type=password]')].filter(visible);
    const roots=[...new Set(passwords.map(e=>e.closest('form')||document))];
    const root=roots.length===1?roots[0]:document;
    const inputs=[...root.querySelectorAll('input')].filter(visible);
    const emails=inputs.filter(e=>e.type==='email'||['email','username'].includes(e.autocomplete)||e.matches('[data-automation-id=email]')||e.type==='text'&&/e.?mail|username|user.?id/i.test(text(e)));
    let buttons=[...root.querySelectorAll('button,input[type=submit],[role=button]')].filter(visible).filter(e=>
      e.matches('[data-automation-id=signInSubmitButton],[data-automation-id=createAccountSubmitButton]')||
      /^(sign in|log in|login|create (an? )?(account|profile)|register|sign up|signup)$/i.test(caption(e)));
    const workday=buttons.filter(e=>e.matches('[data-automation-id=signInSubmitButton],[data-automation-id=createAccountSubmitButton]'));
    if(workday.length)buttons=workday;
    else if(buttons.length>1){
      const submits=buttons.filter(e=>e.type==='submit'&&e.form===root);
      if(submits.length===1)buttons=submits;
    }
    return {root,emails,passwords,buttons,ambiguous:roots.length>1};
  }
  function inspect(){
    if(/^Loading https?:\/\//i.test(document.title))return {page:'loading',signed_in:false,form_error:false};
    const {root,emails,passwords,buttons,ambiguous}=controls();
    const body=document.body?.innerText||'';
    const alerts=[...document.querySelectorAll('[role=alert],.field-error-msg,.form-error,[data-automation-id=inputError],[data-automation-id=inputAlert]')].filter(visible);
    const error=alerts.some(e=>e.textContent.trim()&&!/password must|password requirements/i.test(e.textContent))||/account already exists|email (?:address )?(?:is )?already (?:registered|in use)|incorrect (?:email|password)|invalid (?:login|credentials)/i.test(body);
    const signed_in=[...document.querySelectorAll('a,button,[role=button]')].some(e=>visible(e)&&/^(sign out|log out|logout)$/i.test(caption(e)));
    const captchaSolved=[...document.querySelectorAll('[name=g-recaptcha-response],[name=h-captcha-response],[name=cf-turnstile-response]')].some(e=>!!e.value.trim());
    const captcha=!captchaSolved&&[...document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]')].some(e=>visible(e)&&!/[?&]size=invisible/.test(e.src));
    const challenge=captcha||[...document.querySelectorAll('input[autocomplete=one-time-code],input[name*=otp i]')].some(visible);
    if(challenge)return {page:'challenge',signed_in:false,form_error:error};
    if(!passwords.length){
      if([...document.querySelectorAll('button,a')].filter(e=>visible(e)&&/^sign in with email$/i.test(caption(e))).length===1)return {page:'email_choice',signed_in:false,form_error:error};
      if(/(?:check|sent|send|verify|confirm|activate)[\s\S]{0,100}(?:verification|activation|verify your|confirm your|email address)|(?:verification|activation) (?:email|code)|verify your (?:email|account)/i.test(body))
        return {page:'verification',signed_in:false,form_error:error};
      if(/account (?:has been |was |is )?(?:successfully )?created|registration (?:is )?(?:successful|complete)/i.test(body))
        return {page:'created',signed_in,form_error:error};
      return {page:'',signed_in,form_error:error};
    }
    if(ambiguous||!emails.length||buttons.length!==1)return {page:'ambiguous',signed_in:false,form_error:error};
    const create=passwords.length>1||/create|register|sign ?up/i.test(caption(buttons[0]))||buttons[0].matches('[data-automation-id=createAccountSubmitButton]');
    if(!create&&(passwords.length!==1||emails.length!==1))return {page:'ambiguous',signed_in:false,form_error:error};
    if(create&&emails.length>1&&emails.slice(1).some(e=>!/confirm|retype|repeat|again|verify/i.test(text(e))))return {page:'ambiguous',signed_in:false,form_error:error};
    const container=root===document?document.body:root;
    const rules=(container.innerText+' '+container.textContent).replace(/\s+/g,' ');
    const minimum=Math.max(...passwords.map(e=>e.minLength>0?e.minLength:0),Number(rules.match(/(?:at least|minimum(?: of)?|between)\s*(\d+)\s*(?:and|characters)/i)?.[1]||0));
    const maxima=[...passwords.map(e=>e.maxLength>0?e.maxLength:64),Number(rules.match(/(?:no (?:longer|more) than|not (?:be )?longer than|maximum(?: length)?(?: of)?|at most)\s*(\d+)\s*characters/i)?.[1]||64)];
    return {page:create?'create':'sign_in',signed_in,form_error:error,action:buttons[0].form?.action||'',policy:{minimum,maximum:Math.min(...maxima),symbols:!/no (?:special characters|symbols)|only (?:letters|alphanumeric)/i.test(rules),upper:/upper[ -]?case/i.test(rules),lower:/lower[ -]?case/i.test(rules),digit:/at least (?:one|1) (?:number|digit)/i.test(rules)&&!/(?:number|digit) or/i.test(rules),symbol:/at least (?:one|1) (?:special|symbol|punctuation)/i.test(rules)}};
  }
  function open(kind){
    const names=kind==='create'?/^(create (an? )?(account|profile)|register|sign up|signup)$/i:/^(sign in(?: with email)?|log in|login|please sign in)$/i;
    const links=[...document.querySelectorAll('a,button,[role=button]')].filter(e=>visible(e)&&names.test(caption(e))&&!e.matches('[data-automation-id=signInSubmitButton],[data-automation-id=createAccountSubmitButton]'));
    if(links.length!==1)return false;
    links[0].click();return true;
  }
  globalThis.internAccount={controls,inspect,open};
})();
