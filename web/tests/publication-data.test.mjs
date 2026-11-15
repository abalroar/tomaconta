import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {BASE,json,datasetUrl,datasetRoot,currentDataRevision,pinDataRevision,validateDatasetRoot} from '../src/data.js';
import {loadPublication} from '../src/publication-data.js';
import {statementAssetUrl} from '../src/statements-worker.js';

const a='a'.repeat(32),b='b'.repeat(32);
const publication=revision=>({revision,publishedAt:revision?'2026-11-07T06:00:00Z':null,summary:{observed:0,missing:null},builtIn:revision===null,configured:true});
const restore=t=>{t.after(()=>pinDataRevision(null));};

test('dataset URLs keep canonical source paths and choose exactly the static or pinned revision root',t=>{
  restore(t);pinDataRevision(null);
  assert.equal(currentDataRevision(),null);
  assert.equal(datasetRoot(),BASE+'data/');
  assert.equal(datasetUrl('data/institutions.json'),BASE+'data/institutions.json');
  pinDataRevision(a);
  assert.equal(datasetRoot(),BASE+`api/shared/data/${a}/`);
  for(const path of ['institutions.json','bank-network-ufs.geojson','statements/index.json','statements/engine/bridge.py','statements/inputs/individual-60701190.json.gz']){
    assert.equal(datasetUrl('data/'+path),BASE+`api/shared/data/${a}/`+path);
  }
  for(const id of [0,'',undefined,'A'.repeat(32),'../'+a])assert.throws(()=>pinDataRevision(id),/revisão/);
  assert.equal(currentDataRevision(),a);
  for(const path of ['manifest.json','https://example.com/data/a.json','data/../a.json','data/a.json?url=x','data//a.json','data/%2e%2e/a.json'])assert.throws(()=>datasetUrl(path),/endereço/);
});

test('publication is fetched without cache and pinned before the resolved result is consumed',async t=>{
  restore(t);pinDataRevision(null);
  const value=await loadPublication({fetchImpl:async(url,options)=>{
    assert.equal(url,BASE+'api/shared/current');
    assert.equal(options.cache,'no-store');
    assert.equal(options.credentials,'same-origin');
    assert.ok(options.signal instanceof AbortSignal);
    return Response.json(publication(a));
  }});
  assert.equal(value.revision,a);
  assert.equal(currentDataRevision(),a);
  assert.deepEqual(value.summary,{observed:0,missing:null});
});

test('explicit built-in publications and 404 select static data without accepting zero as null',async t=>{
  restore(t);pinDataRevision(a);
  const builtIn=await loadPublication({fetchImpl:async()=>Response.json(publication(null))});
  assert.equal(builtIn.configured,true);assert.equal(currentDataRevision(),null);
  pinDataRevision(a);
  const unavailable=await loadPublication({fetchImpl:async()=>new Response('',{status:404})});
  assert.deepEqual(unavailable,{revision:null,publishedAt:null,summary:null,builtIn:true,configured:false});
  assert.equal(currentDataRevision(),null);
  await assert.rejects(loadPublication({fetchImpl:async()=>Response.json({...publication(null),revision:0})}),/inválida/);
});

test('503, malformed JSON and inconsistent revision metadata remain visible failures and retain the previous pin',async t=>{
  restore(t);pinDataRevision(a);
  const responses=[()=>new Response('offline',{status:503}),()=>new Response('<html>error</html>'),()=>Response.json({...publication(b),revision:'invalid'}),()=>Response.json({...publication(b),builtIn:true}),()=>Response.json({...publication(b),configured:false})];
  for(const response of responses){await assert.rejects(loadPublication({fetchImpl:async()=>response()}));assert.equal(currentDataRevision(),a);}
  await assert.rejects(loadPublication({timeoutMs:5,fetchImpl:async(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}))}),/demorou/);
  assert.equal(currentDataRevision(),a);
});

test('a superseded publication lookup cannot overwrite the newer immutable revision',async t=>{
  restore(t);let finish;
  const first=loadPublication({fetchImpl:()=>new Promise(resolve=>{finish=resolve;})});
  const rejected=assert.rejects(first,/substituída/);
  await loadPublication({fetchImpl:async()=>Response.json(publication(b))});
  finish(Response.json(publication(a)));
  await rejected;
  assert.equal(currentDataRevision(),b);
});

test('aborted bootstrap and cancelled JSON parsing never change the pinned publication',async t=>{
  restore(t);pinDataRevision(a);
  const already=new AbortController();already.abort();let called=false;
  await assert.rejects(loadPublication({signal:already.signal,fetchImpl:async()=>{called=true;return Response.json(publication(b));}}),{name:'AbortError'});
  assert.equal(called,false);
  const controller=new AbortController();let finish;
  const pending=loadPublication({signal:controller.signal,fetchImpl:async()=>({ok:true,status:200,json:()=>new Promise(resolve=>{finish=resolve;})})});
  const rejected=assert.rejects(pending,{name:'AbortError'});
  await Promise.resolve();controller.abort();finish(publication(b));await rejected;
  const bodyAbort=new AbortController();
  await assert.rejects(loadPublication({signal:bodyAbort.signal,fetchImpl:async()=>({ok:true,status:200,json:async()=>{bodyAbort.abort();throw new DOMException('aborted','AbortError');}})}),{name:'AbortError'});
  assert.equal(currentDataRevision(),a);
});

test('JSON and gzip assets from one pinned root preserve numeric zero, null and exact source IDs',async t=>{
  restore(t);pinDataRevision(a);
  const packet={id:'individual-00360305',values:[0,null,-1],sourceSha256:'original-source'};
  const requests=[];
  t.mock.method(globalThis,'fetch',async url=>{
    requests.push(url);
    const source=JSON.stringify(packet);
    return new Response(url.endsWith('.gz')?gzipSync(source):source,{headers:{'X-TomaConta-Revision':a}});
  });
  assert.deepEqual(await json('data/institutions.json'),packet);
  assert.deepEqual(await json('data/statements/individual-00360305.json.gz'),packet);
  assert.deepEqual(await json('data/bank-network-ufs.geojson'),packet);
  assert.ok(requests.every(url=>url.startsWith(BASE+`api/shared/data/${a}/`)));
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify(packet),{headers:{'X-TomaConta-Revision':a}}));
  assert.deepEqual(await json('data/statements/individual-00360305.json.gz'),packet);
});

test('in-flight and conflicting revision responses cannot reach the application as fresh data',async t=>{
  restore(t);pinDataRevision(a);let finish;
  t.mock.method(globalThis,'fetch',()=>new Promise(resolve=>{finish=resolve;}));
  const pending=json('data/institutions.json'),rejected=assert.rejects(pending,/mudou/);
  pinDataRevision(b);finish(Response.json({zero:0,missing:null}));await rejected;
  t.mock.method(globalThis,'fetch',async()=>Response.json({value:1},{headers:{'X-TomaConta-Revision':a}}));
  await assert.rejects(json('data/institutions.json'),/outra revisão/);
});

test('worker asset URLs bind engine and canonical inputs to the same explicit same-origin revision',()=>{
  const root=`http://localhost/api/shared/data/${a}/`;
  assert.equal(statementAssetUrl(root,'data/statements/engine/manifest.json'),root+'statements/engine/manifest.json');
  const input='data/statements/inputs/individual-00360305.json.gz';
  assert.equal(statementAssetUrl(root,input),root+'statements/inputs/individual-00360305.json.gz');
  assert.equal(input,'data/statements/inputs/individual-00360305.json.gz');
  assert.equal(validateDatasetRoot('/data/'),'http://localhost/data/');
  for(const invalid of ['https://other.example/data/','http://localhost/other/data/',`http://localhost/api/shared/data/invalid/`,root+'?x=1','http://localhost/data/../data/','http://localhost/data%2f/'])assert.throws(()=>validateDatasetRoot(invalid),/Origem/);
});
