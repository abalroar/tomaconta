import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {
  LANDING_GROUPS,selectLandingCohort,groupName,groupColor,groupCode,
  creditTotalFromCharts,commonRoePeriods,buildRoeRace,
  normalizeInstitutionQuery,searchInstitutions,
} from '../src/landing-data.js';

const read=async name=>JSON.parse(await readFile(new URL('../public/data/'+name,import.meta.url),'utf8'));
const catalog=await read('institutions.json');
const cohort=selectLandingCohort(catalog);
const histories=await Promise.all(cohort.map(group=>read(group.historyPath.replace(/^data\//,''))));
const history=(id,values)=>({id,history:values.map(([period,roe])=>({period,values:{roe}}))});
const componentNames=['PJ livre','PF livre','PJ direcionado','PF direcionado'];
const stock=values=>[{id:'credito_estoque-1',unit:'R$ bi',source:'BCB · SGS',series:componentNames.map((name,index)=>({name,data:values[index]}))}];

test('real cohort is exactly the ten largest prudential groups in the common competence',()=>{
 assert.equal(cohort.length,10);assert.deepEqual(cohort.map(group=>group.id),LANDING_GROUPS.map(group=>group.id));
 assert.ok(cohort.every(group=>group.perimeter==='Prudencial'&&group.latestPeriod==='2026-Q2'));
 assert.equal(cohort[0].latest.assets,2846417632562.91);
 assert.equal(cohort.at(-1).name,'SAFRA - PRUDENCIAL');
 assert.ok(cohort.slice(1).every((group,index)=>group.latest.assets<=cohort[index].latest.assets));
});

test('asset selection excludes other perimeters, old observations and nulls, keeping zero',()=>{
 const make=(id,assets,extra={})=>({id,name:'Nome compartilhado',perimeter:'Prudencial',latestPeriod:'2026-Q2',latest:{assets},...extra});
 const data={latestPeriod:'2026-Q2',institutions:[make('individual',1e15,{perimeter:'Individual'}),make('old',1e14,{latestPeriod:'2025-Q4'}),make('missing',null),make('zero',0),make('b',10),make('a',10)]};
 const before=structuredClone(data);assert.deepEqual(selectLandingCohort(data).map(group=>group.id),['a','b','zero']);
 assert.deepEqual(data,before);assert.equal(selectLandingCohort(data,1)[0].id,'a');assert.deepEqual(selectLandingCohort(data,0),[]);
});

test('approved labels and stable colors retain exact group identity',()=>{
 assert.deepEqual(cohort.map(groupName),['Itaú','Banco do Brasil','Caixa','Bradesco','Santander','BNDES','BTG Pactual','Nu Pagamentos','XP','Safra']);
 assert.equal(groupColor(cohort[1]),'#aa8a22');assert.equal(groupColor(cohort[0]),'#ce623c');
 assert.equal(groupCode(cohort[0]),'C0080099');assert.equal(groupName({id:'60701190',name:'ITAÚ UNIBANCO S.A.',perimeter:'Individual'}),'ITAÚ UNIBANCO S.A.');
 assert.equal(groupCode({id:'60701190',name:'ITAÚ UNIBANCO S.A.'}),null);
 const outside={id:'73f0e1311a08e627',name:'BANCO AFINZ BM - PRUDENCIAL'};
 assert.equal(groupColor(outside),groupColor({...outside,latest:{assets:0}}));
});

test('real SFN total uses the four existing transformed components with their original unit',async()=>{
 const charts=await read('sfn.json'),original=structuredClone(charts);
 const total=creditTotalFromCharts(charts,{start:'2016-09',end:'2026-09'});
 assert.equal(total.series.length,1);assert.equal(total.unit,'R$ bi');assert.deepEqual(total.missingComponents,[]);
 assert.equal(total.series[0].data.length,121);assert.ok(total.series[0].data.every(point=>point[1]!=null));
 assert.equal(total.series[0].data[0][0],'2016-09-01');assert.equal(total.series[0].data.at(-1)[0],'2026-09-01');
 assert.ok(Math.abs(total.series[0].data.at(-1)[1]-7444.209)<1e-9);
 assert.deepEqual(charts,original);
});

test('credit gaps stay null while four legitimate zeros sum to zero',()=>{
 const charts=stock([
  [['2025-01-01',0],['2025-02-01',1],['2025-03-01',1]],
  [['2025-01-01',0],['2025-02-01',2],['2025-03-01',2]],
  [['2025-01-01',0],['2025-02-01',null],['2025-03-01',3]],
  [['2025-01-01',0],['2025-02-01',4]],
 ]);
 assert.deepEqual(creditTotalFromCharts(charts).series[0].data,[['2025-01-01',0],['2025-02-01',null],['2025-03-01',null]]);
 charts[0].series.pop();const missing=creditTotalFromCharts(charts);
 assert.deepEqual(missing.missingComponents,['PF direcionado']);assert.ok(missing.series[0].data.every(point=>point[1]===null));
 assert.equal(creditTotalFromCharts([]),null);
});

test('credit input refuses duplicated components or unexpected units',()=>{
 const charts=stock(componentNames.map(()=>[['2025-01-01',1]]));
 assert.throws(()=>creditTotalFromCharts([{...charts[0],series:[...charts[0].series,charts[0].series[0]]}]),/duplicado/);
 assert.throws(()=>creditTotalFromCharts([{...charts[0],unit:'%'}]),/Unidade/);
});

test('real race has 34 continuous quarters and keeps published ROE values unchanged',()=>{
 const before=structuredClone(histories),race=buildRoeRace(cohort,histories);
 assert.equal(race.periods.length,34);assert.equal(race.periods[0],'2018-Q1');assert.equal(race.periods.at(-1),'2026-Q2');
 assert.deepEqual(race.missingPeriods,[]);assert.equal(race.blocks.length,1);
 assert.equal(race.minRoe,-49.69018809);assert.equal(race.maxRoe,63.60265136);
 assert.equal(race.frames[0].values[0],16.95303684);
 assert.equal(race.frames.at(-1).ranking.find(row=>row.id===cohort[0].id).roe,20.66501736);
 for(const frame of race.frames){
  assert.equal(frame.values.length,10);assert.equal(frame.ranking.length,10);assert.equal(frame.leaderId,frame.ranking[0].id);
  assert.deepEqual(frame.ranking.map(row=>row.roe),frame.ranking.map(row=>row.roe).sort((a,b)=>b-a));
  cohort.forEach((group,index)=>assert.equal(frame.values[index],histories[index].history.find(row=>row.period===frame.period).values.roe));
 }
 const changes=race.frames.slice(1).filter((frame,index)=>frame.leaderId!==race.frames[index].leaderId);assert.equal(changes.length,8);
 assert.deepEqual(histories,before);
});

test('continuity crosses year boundaries and never bridges null or absent quarters',()=>{
 const a=history('a',[['2024-Q3',10],['2024-Q4',null],['2025-Q1',0],['2025-Q2',-5]]);
 const b=history('b',[['2024-Q3',20],['2024-Q4',25],['2025-Q1',30],['2025-Q2',35]]);
 assert.deepEqual(commonRoePeriods([a,b],{startPeriod:'2024-Q3'}),['2025-Q1','2025-Q2']);
 const race=buildRoeRace([{id:'a',name:'A'},{id:'b',name:'B'}],[a,b],{startPeriod:'2024-Q3'});
 assert.deepEqual(race.blocks,[['2024-Q3'],['2025-Q1','2025-Q2']]);assert.deepEqual(race.missingPeriods,['2024-Q4']);
 assert.deepEqual(race.frames.map(frame=>frame.values),[[0,30],[-5,35]]);
 b.history.splice(2,1);assert.deepEqual(commonRoePeriods([a,b],{startPeriod:'2024-Q3'}),['2025-Q2']);
 assert.deepEqual(commonRoePeriods([history('c',[['2024-Q4',5],['2025-Q1',6]])],{startPeriod:'2024-Q4'}),['2024-Q4','2025-Q1']);
});

test('race rejects mismatched or duplicate identities and does not merge identical names',()=>{
 assert.throws(()=>buildRoeRace([{id:'absent',name:'Mesmo nome'}],[history('another',[['2025-Q1',1]])]),/Histórico indisponível/);
 assert.throws(()=>commonRoePeriods([history('a',[]),history('a',[])]),/duplicada/);
 const groups=[{id:'a',name:'Mesmo nome',perimeter:'Prudencial'},{id:'b',name:'Mesmo nome',perimeter:'Individual'}];
 const race=buildRoeRace(groups,[history('a',[['2025-Q1',10]]),history('b',[['2025-Q1',20]])]);
 assert.deepEqual(race.frames[0].ranking.map(row=>[row.id,row.perimeter]),[['b','Individual'],['a','Prudencial']]);
});

test('whole-catalog search finds Afinz and Inter outside the landing cohort',()=>{
 for(const query of ['Afinz','Inter','Banco Inter']){
  const results=searchInstitutions(catalog,query);assert.ok(results.length);
  const expected=query==='Afinz'?'73f0e1311a08e627':'8debf22957381dff';const match=results.find(group=>group.id===expected);
  assert.ok(match);assert.ok(!cohort.some(group=>group.id===match.id));assert.equal(match.perimeter,'Prudencial');
  const original=catalog.institutions.find(group=>group.id===match.id);
  assert.equal(match.name,original.name);assert.equal(match.historyPath,original.historyPath);assert.deepEqual(match.latest,original.latest);
 }
});

test('search normalizes accents and identifiers without inferring CNPJ-based group codes',()=>{
 assert.equal(normalizeInstitutionQuery('  ITAÚ—UNIBANCO  '),'itau unibanco');
 assert.equal(searchInstitutions(catalog,'ITAÚ')[0].id,cohort[0].id);
 assert.equal(searchInstitutions(catalog,'Banco do Brasil')[0].id,cohort[1].id);
 assert.equal(searchInstitutions(catalog,'C0080099')[0].id,cohort[0].id);
 assert.equal(searchInstitutions(catalog,'73f0e1311a08e627')[0].name,'BANCO AFINZ BM - PRUDENCIAL');
 assert.deepEqual(searchInstitutions(catalog,'C60701190'),[]);assert.deepEqual(searchInstitutions(catalog,'   '),[]);
});

test('search retains explicit perimeter and distinct identities for similar legal names',()=>{
 const data={latestPeriod:'2026-Q2',institutions:[
  {id:'legal-one',name:'Instituição Exemplo',perimeter:'Prudencial',latestPeriod:'2026-Q2',latest:{assets:10},aliases:['Café'],identifiers:{code:'P-123'}},
  {id:'legal-two',name:'Instituição Exemplo',perimeter:'Individual',latestPeriod:'2026-Q2',latest:{assets:20},historyPath:'individual.json'},
 ]};
 assert.equal(searchInstitutions(data,'cafe')[0].id,'legal-one');assert.equal(searchInstitutions(data,'p123')[0].id,'legal-one');
 const result=searchInstitutions(data,'exemplo');assert.equal(result.length,2);assert.deepEqual(new Set(result.map(group=>group.perimeter)),new Set(['Prudencial','Individual']));
 assert.deepEqual(searchInstitutions(data,'exemplo',{perimeter:'Individual'}).map(group=>group.id),['legal-two']);
 assert.equal(searchInstitutions(data,'exemplo',{limit:1}).length,1);
});

test('search builds the normalized index once per immutable catalog object',()=>{
 let aliasReads=0;
 const group={id:'indexed-group',name:'Exemplo',perimeter:'Prudencial',latestPeriod:'2026-Q2',latest:{assets:10},get aliases(){aliasReads++;return ['Apelido'];}};
 const snapshot={latestPeriod:'2026-Q2',institutions:[group]};
 assert.deepEqual(searchInstitutions(snapshot,'inexistente'),[]);
 const firstBuildReads=aliasReads;assert.ok(firstBuildReads>0);
 assert.deepEqual(searchInstitutions(snapshot,'outro inexistente'),[]);assert.equal(aliasReads,firstBuildReads);
 const nextSnapshot={...snapshot};searchInstitutions(nextSnapshot,'inexistente');assert.ok(aliasReads>firstBuildReads);
});

test('new snapshots refresh search priority and returned objects stay independent',()=>{
 const institutions=[
  {id:'current',name:'Exemplo',perimeter:'Prudencial',latestPeriod:'2026-Q2',latest:{assets:10},historyPath:'a.json'},
  {id:'earlier',name:'Exemplo',perimeter:'Prudencial',latestPeriod:'2025-Q4',latest:{assets:20},historyPath:'b.json'},
 ];
 const snapshot={latestPeriod:'2026-Q2',institutions};const first=searchInstitutions(snapshot,'exemplo');
 assert.equal(first[0].id,'current');first[0].displayName='Alterado na cópia';first[0].name='Outro nome';
 const again=searchInstitutions(snapshot,'exemplo');assert.equal(again[0].displayName,'Exemplo');assert.equal(again[0].name,'Exemplo');
 assert.notEqual(again[0],first[0]);assert.equal(again[0].latest,institutions[0].latest);assert.equal(again[0].historyPath,'a.json');
 const nextSnapshot={...snapshot,latestPeriod:'2025-Q4'};assert.equal(searchInstitutions(nextSnapshot,'exemplo')[0].id,'earlier');
});
