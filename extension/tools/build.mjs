/** Extract the 28 adapter dependency closures from the pinned, user-supplied bundle. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {parse} from 'acorn';
import {analyze} from 'eslint-scope';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const vendor=process.argv[2] ? path.resolve(process.argv[2]) : path.join(root,'third_party/speedyapply/2.28.0');
const expected='f7202224224735d17c8bf9ed8d091034848c8614a6d99cf84c02021bb0692571';
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
if(hash(fs.readFileSync(path.join(vendor,'original.xpi')))!==expected) throw Error('Unsupported SpeedyApply XPI: expected 2.28.0 user-supplied package');
const source=fs.readFileSync(path.join(vendor,'content.js'),'utf8');
if(hash(source)!=='13699cc1248dbc11188eca258151524adda104fd9d04c7ea24c3fb7b7fb2eff4') throw Error('Adapter source hash mismatch');
const ast=parse(source,{ecmaVersion:'latest',ranges:true});
const scopes=analyze(ast,{ecmaVersion:2022,sourceType:'script',optimistic:true});
const body=ast.body[0].declarations[0].init.callee;
const scope=scopes.acquire(body);
const names=['Workday','Greenhouse','Lever','SAP SuccessFactors','iCIMS','Workable','Rippling','Breezy','JazzHR','Ashby','SmartRecruiters','Paylocity','Freshteam','Dover','Pinpoint','Comeet','Gusto','Polymer','ADP','Jobvite','UltiPro','Tesla','TikTok','Eightfold','SEEK','BambooHR','Phenom','Dayforce'];
const replacements={
 DI:'function DI(element, name, absent=false) { return R.waitFor(() => element.classList.contains(name) !== absent, element, {attributes:true}); }',
 _I:'function _I(element, count=1) { return R.waitFor(() => element.childElementCount >= count, element, {childList:true}); }',
 vI:'function vI(element, count=0) { return R.waitFor(() => element.childElementCount === count, element, {childList:true}); }',
 fI:'function fI(element) { return R.waitFor(() => !element.isConnected, document.body, {childList:true,subtree:true}); }',
 tz:`function tz(entries) { return entries.length ? entries.reduce((best,entry) => ({PhD:7,PharmD:6,MBA:5,\"Master's\":4,\"Bachelor's\":3,\"Bachelor of Arts\":3,\"Associate's\":2,GED:1}[entry.degree]||0)>({PhD:7,PharmD:6,MBA:5,\"Master's\":4,\"Bachelor's\":3,\"Bachelor of Arts\":3,\"Associate's\":2,GED:1}[best.degree]||0)?entry:best) : {school:"",degree:""}; }`,
 NI:'async function NI() {}',
 py:'async function py(data) { R.emit("submission_candidate", {title:data.jobTitle}); }',
 my:'function my(data) { R.emit("answer_candidates", {questions:data.map(x=>x.question)}); }',
 aL:'async function aL(questions) { return R.resolveQuestions(questions); }',
 yL:'function yL() {}',
 SI:'function SI(base64, name) { return R.file(base64, name); }',
 DV:'async function DV(file) { return R.upload(file, document.querySelector(`[data-automation-id=resumeUpload] input[type=file], [aria-labelledby=\"Resume/CV-section\"] input[type=file], [data-automation-id=quickApplyPage] input[type=file], [data-fkit-id=\"resumeAttachments--attachments\"] input[type=file]`)); }',
 CI:'function CI(file, selector, xpath=false, root=document) { return R.upload(file, xpath ? J(selector,root) : root.querySelector(selector)); }',
};
const declarations=new Map(scope.variables.filter(v=>v.defs.length).map(v=>[v.name,v.defs[0].node]));
const references=scopes.scopes.flatMap(s=>s.references).filter(r=>r.resolved?.scope===scope);
const selected=new Set();
function include(name){
 if(selected.has(name))return;
 const node=declarations.get(name);if(!node)throw Error('Missing dependency '+name);
 selected.add(name);
 if(replacements[name])return;
 for(const r of references)if(r.identifier.start>=node.start&&r.identifier.end<=node.end)include(r.resolved.name);
}
include('$V');
const mutations=new Set(), external=new Set();
function transform(node){
 function render(n){
  if(n.type==='CallExpression'&&n.callee.type==='MemberExpression'){
   const m=n.callee, method=m.computed?render(m.property):JSON.stringify(m.property.name);
   const name=m.property.name;
   const object=render(m.object), args=n.arguments.map(render).join(',');
   if(m.object.type==='Identifier'&&m.object.name==='window'&&['setTimeout','clearTimeout','setInterval','clearInterval','requestAnimationFrame','cancelAnimationFrame'].includes(name))
    return `(R.environment[${method}](${args}))`;
   // All member calls pass through one gate, including optional calls and native setter.call.
   mutations.add(name||'[computed]');
   return `(R.call(${object},${method},[${args}],${!!(n.optional||m.optional)}))`;
  }
  if(n.type==='AssignmentExpression'&&n.left.type==='MemberExpression'){
   const m=n.left;
   return n.operator==='=' ? `(R.assign(${render(m.object)},${m.computed?render(m.property):JSON.stringify(m.property.name)},${render(n.right)}))` : `(R.update(${render(m.object)},${m.computed?render(m.property):JSON.stringify(m.property.name)},${JSON.stringify(n.operator)},()=>(${render(n.right)})))`;
  }
  if((n.type==='UpdateExpression'||n.type==='UnaryExpression'&&n.operator==='delete')&&n.argument.type==='MemberExpression'){
   const m=n.argument;
   return `(R.mutate(${render(m.object)},${m.computed?render(m.property):JSON.stringify(m.property.name)},${JSON.stringify(n.operator)},${!!n.prefix}))`;
  }
  const children=Object.values(n).flatMap(v=>Array.isArray(v)?v:[v]).filter(v=>v&&typeof v==='object'&&v.type).sort((a,b)=>a.start-b.start);
  let out='',cursor=n.start;
  for(const c of children){if(c.start<cursor)continue;out+=source.slice(cursor,c.start)+render(c);cursor=c.end;}
  return out+source.slice(cursor,n.end);
 }
 return render(node);
}
const chunks=[];
for(const name of [...selected].sort((a,b)=>declarations.get(a).start-declarations.get(b).start)){
 const node=declarations.get(name);
 let adapted = replacements[name]||(node.type==='VariableDeclarator'?'var ':'')+transform(node)+';';
 if(name==='rI')adapted=adapted.replace('{','{if(!e)return \"\";');
 chunks.push(adapted);
}
for(const s of scopes.scopes)for(const r of s.through){if(!r.resolved&&[...selected].some(n=>{const d=declarations.get(n);return !replacements[n]&&r.identifier.start>=d.start&&r.identifier.end<=d.end}))external.add(r.identifier.name);}
const registry=declarations.get('$V').init;
if(registry.elements.length!==28)throw Error('Expected 28 adapters');
const records=registry.elements.map((e,i)=>({id:names[i].toLowerCase().replace(/[^a-z0-9]+/g,'-'),name:names[i],symbol:e.properties.find(p=>p.key.name==='script').value.name, ...Object.fromEntries(e.properties.filter(p=>p.key.name!=='script').map(p=>[p.key.name,p.key.name==='pattern'?p.value.arguments.map(a=>a.quasis[0].value.cooked):p.value.quasis[0].value.cooked]))}));
parse(chunks.join('\n'),{ecmaVersion:'latest'});
const header=`/* Derived from SpeedyApply 2.28.0, proprietary user-supplied code. See third_party/speedyapply/2.28.0/NOTICE.md. Generated by tools/build.mjs. */\n`;
const code=header+`globalThis.createSpeedyAdapters = function(R) {\nconst {MutationObserver,setTimeout,clearTimeout,setInterval,clearInterval,requestAnimationFrame,cancelAnimationFrame}=R.environment;\n`+chunks.join('\n')+`\nreturn $V.map((adapter,index)=>({...${JSON.stringify(records)}[index],...adapter}));\n};\n`;
// The extracted adapter graph must never carry extension/account/cloud/UI dependencies.
for(const token of ['chrome.','browser.','supabase','speedyapply.com','fetch(','XMLHttpRequest','WebSocket','React'])if(code.includes(token))throw Error('Unexpected runtime dependency: '+token);
fs.mkdirSync(path.join(root,'extension/generated'),{recursive:true});
fs.writeFileSync(path.join(root,'extension/generated/scan.js'),'globalThis.scanInternFields = '+fs.readFileSync(path.join(root,'core/automation/scan.js'),'utf8')+';\n');
fs.writeFileSync(path.join(root,'extension/generated/adapters.js'),code);
fs.writeFileSync(path.join(root,'extension/generated/registry.json'),JSON.stringify(records,null,2)+'\n');
fs.writeFileSync(path.join(root,'extension/generated/build-report.json'),JSON.stringify({sourceHash:hash(source),adapterCount:28,symbols:selected.size,bytes:code.length,external:[...external].sort(),mutations:[...mutations].sort()},null,2)+'\n');
console.log(`Extracted 28 adapters: ${selected.size} symbols, ${code.length} bytes`);
