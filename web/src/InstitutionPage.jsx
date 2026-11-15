import React,{useCallback,useEffect,useId,useMemo,useRef,useState} from 'react';
import {json,csvDownload} from './data.js';
import {groupColor,groupName,selectLandingCohort} from './landing-data.js';
import InstitutionSearch from './InstitutionSearch.jsx';
import Chart,{ExportMenu} from './Chart.jsx';
import Statements from './Statements.jsx';
import {tabNavigation} from './tab-navigation.js';
import {ANALYSIS_GROUPS,metricLabel,metricNote,metricUnit,metricNumber,quarterLabel,validateInstitutionHistory,observationAt,previousObservation,institutionChart,institutionExportCharts,comparisonChart,institutionRanking,trimChartStart,capitalCompositionChart} from './institution-data.js';
import './institutions.css';

const TABS=[['analysis','Análise'],['statements','Demonstrações'],['compare','Comparar'],['ranking','Ranking'],['data','Dados']];
const parseContext=()=>{const q=new URLSearchParams(location.search);return {tab:TABS.some(([id])=>id===q.get('panel'))?q.get('panel'):'analysis',period:q.get('period')||'',window:['12','all'].includes(q.get('history'))?q.get('history'):'12'};};
function writeContext(values){const url=new URL(location.href);for(const [key,value] of Object.entries(values)){if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);}history.replaceState({},'',url);}

function MetricOptions({metrics}){return Object.entries(metrics).map(([key])=><option key={key} value={key}>{metricLabel(key,metrics)}</option>);}
function HistoryMessage({error,onRetry}){return <div className="institution-empty" role={error?'alert':'status'}>{error||'Carregando histórico…'}{error&&<button type="button" className="institution-text-action" onClick={onRetry}>Tentar novamente</button>}</div>;}

function MetricTable({keys,group,current,previous,period,metrics,selected,onSelect,head=true}){
  const units=keys.map(key=>metricUnit(key,metrics)),oneUnit=new Set(units).size===1;
  return <table className="institution-metrics" aria-label={'Indicadores de '+group.title.toLowerCase()}>
    {head&&<thead><tr><th scope="col">{oneUnit?units[0]:'Indicador'}</th><th scope="col">{quarterLabel(period)}</th><th scope="col">{previous?quarterLabel(previous.period):'Anterior'}</th></tr></thead>}
    <tbody>{keys.map((key,index)=><React.Fragment key={key}>{(!oneUnit||!head)&&(index===0||units[index]!==units[index-1])&&<tr className="institution-unit-group"><th colSpan="3">{units[index]}</th></tr>}<tr><th scope="row"><button type="button" aria-pressed={selected.includes(key)} onClick={()=>onSelect(key)}>{metricLabel(key,metrics)}</button></th><td data-metric={key}>{metricNumber(current?.values[key],key,metrics)}</td><td>{metricNumber(previous?.values[key],key,metrics)}</td></tr></React.Fragment>)}</tbody>
  </table>;
}

function Analysis({bank,payload,metrics,period,window}){
  const [selected,setSelected]=useState(()=>Object.fromEntries(ANALYSIS_GROUPS.map(group=>[group.id,[...group.initial]])));
  const current=observationAt(payload,period),previous=previousObservation(payload,period);
  return <div className="institution-dashboard">{ANALYSIS_GROUPS.map(group=>{
    const keys=selected[group.id],composition=group.id==='capital'&&keys.length===2&&keys.includes('cet1')&&keys.includes('basel'),chart=trimChartStart(composition?capitalCompositionChart({bank,payload,metrics,period,window}):institutionChart({bank,payload,metrics,keys,period,window,id:'bank-'+group.id})),hasData=chart.series.some(series=>series.data.some(point=>point[1]!=null));
    const onSelect=key=>setSelected(value=>({...value,[group.id]:[key]}));
    return <section className="institution-block" key={group.id} aria-labelledby={'institution-'+group.id}>
      <h2 id={'institution-'+group.id}>{group.title}</h2>
      <MetricTable keys={group.metrics} {...{group,current,previous,period,metrics,onSelect}} selected={keys}/>
      {hasData?<Chart chart={chart} height={210} compact showLegend={keys.length>1}/>:<p className="institution-chart-empty">Sem observações neste recorte.</p>}
      <p className="institution-chart-note">{composition?chart.note:keys.length===1?metricNote(keys[0],metrics)||group.note:group.note}</p>
      {group.more.length>0&&<details className="institution-more"><summary>Outros indicadores</summary><MetricTable keys={group.more} {...{group,current,previous,period,metrics,onSelect}} selected={keys} head={false}/></details>}
    </section>;
  })}</div>;
}

function Source({catalog,bank,period,tab,peers=[]}){
  return <details className="institution-source"><summary>Fonte: BCB / IFData</summary>
    <p>{tab==='ranking'?'Perímetro '+bank.perimeter:tab==='compare'?peers.map(entry=>entry.name).join('; ')+' · '+bank.perimeter:bank.name+' · '+bank.perimeter} · {quarterLabel(tab==='ranking'?catalog.latestPeriod:period,true)}.</p>
    <p>Valores monetários dos gráficos em R$ bilhões; percentuais na escala publicada. N/D indica ausência. Dados mostra os valores nas unidades originais. Conceitos e mudanças de metodologia acompanham os gráficos.</p>
    <p>Publicação {catalog.source.publicationId}. <a href={catalog.source.url} target="_blank" rel="noreferrer">Consultar IFData no Banco Central</a>.</p>
  </details>;
}

function Comparison({catalog,banks,histories,metric,setMetric,period,window,perimeter,onAdd,onRemove,error,loading}){
  const available=useMemo(()=>({...catalog,institutions:catalog.institutions.filter(bank=>bank.perimeter===perimeter&&!banks.some(selected=>selected.id===bank.id))}),[catalog,perimeter,banks]);
  const suggested=useMemo(()=>available.institutions.filter(bank=>bank.latestPeriod===catalog.latestPeriod).slice().sort((a,b)=>(b.latest.assets??-Infinity)-(a.latest.assets??-Infinity)).slice(0,4),[available,catalog.latestPeriod]);
  const chart=comparisonChart({banks,histories,metrics:catalog.metrics,key:metric,period,window,perimeter});
  return <section className="institution-comparison">
    <div className="institution-section-title"><h2>Comparar instituições</h2><span>{quarterLabel(period,true)}</span></div>
    <div className="institution-comparison-controls"><label>Indicador <select value={metric} onChange={event=>setMetric(event.target.value)}><MetricOptions metrics={catalog.metrics}/></select></label>
      {banks.length<4?<InstitutionSearch catalog={available} onSelect={onAdd} suggested={suggested} placeholder="Adicionar instituição" label="Adicionar instituição à comparação"/>:<span className="institution-selection-limit">Quatro instituições selecionadas</span>}
    </div>
    <div className="institution-peer-list">{banks.map(bank=><span className="institution-peer" key={bank.id}><span className="institution-swatch" style={{background:groupColor(bank)}} aria-hidden="true"/>{groupName(bank)}<button type="button" aria-label={'Remover '+groupName(bank)} onClick={()=>onRemove(bank.id)}>remover</button></span>)}</div>
    {error&&<p className="institution-inline-error" role="alert">{error}</p>}
    {loading?<p className="institution-empty" role="status">Carregando comparação…</p>:banks.length?<>
      <Chart chart={chart} height={330} colors={banks.map(groupColor)} showLegend={false}/>
      <table className="institution-comparison-values"><thead><tr><th scope="col">Instituição</th><th scope="col">{metricLabel(metric,catalog.metrics)} · {metricUnit(metric,catalog.metrics,true)}</th></tr></thead><tbody>{banks.map(bank=>{const payload=histories.find(history=>history.id===bank.id),row=observationAt(payload,period);return <tr key={bank.id}><th scope="row"><span className="institution-swatch" style={{background:groupColor(bank)}} aria-hidden="true"/>{groupName(bank)}</th><td>{metricNumber(row?.values[metric],metric,catalog.metrics)}</td></tr>;})}</tbody></table>
    </>:<p className="institution-empty">Selecione até quatro instituições para comparar.</p>}
    <p className="institution-footnote">Mesmo perímetro e competência. {metricNote(metric,catalog.metrics)}</p>
  </section>;
}

function Ranking({catalog,bank,metric,setMetric,onSelect}){
  const [query,setQuery]=useState(''),[limit,setLimit]=useState(100),perimeter=bank.perimeter;
  const all=useMemo(()=>institutionRanking(catalog,{perimeter,key:metric}),[catalog,perimeter,metric]),rows=useMemo(()=>institutionRanking(catalog,{perimeter,key:metric,query}),[catalog,perimeter,metric,query]),position=all.find(({bank:entry})=>entry.id===bank.id)?.rank;
  return <section className="institution-ranking"><div className="institution-section-title"><h2>Ranking</h2><label>Indicador <select value={metric} onChange={event=>{setMetric(event.target.value);setLimit(100);}}><MetricOptions metrics={catalog.metrics}/></select></label></div>
    <div className="institution-ranking-context"><span>{quarterLabel(catalog.latestPeriod,true)} · {all.length.toLocaleString('pt-BR')} instituições com dado</span><span>{groupName(bank)} · {position?position+'ª posição':'N/D'}</span></div>
    <label className="institution-ranking-search">Buscar na lista<input type="search" value={query} onChange={event=>{setQuery(event.target.value);setLimit(100);}} placeholder="Nome da instituição"/></label>
    <table><thead><tr><th scope="col">#</th><th scope="col">Instituição</th><th scope="col">{metricLabel(metric,catalog.metrics)}<span className="institution-unit">{metricUnit(metric,catalog.metrics,true)}</span></th></tr></thead><tbody>{rows.slice(0,limit).map(({bank:entry,rank})=><tr key={entry.id} className={entry.id===bank.id?'is-current':undefined}><td>{rank}</td><th scope="row"><button type="button" onClick={()=>onSelect(entry)}>{groupName(entry)}</button></th><td>{metricNumber(entry.latest[metric],metric,catalog.metrics)}</td></tr>)}</tbody></table>
    {!rows.length&&<p className="institution-empty">Nenhuma instituição com dado corresponde à busca.</p>}
    {rows.length>limit&&<button type="button" className="institution-text-action" onClick={()=>setLimit(value=>value+100)}>Ver mais posições</button>}
    <p className="institution-footnote">Ordenação decrescente pelo valor publicado. Instituições sem observação nesta competência ficam fora da lista.</p>
  </section>;
}

function Data({catalog,payload,period}){
  const row=observationAt(payload,period);
  return <section className="institution-data" aria-label="Valores originais"><table><thead><tr><th scope="col">Indicador</th><th scope="col">Valor original</th><th scope="col">Unidade</th></tr></thead><tbody>{Object.entries(catalog.metrics).map(([key,metric])=><tr key={key}><th scope="row">{metric.label}</th><td>{metricNumber(row?.values[key],key,catalog.metrics,{raw:true})}</td><td className="institution-data-unit">{metric.unit}</td></tr>)}</tbody></table></section>;
}

export default function InstitutionPage({catalog,bankId,onSelect,onStatementSelect,statementIndex,onRetryStatements}){
  const initial=useRef(parseContext()),[tab,setTab]=useState(initial.current.tab),[asOf,setAsOf]=useState(initial.current.period),[window,setWindow]=useState(initial.current.window),[payload,setPayload]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[metric,setMetric]=useState('roe'),[peerIds,setPeerIds]=useState([bankId]),[peerHistories,setPeerHistories]=useState([]),[peerError,setPeerError]=useState(''),[peerLoading,setPeerLoading]=useState(false),[exportHost,setExportHost]=useState(null);
  const previousBank=useRef(bankId),cache=useRef(new Map()),tabPrefix=useId(),bank=catalog.institutions.find(entry=>entry.id===bankId)||catalog.institutions[0],period=asOf||bank.latestPeriod;
  const peers=useMemo(()=>peerIds.map(id=>catalog.institutions.find(entry=>entry.id===id)).filter(entry=>entry&&entry.perimeter===bank.perimeter),[catalog,peerIds,bank.perimeter]);
  const perimeters=useMemo(()=>[...new Set(catalog.institutions.map(entry=>entry.perimeter))],[catalog]);
  const suggested=useMemo(()=>selectLandingCohort(catalog).slice(0,4),[catalog]);

  useEffect(()=>{let active=true;setPayload(null);setError('');const changed=previousBank.current!==bank.id,preserveStatements=tab==='statements';
    if(changed){if(!preserveStatements){setAsOf(bank.latestPeriod);setTab('analysis');}setPeerIds([bank.id]);previousBank.current=bank.id;}
    const desiredPeriod=changed&&!preserveStatements?bank.latestPeriod:asOf||bank.latestPeriod;
    const cached=cache.current.get(bank.id);
    const task=cached?Promise.resolve(cached):json(bank.historyPath).then(result=>validateInstitutionHistory(bank,result));
    task.then(result=>{if(active){cache.current.set(bank.id,result);setPayload(result);if(!result.history.some(row=>row.period===desiredPeriod))setAsOf(result.history.at(-1)?.period||bank.latestPeriod);}}).catch(reason=>{if(active)setError(reason.message);});
    return()=>{active=false;};
  },[bank.id,retry]);

  useEffect(()=>{let active=true;if(tab!=='compare')return;setPeerLoading(true);setPeerError('');
    Promise.allSettled(peers.map(entry=>{const cached=cache.current.get(entry.id);return cached?Promise.resolve(cached):json(entry.historyPath).then(result=>{validateInstitutionHistory(entry,result);cache.current.set(entry.id,result);return result;});})).then(results=>{
      if(!active)return;setPeerHistories(results.filter(result=>result.status==='fulfilled').map(result=>result.value));const unavailable=results.flatMap((result,index)=>result.status==='rejected'?[groupName(peers[index])]:[]);if(unavailable.length)setPeerError('Histórico indisponível: '+unavailable.join(', ')+'. Remova e selecione novamente para tentar.');setPeerLoading(false);
    });return()=>{active=false;};
  },[tab,peers]);

  useEffect(()=>{writeContext({panel:tab==='analysis'?null:tab,period:period===bank.latestPeriod?null:period,history:window==='12'?null:window});},[tab,period,window,bank.latestPeriod]);
  useEffect(()=>{const back=()=>{const context=parseContext();setTab(context.tab);setAsOf(context.period);setWindow(context.window);};globalThis.addEventListener('popstate',back);return()=>globalThis.removeEventListener('popstate',back);},[]);

  const ready=payload?.id===bank.id&&payload?.perimeter===bank.perimeter;
  const exportCharts=useMemo(()=>ready?institutionExportCharts({bank,payload,metrics:catalog.metrics,period,window}):[],[ready,bank,payload,catalog.metrics,period,window]);
  const compare=useMemo(()=>comparisonChart({banks:peers,histories:peerHistories,metrics:catalog.metrics,key:metric,period,window,perimeter:bank.perimeter}),[peers,peerHistories,catalog.metrics,metric,period,window,bank.perimeter]);
  function choose(entry){onSelect(entry);setTab('analysis');setAsOf(entry.latestPeriod);setPeerIds([entry.id]);}
  const statementContext=useCallback(context=>{
    if(context?.analysisBank&&context.analysisBank.id!==bank.id)onStatementSelect?.(context.analysisBank,context,context.periods);
  },[bank.id,onStatementSelect]);
  function changePerimeter(value){const next=catalog.institutions.filter(entry=>entry.perimeter===value).slice().sort((a,b)=>(b.latest.assets??-Infinity)-(a.latest.assets??-Infinity))[0];if(next)choose(next);}
  function exportRanking(){const rows=catalog.institutions.filter(entry=>entry.perimeter===bank.perimeter&&entry.latestPeriod===catalog.latestPeriod).map(entry=>({title:entry.name,unit:catalog.metrics[metric].unit,source:'BCB / IFData · '+entry.perimeter,series:[{name:catalog.metrics[metric].label,data:[[entry.latestPeriod,entry.latest[metric]]]}]}));csvDownload(rows,'Ranking_'+metric+'_'+catalog.latestPeriod);}
  const statementActive=tab==='statements',title=groupName(bank);
  return <div className="institution-page">
    <header className="institution-header tc-page-header">
      <div className="institution-identity"><div><h1>{title}</h1>{statementActive&&<p>Demonstrações contábeis</p>}</div><InstitutionSearch catalog={catalog} suggested={suggested} onSelect={choose} placeholder="Trocar instituição" label="Trocar instituição"/></div>
      <div className="institution-toolbar">
        {!statementActive&&<div className="institution-filters"><label>Perímetro <select value={bank.perimeter} onChange={event=>changePerimeter(event.target.value)}>{perimeters.map(value=><option key={value} value={value}>{value==='Prudencial'?value:'Financeiro / independente'}</option>)}</select></label>
          {tab!=='ranking'&&<label>Competência <select aria-label="Competência" value={period} disabled={!ready} onChange={event=>setAsOf(event.target.value)}>{(ready?payload.history:[{period:bank.latestPeriod}]).slice().reverse().map(row=><option key={row.period} value={row.period}>{quarterLabel(row.period,true)}</option>)}</select></label>}
          {['analysis','compare'].includes(tab)&&<label>Histórico <select aria-label="Janela histórica" value={window} onChange={event=>setWindow(event.target.value)}><option value="12">3 anos</option><option value="all">Completo</option></select></label>}
        </div>}
        {tab==='ranking'?<details className="institution-export"><summary>Exportar</summary><div><button type="button" onClick={exportRanking}>Ranking · CSV</button></div></details>:!statementActive&&<ExportMenu charts={tab==='compare'?[compare]:exportCharts} title={tab==='compare'?'Comparação de instituições · '+bank.perimeter:bank.name} disabled={!ready||(tab==='compare'&&(peerLoading||!!peerError||!peers.length))} onError={setError}/>}
        <div className="institution-export-host" ref={setExportHost}/>
      </div>
      <div className="institution-tabs" role="tablist" aria-label="Análise da instituição">{TABS.map(([id,label])=><button type="button" id={`${tabPrefix}-${id}`} key={id} role="tab" aria-selected={tab===id} tabIndex={tab===id?0:-1} aria-controls={`${tabPrefix}-panel`} onKeyDown={tabNavigation} onClick={()=>{setTab(id);setError('');}}>{label}</button>)}</div>
    </header>
    <div className="tc-page-content institution-content" role="tabpanel" id={`${tabPrefix}-panel`} aria-labelledby={`${tabPrefix}-${tab}`}>
      {statementActive?<Statements index={statementIndex} {...{catalog,bank,exportHost}} onContextChange={statementContext} onRetryIndex={onRetryStatements}/>:<>
        {error&&ready&&<p className="institution-inline-error" role="alert">{error}</p>}
        {tab==='analysis'&&(ready?<Analysis {...{bank,payload,period,window}} metrics={catalog.metrics}/>:<HistoryMessage error={error} onRetry={()=>setRetry(value=>value+1)}/>)}
        {tab==='compare'&&<Comparison {...{catalog,metric,setMetric,period,window}} banks={peers} histories={peerHistories} perimeter={bank.perimeter} onAdd={entry=>setPeerIds(ids=>ids.length<4&&!ids.includes(entry.id)?[...ids,entry.id]:ids)} onRemove={id=>setPeerIds(ids=>ids.filter(value=>value!==id))} loading={peerLoading} error={peerError}/>}
        {tab==='ranking'&&<Ranking {...{catalog,bank,metric,setMetric}} onSelect={choose}/>}
        {tab==='data'&&(ready?<Data {...{catalog,payload,period}}/>:<HistoryMessage error={error} onRetry={()=>setRetry(value=>value+1)}/>)}
        <Source {...{catalog,bank,period,tab,peers}}/>
      </>}
    </div>
  </div>;
}
