import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {statementAnalysisBank,statementSelectionForBank,statementNavigationUrl} from '../src/statement-data.js';

const read=async path=>JSON.parse(await readFile(new URL(`../public/data/${path}`,import.meta.url),'utf8'));
const [catalog,index,crosswalk]=await Promise.all(['institutions.json','statements/index.json','statements/crosswalk.json'].map(read));
const bank=id=>catalog.institutions.find(entry=>entry.id===id);
const entity=id=>index.institutions.find(entry=>entry.id===id);
const itau=bank('5f6d3c0745685d8f'),afinz=bank('73f0e1311a08e627');
const statement=entity('prudential-C0083539');

test('Afinz exact reverse synchronizes global bank while retaining statements, two dates and analysis filters',()=>{
  const before=structuredClone({catalog:afinz,entity:statement});
  assert.equal(statementAnalysisBank(catalog,crosswalk,statement),afinz);
  const periods=['202512','202606'];
  const url=statementNavigationUrl(`https://example.com/tomaconta/?view=institutions&bank=${itau.id}&panel=statements&period=2025-Q4&history=all`,afinz,statement,periods);
  assert.equal(url.searchParams.get('bank'),afinz.id);
  assert.equal(url.searchParams.get('panel'),'statements');
  assert.equal(url.searchParams.get('statement'),statement.id);
  assert.equal(url.searchParams.get('periods'),'202512,202606');
  assert.equal(url.searchParams.get('period'),'2025-Q4');
  assert.equal(url.searchParams.get('history'),'all');
  assert.deepEqual(statementSelectionForBank(index,afinz,crosswalk,{entity:statement,periods}),{entity:statement,periods});
  // Analysis changes its panel only; remounting Statements reads the same URL
  // identity and periods, rather than substituting the default four columns.
  url.searchParams.delete('panel');
  url.searchParams.set('panel','statements');
  const restored=statementSelectionForBank(index,afinz,crosswalk,{requestedId:url.searchParams.get('statement'),requestedPeriods:url.searchParams.get('periods').split(',')});
  assert.deepEqual(restored,{entity:statement,periods});
  assert.deepEqual({catalog:afinz,entity:statement},before);
});

test('deep link to another prudential statement retains its custom dates through the bank binding change',()=>{
  const requested=['202606','202403'];
  const initial=statementSelectionForBank(index,itau,crosswalk,{requestedId:statement.id,requestedPeriods:requested});
  assert.deepEqual(initial.periods,['202403','202606']);
  const selected=statementAnalysisBank(catalog,crosswalk,initial.entity);
  assert.equal(selected,afinz);
  const bound=statementSelectionForBank(index,selected,crosswalk,initial);
  assert.equal(bound.entity,statement);
  assert.deepEqual(bound.periods,initial.periods);
  assert.deepEqual(requested,['202606','202403']);
  const changed=statementSelectionForBank(index,itau,crosswalk,initial);
  assert.equal(changed.entity.id,'prudential-C0080099');
  assert.deepEqual(changed.periods,changed.entity.defaultPeriods);
});

test('multiple official aliases remain independent even with a unique most recent link',()=>{
  const renamed=entity('prudential-C0085829');
  const matches=Object.values(crosswalk.links).filter(link=>link.statementId===renamed.id);
  assert.equal(matches.length,2);
  assert.deepEqual(matches.map(link=>link.effectivePeriod).sort(),['202603','202606']);
  assert.equal(statementAnalysisBank(catalog,crosswalk,renamed),null);
  assert.equal(statementAnalysisBank(catalog,{links:{}},statement),null);
  assert.equal(statementAnalysisBank(catalog,crosswalk,{...statement,code:'C0000000'}),null);
});

test('individual and incompatible perimeters never imply a global prudential institution',()=>{
  const individual=entity('individual-60701190');
  const requested=statementSelectionForBank(index,itau,crosswalk,{requestedId:individual.id,requestedPeriods:['202512','202606']});
  assert.equal(requested.entity,individual);
  assert.deepEqual(requested.periods,['202512','202606']);
  assert.equal(statementAnalysisBank(catalog,crosswalk,individual),null);
  const fabricated={links:{[itau.id]:{statementId:individual.id,scope:'individual',code:individual.code}}};
  assert.equal(statementAnalysisBank(catalog,fabricated,individual),null);
  const wrongPerimeter={institutions:catalog.institutions.map(entry=>entry.id===afinz.id?{...entry,perimeter:'Individual'}:entry)};
  assert.equal(statementAnalysisBank(wrongPerimeter,crosswalk,statement),null);
  const contradicted={links:{[itau.id]:{statementId:statement.id,scope:statement.scope,code:statement.code}}};
  assert.equal(statementAnalysisBank(catalog,contradicted,statement),null);
  assert.throws(()=>statementNavigationUrl('https://example.com/',itau,individual,requested.periods),/prudencial/);
});

test('navigation rejects invalid date requests instead of writing a substituted default selection',()=>{
  const href='https://example.com/tomaconta/?bank=original&panel=statements';
  for(const periods of [[],['202606','202606'],['201512'],statement.periods.slice(0,9),undefined]){
    assert.throws(()=>statementNavigationUrl(href,afinz,statement,periods),/Competências/);
  }
  assert.equal(new URL(href).searchParams.get('bank'),'original');
});
