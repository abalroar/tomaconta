import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {selectedStatementPeriods,samePeriods,statementSelectionForBank,statementAnalysisBank,statementNavigationUrl} from '../src/statement-data.js';

const read=async path=>JSON.parse(await readFile(new URL('../public/data/'+path,import.meta.url),'utf8'));
const [catalog,index,crosswalk]=await Promise.all(['institutions.json','statements/index.json','statements/crosswalk.json'].map(read));
const source=await readFile(new URL('../src/Statements.jsx',import.meta.url),'utf8');
const itau=catalog.institutions.find(bank=>bank.id==='5f6d3c0745685d8f');
const afinz=index.institutions.find(entity=>entity.id==='prudential-C0083539');

// Exercise the actual UI handler and bank-binding effect, rather than supplying
// an already-correct helper state. No DOM/browser or extra test dependency.
function bodyAfter(marker){
  const markerAt=source.indexOf(marker);assert.notEqual(markerAt,-1,marker);
  const start=source.indexOf('{',markerAt);let depth=0,quote=null,escaped=false;
  for(let at=start;at<source.length;at++){
    const char=source[at];
    if(quote){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char===quote)quote=null;continue;}
    if(char==='"'||char==="'"||char==='`'){quote=char;continue;}
    if(char==='{')depth++;else if(char==='}'&&!--depth)return source.slice(start,at+1);
  }
  throw Error('Unclosed UI function: '+marker);
}
const selectBody=bodyAfter('function select(next)');
const bindingBody=bodyAfter('useEffect(()=>{\n    if(!index||index.unavailable||!crosswalkReady');
function compile(args,body){return new Function(...Object.keys(args),body)(...Object.values(args));}

function flow(requested=['202512','202606'],customIndex=index){
  const state={entityId:'prudential-C0080099',scope:'prudential',periods:requested.slice(),bank:itau,periodNotice:'',page:0,error:''};
  const defaults={current:{}},boundBank={current:itau.id},remembered={current:{}};
  const bindings=()=>({index:customIndex,periods:state.periods,remembered,selectedStatementPeriods,samePeriods,
    setScope:value=>{state.scope=value;},setEntityId:value=>{state.entityId=value;},setPeriods:value=>{state.periods=value;},
    setPage:value=>{state.page=value;},setError:value=>{state.error=value;},setPeriodNotice:value=>{state.periodNotice=value;}});
  function select(next){compile({...bindings(),next},selectBody);}
  function bindBank(){
    const entity=customIndex.institutions.find(entry=>entry.id===state.entityId);
    compile({...bindings(),entity,bank:state.bank,crosswalk,crosswalkReady:true,boundBank,defaults,statementSelectionForBank},bindingBody);
  }
  return {state,select,bindBank,sync(){
    const entity=customIndex.institutions.find(entry=>entry.id===state.entityId);
    state.bank=statementAnalysisBank(catalog,crosswalk,entity)||state.bank;
    return statementNavigationUrl('https://example.com/tomaconta/?view=institutions&panel=statements',state.bank,entity,state.periods);
  }};
}

test('actual selector retains two Itaú dates when choosing Afinz before the context callback and bank effect',()=>{
  const app=flow();app.select(afinz);
  assert.deepEqual(app.state.periods,['202512','202606']);
  assert.equal(app.state.entityId,afinz.id);
  assert.equal(app.state.periodNotice,'');
  // The effect can run before and after the parent propagates the new bank.
  app.bindBank();assert.deepEqual(app.state.periods,['202512','202606']);
  const url=app.sync();app.bindBank();app.bindBank();
  assert.equal(url.searchParams.get('bank'),'73f0e1311a08e627');
  assert.equal(url.searchParams.get('statement'),afinz.id);
  assert.equal(url.searchParams.get('periods'),'202512,202606');
  assert.deepEqual(app.state.periods,['202512','202606']);
  const restored=statementSelectionForBank(index,app.state.bank,crosswalk,{requestedId:url.searchParams.get('statement'),requestedPeriods:url.searchParams.get('periods').split(',')});
  assert.deepEqual(restored.periods,['202512','202606']);
});

test('actual selector preserves arbitrary available dates rather than a four-column default',()=>{
  const app=flow(['202403','202606']);app.select(afinz);
  assert.deepEqual(app.state.periods,['202403','202606']);
  app.sync();app.bindBank();assert.deepEqual(app.state.periods,['202403','202606']);
});

test('an unavailable requested slice selects valid dates with an explicit visible notice',()=>{
  const limited={...afinz,periods:['202303'],defaultPeriods:['202303']};
  const limitedIndex={...index,institutions:index.institutions.map(entity=>entity.id===afinz.id?limited:entity)};
  const app=flow(['202512','202606'],limitedIndex);app.select(limited);
  assert.deepEqual(app.state.periods,['202303']);
  assert.match(app.state.periodNotice,/competências.*indisponíveis/i);
  assert.match(source,/periodNotice&&<p[^>]*role="status"/);
  app.sync();app.bindBank();assert.deepEqual(app.state.periods,['202303']);
});
