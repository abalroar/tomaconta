import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {currentDataRevision,pinDataRevision} from '../src/data.js';
import {SHARED_BASES,buildSharedPlan,newRequestKey,newerSharedPublication,pendingSharedJobs,publishedMonth,sharedJobOutcome,sharedJobState,sharedStatus,submitSharedPlan,suggestedSharedWindow} from '../src/shared-client.js';

const catalog=JSON.parse(await readFile(new URL('../public/data/institutions.json',import.meta.url),'utf8'));
const manifest=JSON.parse(await readFile(new URL('../public/data/manifest.json',import.meta.url),'utf8'));
const revision='a'.repeat(32),next='b'.repeat(32),key='c'.repeat(32);
const publication={revision,publishedAt:'2026-11-07T04:00:00Z',configured:true,builtIn:false};
const job={id:'d'.repeat(32),kind:'mercado_imobiliario',params:{kind:'mercado_imobiliario',mode:'incremental'},status:'queued',progress:0,createdAt:'2026-11-07T04:01:00Z',updatedAt:'2026-11-07T04:01:00Z',message:'Aguardando executor',result:null};

test('the real catalog supplies its published financial reference and all eight public sources retain their own date contracts',()=>{
  assert.equal(SHARED_BASES.length,8);
  assert.equal(publishedMonth(catalog),'2026-06');
  assert.deepEqual(buildSharedPlan({kind:'financeiro',period:publishedMonth(catalog)}),{kind:'financeiro',mode:'incremental',period:'2026-06'});
  assert.deepEqual(buildSharedPlan({kind:'individual',period:'2026-09'}),{kind:'individual',mode:'incremental',period:'2026-09'});
  assert.throws(()=>buildSharedPlan({kind:'individual',period:'2026-08'}),/fim de trimestre/);
  assert.deepEqual(buildSharedPlan({kind:'mercado_imobiliario'}),{kind:'mercado_imobiliario',mode:'incremental'});
  assert.deepEqual(suggestedSharedWindow('mercado_imobiliario',manifest),{start:'2025-09',end:'2026-08'});
  assert.deepEqual(buildSharedPlan({kind:'mercado_imobiliario',interval:true,start:'2025-09',end:'2026-08'}),{kind:'mercado_imobiliario',mode:'incremental',start:'2025-09',end:'2026-08'});
  assert.throws(()=>buildSharedPlan({kind:'scr_data',interval:true,start:'2024-01',end:'2026-06'}),/24 meses/);
  assert.deepEqual(buildSharedPlan({kind:'rede_agencias',period:'2026-06',interval:true,start:'2026-01',end:'2026-06'}),{kind:'rede_agencias',mode:'incremental'});
  assert.match(newRequestKey(),/^[a-f0-9]{32}$/);
});

test('status reads raw metadata and queue without changing the active data generation',async()=>{
  pinDataRevision(revision);
  const paths=[];
  const result=await sharedStatus({fetchImpl:async(path,options)=>{
    paths.push(path);assert.equal(options.method,'GET');assert.equal(options.cache,'no-store');
    return Response.json(path.endsWith('/current')?{...publication,revision:next}:{jobs:[job]});
  }});
  assert.deepEqual(paths,['/api/shared/current','/api/shared/jobs']);
  assert.equal(result.current.revision,next);
  assert.equal(currentDataRevision(),revision);
  assert.equal(newerSharedPublication(publication,result.current,result.jobs),true);
  assert.equal(pendingSharedJobs(result.jobs),true);
  pinDataRevision(null);
});

test('development skips unavailable queue while bootstrap remains observable and cannot appear published',async()=>{
  let calls=0;
  const result=await sharedStatus({fetchImpl:async()=>{calls++;return Response.json({revision:null,builtIn:true,configured:false});}});
  assert.equal(calls,1);assert.deepEqual(result.jobs,[]);
  const bootstrap=await sharedStatus({fetchImpl:async path=>Response.json(path.endsWith('/current')?{revision:null,builtIn:true,configured:true}:{jobs:[{...job,kind:'bootstrap'}]})});
  assert.equal(bootstrap.current.builtIn,true);
  assert.equal(sharedJobState(bootstrap.jobs[0]),'Na fila');
  assert.equal(newerSharedPublication({revision:null},bootstrap.current,bootstrap.jobs),false);
});

test('a submitted request uses exactly one POST, retains the caller key and reports queue acceptance as pending',async()=>{
  const plan=buildSharedPlan({kind:'mercado_imobiliario'}),calls=[];
  const result=await submitSharedPlan(plan,key,{fetchImpl:async(path,options)=>{
    calls.push({path,options});return Response.json({job},{status:201});
  }});
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/shared/jobs');assert.equal(calls[0].options.method,'POST');
  assert.equal(calls[0].options.headers['Idempotency-Key'],key);
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.deepEqual(JSON.parse(calls[0].options.body),plan);
  assert.equal(sharedJobState(result),'Na fila');assert.equal(sharedJobOutcome(result),'Aguardando início.');
  assert.equal(newerSharedPublication(publication,publication,[result]),false);
});

test('financial default requests discover current publications while an explicit competence is sent only when selected',async()=>{
  const requests=[];
  const fetchImpl=async(path,options)=>{requests.push(JSON.parse(options.body));return Response.json({job});};
  for(const kind of ['financeiro','individual','tudo']){
    await submitSharedPlan(buildSharedPlan({kind,period:''}),key,{fetchImpl});
  }
  assert.deepEqual(requests,[
    {kind:'financeiro',mode:'incremental'},
    {kind:'individual',mode:'incremental'},
    {kind:'tudo',mode:'incremental'},
  ]);
  const selected=publishedMonth(catalog);
  await submitSharedPlan(buildSharedPlan({kind:'financeiro',period:selected}),key,{fetchImpl});
  assert.deepEqual(requests.at(-1),{kind:'financeiro',mode:'incremental',period:'2026-06'});
  await submitSharedPlan(buildSharedPlan({kind:'financeiro',period:''}),key,{fetchImpl});
  assert.equal('period' in requests.at(-1),false);
});

test('an uncertain POST is not retried automatically and an explicit retry can reuse its idempotency key',async()=>{
  let attempts=0;const received=[];
  const fetchImpl=async(path,options)=>{attempts++;received.push(options.headers['Idempotency-Key']);if(attempts===1)throw Error('connection closed');return Response.json({job});};
  await assert.rejects(submitSharedPlan(job.params,key,{fetchImpl}),/pedido não foi confirmado/);
  assert.equal(attempts,1);
  await submitSharedPlan(job.params,key,{fetchImpl});
  assert.deepEqual(received,[key,key]);
});

test('failures preserve the current publication and historical successful jobs do not trigger a stale reload prompt',async()=>{
  for(const status of ['failed','needs_review']){
    const failed={...job,status,progress:.43,error:'Fonte indisponível'};
    assert.match(sharedJobOutcome(failed),/preservad/);
    assert.equal(newerSharedPublication(publication,publication,[failed]),false);
  }
  const old={...job,status:'succeeded',result:{revision:next},updatedAt:'2026-11-06T23:00:00Z'};
  assert.equal(newerSharedPublication(publication,publication,[old]),false);
  const published={...old,updatedAt:'2026-11-07T04:02:00Z'};
  assert.equal(newerSharedPublication(publication,publication,[published]),true);
  const fetchImpl=async()=>Response.json({error:'Há atualização recente.'},{status:429});
  await assert.rejects(submitSharedPlan(job.params,key,{fetchImpl}),error=>error.status===429&&error.detail.includes('HTTP 429'));
});
