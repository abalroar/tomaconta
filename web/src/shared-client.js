import {BASE} from './data.js';

export const SHARED_BASES=[
  {kind:'financeiro',label:'Instituições financeiras',source:'BCB · IF.data'},
  {kind:'individual',label:'Balanço e DRE · individual',source:'BCB · COSIF 4010'},
  {kind:'mercado_credito_sgs',label:'Crédito do SFN',source:'BCB · SGS',sourceId:'sfn'},
  {kind:'mercado_imobiliario',label:'Mercado imobiliário',source:'BCB · Olinda',sourceId:'imob'},
  {kind:'scr_data',label:'Crédito PF/PJ · Atlas e séries',source:'BCB · SCR.data',sourceId:'scr'},
  {kind:'spb_meios_pagamento',label:'Meios de pagamento',source:'BCB · Olinda / MPV',sourceId:'spb'},
  {kind:'rede_agencias',label:'Rede de agências',source:'BCB / IBGE'},
  {kind:'tudo',label:'Todas as bases',source:'BCB / IBGE'},
];
const API=`${BASE}api/shared`;
const ID=/^[a-f0-9]{32}$/;
const MONTH=/^20\d{2}-(0[1-9]|1[0-2])$/;
const FINANCIAL=new Set(['financeiro','individual','tudo']);
const STATES=new Set(['queued','running','succeeded','failed','needs_review']);
export const financialPlan=kind=>FINANCIAL.has(kind);
export const sharedBase=kind=>SHARED_BASES.find(base=>base.kind===kind)||{label:kind==='bootstrap'?'Importação inicial':'Atualização',source:'BCB'};
export const pendingSharedJobs=jobs=>jobs.some(job=>['queued','running'].includes(job.status));

export function publishedMonth(catalog){
  const value=catalog?.latestPeriod;
  const quarter=String(value||'').match(/^(20\d{2})-Q([1-4])$/);
  return quarter?`${quarter[1]}-${String(Number(quarter[2])*3).padStart(2,'0')}`:MONTH.test(String(value||'').slice(0,7))?value.slice(0,7):'';
}

export function suggestedSharedWindow(kind,manifest){
  const source=sharedBase(kind),end=manifest?.sources?.find(item=>item.id===source.sourceId)?.period?.slice(0,7);
  if(!MONTH.test(end||''))return {start:'',end:''};
  const [year,month]=end.split('-').map(Number);
  return {start:new Date(Date.UTC(year,month-12,1)).toISOString().slice(0,7),end};
}

export function buildSharedPlan({kind,mode='incremental',period='',interval=false,start='',end=''}){
  if(!SHARED_BASES.some(base=>base.kind===kind)||!['incremental','overwrite'].includes(mode))throw Error('Escolha uma base e um modo de atualização.');
  const plan={kind,mode};
  if(kind==='rede_agencias')return plan;
  if(financialPlan(kind)){
    if(period){
      if(!MONTH.test(period)||kind==='individual'&&!['03','06','09','12'].includes(period.slice(5)))throw Error('Escolha uma competência válida; a visão individual usa fim de trimestre.');
      plan.period=period;
    }
  }else if(interval){
    if(!MONTH.test(start)||!MONTH.test(end)||start>end)throw Error('Defina o início e o fim do intervalo.');
    const monthIndex=value=>Number(value.slice(0,4))*12+Number(value.slice(5));
    if(monthIndex(end)-monthIndex(start)>23)throw Error('Use um intervalo de até 24 meses.');
    plan.start=start;plan.end=end;
  }
  return plan;
}

export function newRequestKey(){
  return globalThis.crypto.randomUUID().replaceAll('-','');
}

export class SharedRequestError extends Error{
  constructor(message,{status=0,detail=''}={}){super(message);this.name='SharedRequestError';this.status=status;this.detail=detail;}
}

async function request(path,{method='GET',input,key,signal,fetchImpl=globalThis.fetch,timeoutMs=20000}={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
  const abort=()=>controller.abort();
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  try{
    const headers={Accept:'application/json'};
    if(input!==undefined)headers['Content-Type']='application/json';
    if(key)headers['Idempotency-Key']=key;
    let response;
    try{response=await fetchImpl(`${API}${path}`,{method,headers,body:input===undefined?undefined:JSON.stringify(input),cache:'no-store',credentials:'same-origin',signal:controller.signal});}
    catch(error){if(signal?.aborted)throw error;throw new SharedRequestError(method==='POST'?'O pedido não foi confirmado. Consulte a fila ou tente novamente.':'Não foi possível consultar a atualização. Tente novamente.',{detail:controller.signal.aborted?'Tempo de consulta esgotado.':'Falha de conexão.'});}
    let value;try{value=await response.json();}catch{throw new SharedRequestError('O serviço retornou uma resposta inválida. Tente novamente.',{status:response.status,detail:`HTTP ${response.status}`});}
    if(!response.ok)throw new SharedRequestError(response.status===429?'Há uma atualização recente ou a fila está cheia. Tente novamente em instantes.':response.status===400?value.error||'Confira o pedido de atualização.':'A atualização está indisponível neste momento. Tente novamente.',{status:response.status,detail:`HTTP ${response.status}${typeof value.error==='string'?` · ${value.error}`:''}`});
    return value;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}

function validJob(job){
  return job&&ID.test(job.id||'')&&STATES.has(job.status)&&typeof job.kind==='string'&&Number.isFinite(job.progress)&&job.progress>=0&&job.progress<=1;
}

/** Reads status only. It never pins a revision or touches dataset/engine caches. */
export async function sharedStatus(options={}){
  const current=await request('/current',options);
  if(!current||typeof current.configured!=='boolean'||typeof current.builtIn!=='boolean'||!(current.revision===null||ID.test(current.revision||''))||current.builtIn!==(current.revision===null)||current.revision&&!current.configured)throw new SharedRequestError('A publicação retornou um estado inválido. Tente novamente.');
  if(!current.configured)return {current,jobs:[]};
  const value=await request('/jobs',options);
  if(!Array.isArray(value?.jobs)||!value.jobs.every(validJob))throw new SharedRequestError('A fila retornou um estado inválido. Tente novamente.');
  return {current,jobs:value.jobs};
}

/** One POST per call. A caller may reuse the key after an uncertain response. */
export async function submitSharedPlan(plan,key,options={}){
  if(!ID.test(key||''))throw Error('O pedido de atualização perdeu sua identificação. Tente novamente.');
  const value=await request('/jobs',{...options,method:'POST',input:plan,key});
  if(!validJob(value?.job))throw new SharedRequestError('O pedido retornou uma resposta inválida. Consulte a fila antes de tentar novamente.');
  return value.job;
}

export function newerSharedPublication(publication,current,jobs=[]){
  if(current?.revision&&current.revision!==publication?.revision)return true;
  const publishedAt=Date.parse(publication?.publishedAt||'');
  return jobs.some(job=>job.status==='succeeded'&&ID.test(job.result?.revision||'')&&job.result.revision!==publication?.revision&&(!publication?.revision||Number.isFinite(publishedAt)&&Date.parse(job.updatedAt)>publishedAt));
}

export function sharedJobState(job){
  return {queued:'Na fila',running:'Em execução',succeeded:'Publicada',failed:'Falhou',needs_review:'Revisão necessária'}[job.status]||'Estado indisponível';
}

export function sharedJobOutcome(job){
  if(job.status==='succeeded')return 'Base validada e publicada.';
  if(job.status==='failed')return 'A base publicada foi preservada.';
  if(job.status==='needs_review')return 'A base foi preservada; há contas para revisão.';
  if(job.status==='queued')return 'Aguardando início.';
  const message=typeof job.message==='string'?job.message:'';
  return /parquet|oidc|engine|hash|atômic|cache|workflow|runner|sqlite|reserva|executor/i.test(message)?'Preparando a nova base.':message||'Atualização em andamento.';
}
