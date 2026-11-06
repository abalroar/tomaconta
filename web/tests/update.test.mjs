import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {mergeImob} from '../src/update.js';

const load=async file=>JSON.parse(await readFile(new URL('../public/data/'+file,import.meta.url),'utf8'));
const base=await load('imob-br.json'),specs=await load('imob-catalog.json');
// Reconstitui a resposta oficial na unidade original, usando o bundle real.
const rows=base.flatMap(c=>{const s=specs.find(s=>s.id===c.id);return s.historical?[]:c.series.flatMap(series=>series.data
 .filter(([date,value])=>date>='2025-09-01'&&date<='2026-08-31'&&value!=null)
 .map(([Data,value])=>({Data,Info:s.prefix+series.category+'_br',Valor:value/s.scale})));});
const clone=value=>structuredClone(value);
const allPoints=c=>c.series.flatMap(s=>s.data);

test('real baseline covers24 approved charts and22activecharts; propertycalendarendsJuly',()=>{
 assert.equal(base.length,24);assert.equal(new Set(base.map(c=>c.id)).size,24);
 assert.equal(specs.filter(s=>!s.historical).length,22);
 assert.ok(!base.some(c=>/bndu/i.test(c.id+' '+c.title)));
 const result=mergeImob(base,specs,rows,'BR');
 for(const c of result.filter(c=>!c.historical))assert.ok(allPoints(c).length);
 assert.equal(result.find(c=>c.id==='contratacao_valor_pf').latestPeriod,'2026-08');
 assert.equal(result.find(c=>c.id==='imoveis_tipo').latestPeriod,'2026-07');
});

test('monthly fullreplacement captures retracted observation and wholemissingmonth',()=>{
 const spec=specs.find(s=>s.id==='contratacao_valor_pf');
 const info=spec.prefix+'sfh_br';
 const fresh=rows.filter(r=>!(r.Info===info&&r.Data==='2026-06-30')&&!(r.Info.startsWith(spec.prefix)&&r.Data==='2026-05-31'));
 const result=mergeImob(base,specs,fresh,'br').find(c=>c.id===spec.id);
 assert.ok(!result.series.find(s=>s.category==='sfh').data.some(p=>p[0]==='2026-06-30'));
 assert.ok(!allPoints(result).some(p=>p[0]==='2026-05-31'));
 assert.ok(base.find(c=>c.id===spec.id).series.find(s=>s.category==='sfh').data.some(p=>p[0]==='2026-06-30'));
});

test('history outsidequerywindow and closedriskremain unchanged; operationdoesnotmutateinputs',()=>{
 const original=clone(base);const result=mergeImob(base,specs,rows,'br');
 assert.deepEqual(base,original);
 for(let i=0;i<base.length;i++){
  if(base[i].historical){assert.deepEqual(result[i],base[i]);assert.ok(allPoints(result[i]).every(p=>p[0]<='2024-12-31'));}
  else for(const series of base[i].series){const before=series.data.filter(p=>p[0]<'2025-09-01');assert.deepEqual(result[i].series.find(s=>s.category===series.category).data.filter(p=>p[0]<'2025-09-01'),before);}
 }
});

test('latermonthsoutsidewindowremain and rerunningisidempotent',()=>{
 const previous=clone(base);previous[0].series[0].data.push(['2026-09-30',12]);
 const once=mergeImob(previous,specs,rows,'br');assert.ok(once[0].series[0].data.some(p=>p[0]==='2026-09-30'&&p[1]===12));
 assert.deepEqual(mergeImob(once,specs,rows,'br'),once);
});

test('codescaseinsensitive and legitimatezeroaccepted withoutinventingzeros',()=>{
 const fresh=clone(rows);fresh[0].Info=fresh[0].Info.toUpperCase();fresh[0].Valor=0;
 const result=mergeImob(base,specs,fresh,'br');const s=specs.find(s=>fresh[0].Info.toLowerCase().startsWith(s.prefix));
 const c=result.find(c=>c.id===s.id);const category=fresh[0].Info.toLowerCase().slice(s.prefix.length,-3);
 assert.equal(c.series.find(s=>s.category===category).data.find(p=>p[0]===fresh[0].Data)[1],0);
});

test('duplicatecasefoldedInfoDateaborts',()=>{
 assert.throws(()=>mergeImob(base,specs,[...rows,{...rows[0],Info:rows[0].Info.toUpperCase()}],'br'),/duplicada/);
});

test('invaliddatecalendarandnonmonthendabort',()=>{
 for(const Data of ['2026-02-30','2026-02-20','2026-13-31','not-a-date',null]){
  const fresh=clone(rows);fresh[0].Data=Data;assert.throws(()=>mergeImob(base,specs,fresh,'br'),/Data|fechamento/);
 }
});

test('nullnegativeinfiniteemptyandbooleanvaluesabort',()=>{
 for(const Valor of [null,-1,Infinity,NaN,'',false]){const fresh=clone(rows);fresh[0].Valor=Valor;assert.throws(()=>mergeImob(base,specs,fresh,'br'),/Valor/);}
});

test('newcategorywithinapprovedprefixandotherUFabort',()=>{
 assert.throws(()=>mergeImob(base,specs,[...rows,{...rows[0],Info:specs[0].prefix+'novidade_br'}],'br'),/Categoria nova/);
 assert.throws(()=>mergeImob(base,specs,[...rows,{...rows[0],Info:rows[0].Info.replace(/_br$/,'_sp')}],'br'),/abrangência/);
});

test('BNDUoutsidescopeignored and cannotentercatalog',()=>{
 const clean=mergeImob(base,specs,rows,'br');
 assert.deepEqual(mergeImob(base,specs,[...rows,{Info:'contabil_bndu_br',Data:null,Valor:null}],'br'),clean);
 const bad=clone(specs);bad[0].title='BNDU';assert.throws(()=>mergeImob(base,bad,rows,'br'),/BNDU/);
 assert.throws(()=>mergeImob(base.slice(1),specs,rows,'br'),/24/);
});

test('missingactivechartcoverageaborts and cannotreplacepriorbase',()=>{
 const original=clone(base);const s=specs.find(s=>s.id==='contratacao_taxa_pf');
 assert.throws(()=>mergeImob(base,specs,rows.filter(r=>!r.Info.startsWith(s.prefix)),'br'),/Cobertura ativa incompleta/);
 assert.deepEqual(base,original);
 assert.throws(()=>mergeImob(base,specs,[],'br'),/sem observações/);
});

test('risksafterDecember2024requirecatalogreview',()=>{
 const s=specs.find(s=>s.id==='estoque_risco_pf');
 assert.throws(()=>mergeImob(base,specs,[...rows,{Info:s.prefix+'aa_br',Data:'2026-08-31',Valor:50}],'br'),/posterior/);
});

test('explicitquerywindowcaptureswholeinitialmonthretraction',()=>{
 const fresh=rows.filter(r=>r.Data.slice(0,7)!=='2025-09');
 const result=mergeImob(base,specs,fresh,'br',{start:'2025-09-01',end:'2026-08-31'});
 for(const c of result.filter(c=>!c.historical))assert.ok(!allPoints(c).some(p=>p[0].startsWith('2025-09')));
 assert.throws(()=>mergeImob(base,specs,rows,'br',{start:'2026-01-01',end:'2026-08-31'}),/fora da janela/);
});
