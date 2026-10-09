import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {parse} from 'acorn';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const generated=path.join(root,'generated');

test('pinned extraction is deterministic and retains all 28 actual entry points',()=>{
 const before=fs.readFileSync(path.join(generated,'adapters.js'),'utf8');
 const build=spawnSync(process.execPath,[path.join(root,'tools/build.mjs')],{encoding:'utf8'});
 assert.equal(build.status,0,build.stderr);
 assert.equal(fs.readFileSync(path.join(generated,'adapters.js'),'utf8'),before);
 const registry=JSON.parse(fs.readFileSync(path.join(generated,'registry.json')));
 assert.equal(registry.length,28);
 assert.equal(new Set(registry.map(r=>r.symbol)).size,28);
 for(const adapter of registry)assert.ok(before.includes(`function ${adapter.symbol}(`));
 assert.equal(registry.find(a=>a.id==='phenom').selector,'head[data-ph-id]');
 parse(before,{ecmaVersion:'latest'});
 for(const forbidden of ['supabase','speedyapply.com','fetch(','XMLHttpRequest','WebSocket','chrome.','browser.'])assert.ok(!before.includes(forbidden),forbidden);
});

test('a different supplied XPI fails before emitting any adapter bundle',()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'intern-bot-invalid-xpi-'));
 try{
  fs.writeFileSync(path.join(directory,'original.xpi'),'different version');
  const result=spawnSync(process.execPath,[path.join(root,'tools/build.mjs'),directory],{encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Unsupported SpeedyApply XPI/);
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
});

test('MV3 runtime has no external account, cloud startup or externally connectable API',()=>{
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));
 assert.equal(manifest.manifest_version,3);
 assert.ok(!manifest.externally_connectable);
 assert.ok(!manifest.web_accessible_resources);
 assert.match(manifest.content_security_policy.extension_pages,/connect-src 'none'/);
 assert.equal(manifest.content_scripts[0].all_frames,true);
 for(const file of ['runtime.js','background.js','wake.js']){
  const source=fs.readFileSync(path.join(root,file),'utf8');
  assert.doesNotMatch(source,/fetch\(|XMLHttpRequest|WebSocket|https:\/\/.*speedyapply/);
  parse(source,{ecmaVersion:'latest'});
 }
});
