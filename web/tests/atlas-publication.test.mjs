import test from 'node:test';
import assert from 'node:assert/strict';
import {pinDataRevision,currentDataRevision} from '../src/data.js';
import {loadAtlasAsset} from '../src/atlas-publication.js';

const revision='a'.repeat(32),source={dims:{person:'PJ'},rows:[[0,0,0,0,0,1]]};
test('a legacy revision missing Atlas uses an identified built-in series without changing the financial pin',async()=>{
  pinDataRevision(revision);const calls=[];
  const packet=await loadAtlasAsset('atlas-pj.json',{fetchImpl:async url=>{calls.push(url);return calls.length===1?new Response('',{status:404}):Response.json(source);}});
  assert.deepEqual(calls,[`/api/shared/data/${revision}/atlas-pj.json`,'/data/atlas-pj.json']);
  assert.equal(packet.builtIn,true);assert.equal(packet.revision,null);assert.equal(currentDataRevision(),revision);
});
test('an updated revision uses its own Atlas bytes and never falls back on transport or integrity failures',async()=>{
  pinDataRevision(revision);let calls=0;
  const packet=await loadAtlasAsset('atlas-pj.json',{fetchImpl:async()=>{calls++;return Response.json(source,{headers:{'X-TomaConta-Revision':revision}});}});
  assert.equal(packet.builtIn,false);assert.equal(packet.revision,revision);assert.equal(calls,1);
  calls=0;await assert.rejects(()=>loadAtlasAsset('atlas-pj.json',{fetchImpl:async()=>{calls++;return new Response('',{status:503});}}),/503/);assert.equal(calls,1);
  await assert.rejects(()=>loadAtlasAsset('atlas-pj.json',{fetchImpl:async()=>Response.json(source,{headers:{'X-TomaConta-Revision':'b'.repeat(32)}})}),/outra revisão/);
  assert.equal(currentDataRevision(),revision);
});
test('client identity cannot be substituted during loading',async()=>{
  pinDataRevision(null);
  await assert.rejects(()=>loadAtlasAsset('atlas-pf.json',{fetchImpl:async()=>Response.json(source)}),/incompleta/);
  await assert.rejects(()=>loadAtlasAsset('../other.json'),/desconhecida/);
});
