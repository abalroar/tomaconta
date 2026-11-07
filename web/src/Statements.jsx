import React,{useEffect,useId,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ChevronDown} from 'lucide-react';
import {download,json} from './data.js';
import {groupName,searchInstitutions} from './landing-data.js';
import InstitutionSearch from './InstitutionSearch.jsx';
import {tabNavigation} from './tab-navigation.js';
import {prepareStatement,exportStatement,resetStatementRuntime} from './statements-runtime.js';
import {SCOPE_LABELS,statementPeriodLabel,samePeriods,validateStatementPacket,preferredStatement,statementSearchCatalog,selectedStatementPeriods,statementFileName} from './statement-data.js';
import './statements.css';

const TABLES=['Balanço','DRE','Carteira 4.966'];
const selectedFromUrl=()=>{const query=new URLSearchParams(location.search);return {id:query.get('statement'),periods:query.get('periods')?.split(',')};};
function storeSelection(entity,periods){const url=new URL(location.href);url.searchParams.set('statement',entity.id);url.searchParams.set('periods',periods.join(','));history.replaceState({},'',url);}
function useSmallTable(){const [small,setSmall]=useState(()=>matchMedia('(max-width:600px)').matches);useEffect(()=>{const query=matchMedia('(max-width:600px)'),change=()=>setSmall(query.matches);query.addEventListener('change',change);return()=>query.removeEventListener('change',change);},[]);return small;}

function PeriodPicker({entity,periods,onChange,disabled}){
  const node=useRef(null),[draft,setDraft]=useState(periods);
  useEffect(()=>setDraft(periods),[periods]);
  useEffect(()=>{function outside(event){if(node.current?.open&&!node.current.contains(event.target))node.current.open=false;}function escape(event){if(event.key==='Escape'&&node.current?.open){node.current.open=false;node.current.querySelector('summary')?.focus();}}document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};},[]);
  function choose(period,checked){setDraft(values=>checked?(values.length<8?[...values,period].sort():values):values.filter(value=>value!==period));}
  return <details ref={node} className="statements-period-picker" onToggle={event=>{if(event.currentTarget.open)setDraft(periods);}}>
    <summary>{periods.length===1?statementPeriodLabel(periods[0],true):`${periods.length} competências`}<ChevronDown size={14} strokeWidth={1.6} aria-hidden="true"/></summary>
    <div className="statements-period-options"><div className="statements-period-actions"><span>{draft.length} de 8</span><button type="button" onClick={()=>setDraft([])}>Limpar</button></div>
      <div className="statements-period-grid">{entity.periods.slice().reverse().map(period=><label key={period}><input type="checkbox" checked={draft.includes(period)} disabled={disabled||draft.length>=8&&!draft.includes(period)} onChange={event=>choose(period,event.target.checked)}/><span>{statementPeriodLabel(period,true)}</span></label>)}</div>
      <div className="statements-period-actions"><button type="button" onClick={()=>setDraft(selectedStatementPeriods(entity))}>Últimos trimestres</button><button type="button" className="statements-apply" disabled={disabled||!draft.length} onClick={()=>{onChange(draft.slice().sort());node.current.open=false;}}>Aplicar</button></div>
    </div>
  </details>;
}

function StatementExport({entity,periods,packet,disabled,onStatus,onError}){
  const node=useRef(null),controller=useRef(null),context=useRef(''),[busy,setBusy]=useState(false),[status,setStatus]=useState('');
  const key=entity?.id+':'+periods.join(',');context.current=key;
  useEffect(()=>{setStatus('');setBusy(false);controller.current?.abort();return()=>controller.current?.abort();},[key]);
  useEffect(()=>{function outside(event){if(node.current?.open&&!node.current.contains(event.target))node.current.open=false;}function escape(event){if(event.key==='Escape'&&node.current?.open){node.current.open=false;node.current.querySelector('summary')?.focus();}}document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};},[]);
  async function run(format){
    if(disabled||busy||!entity)return;const selectedKey=key,abort=new AbortController();controller.current=abort;setBusy(true);setStatus('Preparando arquivo…');
    const progress=message=>{if(!abort.signal.aborted&&context.current===selectedKey){setStatus(message);onStatus?.(message);}};
    try{const blob=await exportStatement(entity,periods,format,progress,{signal:abort.signal});if(abort.signal.aborted||context.current!==selectedKey)return;download(blob,statementFileName(packet,entity,periods,format));setStatus(format==='xlsx'?'Excel preparado.':'PowerPoint preparado.');}
    catch(error){if(error.name!=='AbortError'&&context.current===selectedKey){setStatus(error.message);onError?.(error.message);}}
    finally{if(context.current===selectedKey)setBusy(false);}
  }
  return <details ref={node} className="tc-export-menu"><summary>Exportar</summary><div className="tc-export-options"><strong>{entity?groupName(entity):'Demonstrações'}</strong>{entity&&<p>{SCOPE_LABELS[entity.scope]} · {periods.map(period=>statementPeriodLabel(period)).join(', ')}</p>}
    <button type="button" disabled={disabled||busy||!entity} onClick={()=>run('xlsx')}>Excel da análise</button><button type="button" disabled={disabled||busy||!entity} onClick={()=>run('pptx')}>{periods.length>3?'PPTX · últimas 3 competências':'PPTX da análise'}</button>
    {status&&<p role="status" aria-live="polite">{status}</p>}
  </div></details>;
}

function StatementTable({table,periods,detail,shares}){
  const rows=detail?table.rows:table.rows.filter(row=>!['indent','detail'].includes(row.style));
  return <table className="statements-table" aria-label={table.name+' · R$ milhões e percentuais'}>
    <colgroup><col style={{width:'40%'}}/>{periods.flatMap(period=>shares?[<col key={period+'-amount'} style={{width:45/periods.length+'%'}}/>,<col key={period+'-share'} style={{width:15/periods.length+'%'}}/>]:[<col key={period} style={{width:60/periods.length+'%'}}/>])}</colgroup>
    <thead><tr><th scope="col" rowSpan={shares?2:1}>Conta</th>{periods.map(period=><th scope={shares?'colgroup':'col'} key={period} colSpan={shares?2:1}>{statementPeriodLabel(period)}</th>)}</tr>{shares&&<tr>{periods.flatMap(period=>[<th key={period+'-amount'} scope="col">Valor</th>,<th key={period+'-share'} scope="col">%</th>])}</tr>}</thead>
    <tbody>{rows.map(row=><tr key={row.id} className={'statements-row statements-'+row.style+(row.tier==='key'?' statements-key':'')}><th scope="row">{row.label}</th>{periods.flatMap(period=>(shares?['amount','share']:['amount']).map(kind=>{const cell=row.cells[period]?.[kind];return <td key={period+'-'+kind} className={cell?.tone?'is-'+cell.tone:undefined} data-row={row.id} data-period={period} data-kind={kind} data-state={cell?.state||'missing'} data-value={cell?.value??'null'}>{cell?.display||'–'}</td>;}))}</tr>)}</tbody>
  </table>;
}

export default function Statements({index,bank,exportHost,onContextChange,onRetryIndex}){
  const [crosswalk,setCrosswalk]=useState(null),[crosswalkReady,setCrosswalkReady]=useState(false),[entityId,setEntityId]=useState(''),[scope,setScope]=useState('prudential'),[periods,setPeriods]=useState([]),[tableName,setTableName]=useState('Balanço'),[packet,setPacket]=useState(null),[loading,setLoading]=useState(false),[status,setStatus]=useState(''),[error,setError]=useState(''),[retry,setRetry]=useState(0),[detail,setDetail]=useState(false),[shares,setShares]=useState(false),[page,setPage]=useState(0);
  const defaults=useRef(selectedFromUrl()),boundBank=useRef(''),remembered=useRef({}),snapshotCache=useRef(new Map()),small=useSmallTable(),id=useId();
  const entity=index?.institutions.find(entry=>entry.id===entityId)||null;
  const searchable=useMemo(()=>index&&!index.unavailable?statementSearchCatalog(index,scope):{institutions:[]},[index,scope]);
  const suggested=useMemo(()=>searchInstitutions(searchable,groupName(bank),{limit:4}),[searchable,bank]);
  const ready=entity&&packet?.id===entity.id&&samePeriods(packet.periods,periods),tables=ready?packet.tables:[],table=tables.find(entry=>entry.name===tableName)||tables[0];
  const perPage=small?2:shares?3:4,totalPages=Math.max(1,Math.ceil(periods.length/perPage)),shown=periods.slice(Math.min(page,totalPages-1)*perPage,(Math.min(page,totalPages-1)+1)*perPage);

  useEffect(()=>{let active=true;if(!index||index.unavailable)return;setCrosswalkReady(false);json(index.crosswalkPath).then(result=>{if(active)setCrosswalk(result);}).catch(()=>{if(active)setCrosswalk(null);}).finally(()=>{if(active)setCrosswalkReady(true);});return()=>{active=false;};},[index]);
  useEffect(()=>{
    if(!index||index.unavailable||!crosswalkReady||boundBank.current===bank.id)return;
    const requested=index.institutions.find(entry=>entry.id===defaults.current.id),preferred=requested||preferredStatement(index,bank,crosswalk);
    boundBank.current=bank.id;
    if(preferred){setEntityId(preferred.id);setScope(preferred.scope);setPeriods(selectedStatementPeriods(preferred,defaults.current.periods));remembered.current[preferred.scope]=preferred.id;}
    else{setEntityId('');setPeriods([]);setScope('prudential');}
    defaults.current={};
  },[index,crosswalkReady,crosswalk,bank.id]);

  useEffect(()=>{if(!entity||!periods.length){setPacket(null);onContextChange?.(null);return;}storeSelection(entity,periods);onContextChange?.({id:entity.id,code:entity.code,name:entity.name,scope:entity.scope});},[entity,periods,onContextChange]);
  useEffect(()=>{
    const abort=new AbortController();let active=true;
    if(!entity||!periods.length)return()=>abort.abort();
    setLoading(true);setError('');setStatus('Carregando demonstrações…');setPage(0);
    async function load(){
      try{
        let result;
        if(samePeriods(periods,entity.defaultPeriods)){
          const cached=snapshotCache.current.get(entity.id);
          try{result=cached||validateStatementPacket(entity,periods,await json(entity.path));snapshotCache.current.set(entity.id,result);if(snapshotCache.current.size>4)snapshotCache.current.delete(snapshotCache.current.keys().next().value);}
          catch{result=await prepareStatement(entity,periods,message=>{if(active)setStatus(message);},{signal:abort.signal});}
        }else result=await prepareStatement(entity,periods,message=>{if(active)setStatus(message);},{signal:abort.signal});
        validateStatementPacket(entity,periods,result);
        if(active){setPacket(result);setStatus('');}
      }catch(reason){if(active&&reason.name!=='AbortError'){setError(reason.message);setStatus('');}}
      finally{if(active)setLoading(false);}
    }
    load();return()=>{active=false;abort.abort();};
  },[entity,periods,retry]);
  useEffect(()=>{function back(){const selected=selectedFromUrl(),next=index?.institutions.find(entry=>entry.id===selected.id);if(next){setEntityId(next.id);setScope(next.scope);setPeriods(selectedStatementPeriods(next,selected.periods));}}globalThis.addEventListener('popstate',back);return()=>globalThis.removeEventListener('popstate',back);},[index]);

  function select(next){const actual=index.institutions.find(entry=>entry.id===next.id);if(!actual)return;remembered.current[actual.scope]=actual.id;setScope(actual.scope);setEntityId(actual.id);setPeriods(selectedStatementPeriods(actual));setPage(0);setError('');}
  function changeScope(next){setScope(next);const previous=index.institutions.find(entry=>entry.id===remembered.current[next]);if(previous){setEntityId(previous.id);setPeriods(selectedStatementPeriods(previous));}else{setEntityId('');setPeriods([]);setError('');onContextChange?.(null);const url=new URL(location.href);url.searchParams.delete('statement');url.searchParams.delete('periods');history.replaceState({},'',url);}}
  function retryAnalysis(){resetStatementRuntime();setRetry(value=>value+1);}

  if(!index)return <p className="institution-empty" role="status">Carregando catálogo de demonstrações…</p>;
  if(index.unavailable)return <div className="institution-empty" role="alert">O catálogo de demonstrações não pôde ser carregado.<button type="button" className="institution-text-action" onClick={onRetryIndex}>Tentar novamente</button></div>;

  const exportMenu=<StatementExport {...{entity,periods}} packet={ready?packet:null} disabled={!ready||loading} onError={setError}/>;
  return <section className="statements-page" aria-labelledby={`${id}-heading`}>
    {exportHost?createPortal(exportMenu,exportHost):<div className="statements-local-export">{exportMenu}</div>}
    <div className="statements-toolbar"><div className="statements-tabs" role="tablist" aria-label="Demonstração">{TABLES.map((name,index)=><button type="button" role="tab" id={`${id}-tab-${index}`} key={name} aria-selected={name===tableName} tabIndex={name===tableName?0:-1} aria-controls={`${id}-table`} onKeyDown={tabNavigation} onClick={()=>setTableName(name)}>{name}</button>)}</div><label>Perímetro <select value={scope} onChange={event=>changeScope(event.target.value)}><option value="prudential">Prudencial</option><option value="individual">Individual</option></select></label></div>
    <div className="statements-selection"><InstitutionSearch catalog={searchable} suggested={suggested} onSelect={select} placeholder={scope==='individual'?'Buscar pessoa jurídica ou CNPJ-base':'Buscar conglomerado ou código'} label="Selecionar instituição das demonstrações"/>{entity&&<PeriodPicker {...{entity,periods}} onChange={setPeriods}/>}</div>
    {!entity?<p className="institution-empty">{!crosswalkReady?'Identificando a instituição…':scope==='individual'?'Escolha a pessoa jurídica no perímetro individual.':'Selecione um conglomerado para consultar Balanço e DRE.'}</p>:<>
      <div className="statements-identity"><div><strong>{entity.name}</strong><p>{scope==='individual'?`CNPJ-base ${entity.code} · COSIF 4010`:`Conglomerado ${entity.code} · COSIF 4060 / 4066`}</p></div><span>R$ milhões · índices em %</span></div>
      {error&&<div className="statements-error" role="alert"><p>{error}</p><button type="button" className="institution-text-action" onClick={retryAnalysis}>Tentar novamente</button></div>}
      {!ready||loading?<p className="institution-empty" role="status">{error?'Selecione outra instituição ou tente novamente.':status||'Preparando demonstrativos…'}</p>:table&&<>
        <div className="institution-section-title"><h2 id={`${id}-heading`}>{table.name}</h2><div className="statements-table-controls"><label><input type="checkbox" checked={shares} onChange={event=>{setShares(event.target.checked);setPage(0);}}/>Composição (%)</label><button type="button" className="institution-text-action" onClick={()=>setDetail(value=>!value)}>{detail?'Recolher contas':'Detalhar contas'}</button></div></div>
        {totalPages>1&&<div className="statements-pagination"><span>{shown.map(period=>statementPeriodLabel(period)).join(' · ')}</span><div><button type="button" disabled={page<=0} onClick={()=>setPage(value=>Math.max(0,value-1))}>Anteriores</button><span>{Math.min(page,totalPages-1)+1} / {totalPages}</span><button type="button" disabled={page>=totalPages-1} onClick={()=>setPage(value=>Math.min(totalPages-1,value+1))}>Próximas</button></div></div>}
        <div id={`${id}-table`} role="tabpanel" aria-labelledby={`${id}-tab-${TABLES.indexOf(tableName)}`} className="statements-table-container">{table.rows.some(row=>periods.some(period=>row.cells[period]?.amount?.value!=null))?<StatementTable {...{table,detail,shares}} periods={shown}/>:<p className="institution-empty">Sem dados desta demonstração no perímetro e nas competências escolhidos.</p>}</div>
        {table.name==='DRE'&&<p className="statements-footnote">Resultado acumulado no ano em cada data-base. O período de acumulação reinicia em janeiro.</p>}
        {table.name==='DRE'&&packet.referenceNote&&<p className="statements-footnote">{packet.referenceNote}</p>}
        <details className="institution-source"><summary>Fonte: BCB / COSIF · critérios de apresentação</summary><p>{entity.name} · {SCOPE_LABELS[scope]} · {periods.map(period=>statementPeriodLabel(period,true)).join(', ')}. – indica dado não disponível.</p><p>Valores monetários em R$ milhões. As porcentagens conservam o formato das demonstrações de origem.</p>{packet.limitations.map((note,index)=><p key={index}>{note}</p>)}
          <details className="statements-checks"><summary>Verificações contábeis</summary><table><thead><tr><th>Verificação</th><th>Competência</th><th>Resultado</th></tr></thead><tbody>{packet.checks.map((check,index)=><tr key={index}><th scope="row">{check.check}</th><td>{statementPeriodLabel(check.period)}</td><td>{check.status}</td></tr>)}</tbody></table></details>
        </details>
      </>}
    </>}
  </section>;
}
