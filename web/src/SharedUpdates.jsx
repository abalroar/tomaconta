import React,{useCallback,useEffect,useRef,useState} from 'react';
import {SHARED_BASES,buildSharedPlan,financialPlan,newerSharedPublication,newRequestKey,pendingSharedJobs,publishedMonth,sharedBase,sharedJobOutcome,sharedJobState,sharedStatus,submitSharedPlan,suggestedSharedWindow} from './shared-client.js';
import './shared-updates.css';

function updatedAt(value){
  const date=new Date(value);
  return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date):'N/D';
}

export default function SharedUpdates({publication,catalog,manifest}){
  const [kind,setKind]=useState('financeiro'),[mode,setMode]=useState('incremental');
  const [reference,setReference]=useState('auto'),[period,setPeriod]=useState(()=>publishedMonth(catalog)),[interval,setIntervalWindow]=useState(false),[window,setWindow]=useState({start:'',end:''});
  const [current,setCurrent]=useState(publication),[jobs,setJobs]=useState([]),[loading,setLoading]=useState(true),[submitting,setSubmitting]=useState(false),[error,setError]=useState(null),[notice,setNotice]=useState('');
  const mounted=useRef(false),statusRequest=useRef(null),postRequest=useRef(null),pendingPost=useRef(null);
  const refresh=useCallback(async()=>{
    if(statusRequest.current)return;
    const controller=new AbortController();statusRequest.current=controller;
    if(mounted.current)setLoading(true);
    try{
      const result=await sharedStatus({signal:controller.signal});
      if(mounted.current){setCurrent(result.current);setJobs(result.jobs);setError(null);}
    }catch(reason){if(mounted.current&&!controller.signal.aborted)setError(reason);}
    finally{if(statusRequest.current===controller){statusRequest.current=null;if(mounted.current)setLoading(false);}}
  },[]);
  useEffect(()=>{
    mounted.current=true;refresh();
    const visible=()=>{if(!document.hidden)refresh();};
    document.addEventListener('visibilitychange',visible);
    return()=>{mounted.current=false;statusRequest.current?.abort();statusRequest.current=null;postRequest.current?.abort();document.removeEventListener('visibilitychange',visible);};
  },[refresh]);
  const polling=pendingSharedJobs(jobs)||current?.configured&&current?.builtIn;
  useEffect(()=>{
    if(!polling)return;
    const timer=globalThis.setInterval(()=>{if(!document.hidden)refresh();},5000);
    return()=>globalThis.clearInterval(timer);
  },[polling,refresh]);
  const available=newerSharedPublication(publication,current,jobs);
  const configured=current?.configured===true,ready=configured&&Boolean(current?.revision),base=sharedBase(kind);
  function selectKind(value){
    setKind(value);setReference('auto');setPeriod(publishedMonth(catalog));setIntervalWindow(false);setWindow(suggestedSharedWindow(value,manifest));setNotice('');
  }
  async function submit(event){
    event.preventDefault();if(!ready||submitting)return;
    let plan;try{plan=buildSharedPlan({kind,mode,period:reference==='period'?period:'',interval,...window});}catch(reason){setError(reason);return;}
    const signature=JSON.stringify(plan);
    if(pendingPost.current?.signature!==signature)pendingPost.current={signature,key:newRequestKey()};
    const controller=new AbortController();postRequest.current=controller;setSubmitting(true);setError(null);setNotice('Enviando pedido…');
    try{
      const job=await submitSharedPlan(plan,pendingPost.current.key,{signal:controller.signal});
      pendingPost.current=null;
      if(mounted.current){setJobs(existing=>[job,...existing.filter(item=>item.id!==job.id)]);setNotice('');}
      await refresh();
    }catch(reason){if(mounted.current&&!controller.signal.aborted){setError(reason);setNotice('');}}
    finally{postRequest.current=null;if(mounted.current)setSubmitting(false);}
  }
  return <section className="tc-shared-updates" aria-labelledby="tc-shared-title">
    <div className="tc-shared-heading"><div><h2 id="tc-shared-title">Base compartilhada</h2><p className="tc-section-description">A atualização validada fica disponível para todos que usam o Toma Conta.</p></div><button type="button" className="tc-text-action" disabled={loading} onClick={refresh}>{loading?'Consultando…':'Consultar fila'}</button></div>
    {!configured&&!loading&&<p className="tc-operation-status">A atualização compartilhada está disponível no site publicado.</p>}
    {configured&&current.builtIn&&<p className="tc-operation-status" role="status">A base compartilhada aguarda a importação inicial. A versão publicada continua disponível.</p>}
    {available&&<div className="tc-shared-publication" role="status"><span>Uma nova base está disponível.</span><button type="button" className="tc-action tc-action-primary" onClick={()=>globalThis.location.reload()}>Carregar nova base</button></div>}
    <form onSubmit={submit}>
      <div className="tc-shared-controls"><label className="tc-field tc-shared-base">Base<select value={kind} onChange={event=>selectKind(event.target.value)} disabled={submitting}>{SHARED_BASES.map(source=><option value={source.kind} key={source.kind}>{source.label}</option>)}</select></label><button type="submit" className="tc-action tc-action-primary" disabled={!ready||loading||submitting}>{submitting?'Enviando…':'Atualizar para todos'}</button></div>
      <p className="tc-copy-context">Fonte: {base.source}{kind==='rede_agencias'?' · cadastro atual':''}</p>
      <details className="tc-shared-options"><summary>Opções de atualização</summary><div className="tc-shared-advanced"><label className="tc-field">Modo<select value={mode} onChange={event=>setMode(event.target.value)} disabled={submitting}><option value="incremental">Incremental</option><option value="overwrite">Reprocessar</option></select></label>
        {financialPlan(kind)&&<><label className="tc-field">Referência<select value={reference} onChange={event=>setReference(event.target.value)} disabled={submitting}><option value="auto">Últimos dados disponíveis</option><option value="period">Definir competência</option></select></label>{reference==='period'&&<label className="tc-field">Competência de referência<input type="month" value={period} onChange={event=>setPeriod(event.target.value)} disabled={submitting} required/></label>}</>}
        {!financialPlan(kind)&&kind!=='rede_agencias'&&<><label className="tc-field">Período<select value={interval?'interval':'auto'} onChange={event=>setIntervalWindow(event.target.value==='interval')} disabled={submitting}><option value="auto">Últimos dados disponíveis</option><option value="interval">Definir intervalo</option></select></label>{interval&&<><label className="tc-field">De<input type="month" value={window.start} onChange={event=>setWindow(value=>({...value,start:event.target.value}))} disabled={submitting} required/></label><label className="tc-field">Até<input type="month" value={window.end} onChange={event=>setWindow(value=>({...value,end:event.target.value}))} disabled={submitting} required/></label></>}</>}
      </div>{financialPlan(kind)&&<p className="tc-copy-context">{reference==='auto'?'Consulta as publicações disponíveis do BCB.':'A referência inicial é a competência da base em uso.'}</p>}</details>
    </form>
    {notice&&<p className="tc-operation-status" role="status" aria-live="polite">{notice}</p>}
    {error&&<div className="tc-shared-error" role="alert"><p>{error.message}</p><button type="button" className="tc-text-action" disabled={loading} onClick={refresh}>Consultar novamente</button>{error.detail&&<details><summary>Detalhes da consulta</summary><p>{error.detail}</p></details>}</div>}
    {(jobs.length>0||configured)&&<div className="tc-table-scroll tc-shared-job-list"><table className="tc-data-table tc-shared-jobs"><caption>Pedidos recentes</caption><thead><tr><th scope="col">Base</th><th scope="col">Pedido</th><th scope="col">Estado</th><th scope="col">Resultado</th></tr></thead><tbody>{jobs.slice(0,6).map(job=><tr key={job.id}><td><span>{sharedBase(job.kind).label}</span><small>{sharedBase(job.kind).source}</small></td><td><time dateTime={job.createdAt}>{updatedAt(job.createdAt)}</time>{job.params?.period&&<small>{job.params.period.slice(5)}/{job.params.period.slice(0,4)}</small>}</td><td><span className={job.status==='failed'||job.status==='needs_review'?'tc-shared-attention':''}>{sharedJobState(job)}</span>{job.status==='running'&&<div className="tc-shared-progress"><progress value={job.progress} max="1" aria-label={`Progresso de ${sharedBase(job.kind).label}`}/><span>{Math.round(job.progress*100)}%</span></div>}</td><td>{sharedJobOutcome(job)}{job.error&&<details className="tc-shared-job-error"><summary>Ver motivo</summary><p>{job.error}</p></details>}</td></tr>)}{!jobs.length&&<tr><td colSpan="4">{loading?'Consultando pedidos…':'Ainda não há pedidos de atualização.'}</td></tr>}</tbody></table></div>}
  </section>;
}
