import React,{lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {currentDataRevision,json} from './data.js';
import Landing from './Landing.jsx';
import AppShell from './AppShell.jsx';
import {statementNavigationUrl} from './statement-data.js';
import {loadPublication} from './publication-data.js';
import {housingStorageKey} from './update-data.js';
import '@fontsource-variable/hanken-grotesk';
import './style.css';

const InstitutionPage=lazy(()=>import('./InstitutionPage.jsx'));
const SeriesPages=lazy(()=>import('./SeriesPages.jsx'));
const UpdatePage=lazy(()=>import('./UpdatePage.jsx'));
class SectionBoundary extends React.Component{
  state={error:false};
  static getDerivedStateFromError(){return {error:true};}
  render(){return this.state.error?<div className="tc-boot"><p>Não foi possível abrir esta seção.</p><button type="button" onClick={()=>location.reload()}>Recarregar</button></div>:this.props.children;}
}

const PAGES=new Set(['overview','institutions','sfn','imob','payments','update']);
const route=()=>{const query=new URLSearchParams(location.search);return {page:PAGES.has(query.get('view'))?query.get('view'):'overview',bank:query.get('bank')};};
function defaultBank(catalog,id){return catalog.institutions.find(bank=>bank.id===id)||catalog.institutions.find(bank=>bank.key==='ITAU PRUDENCIAL')||catalog.institutions[0];}

function App(){
  const [publication,setPublication]=useState(null),[publicationReady,setPublicationReady]=useState(false);
  const [page,setPage]=useState(route().page),[catalog,setCatalog]=useState(null),[manifest,setManifest]=useState(null),[sfn,setSfn]=useState([]),[extra,setExtra]=useState([]),[bankId,setBankId]=useState(''),[statements,setStatements]=useState(null),[error,setError]=useState('');
  const [uf,setUf]=useState('br'),[housing,setHousing]=useState({uf:'br',charts:[]}),[housingLoading,setHousingLoading]=useState(true),[housingError,setHousingError]=useState(''),[retry,setRetry]=useState(0),[housingRetry,setHousingRetry]=useState(0),[statementsRetry,setStatementsRetry]=useState(0);
  const activeUf=useRef(uf);activeUf.current=uf;

  useEffect(()=>{let active=true;const controller=new AbortController();setError('');setPublicationReady(false);
    async function load(){
      const published=await loadPublication({signal:controller.signal});if(!active)return;
      const [m,c,s,x]=await Promise.all([json('data/manifest.json'),json('data/institutions.json'),json('data/sfn.json'),json('data/extra.json')]);
      if(!active)return;const selected=defaultBank(c,route().bank);setPublication(published);setManifest(m);setCatalog(c);setSfn(s);setExtra(x);setBankId(selected.id);setPublicationReady(true);
      if(route().page==='institutions'&&route().bank&&route().bank!==selected.id){const url=new URL(location.href);url.searchParams.set('bank',selected.id);history.replaceState({},'',url);}
    }
    load().catch(reason=>{if(active)setError(reason.message);});
    return()=>{active=false;controller.abort();};
  },[retry]);

  useEffect(()=>{if(!publicationReady||!['institutions','update'].includes(page)||statements&&!statements.unavailable)return;let active=true;setStatements(null);json('data/statements/index.json').then(index=>{if(active)setStatements(index);}).catch(()=>{if(active)setStatements({unavailable:true,institutions:[]});});return()=>{active=false;};},[page,statementsRetry,publicationReady]);

  useEffect(()=>{if(!publicationReady)return;let active=true;setHousingLoading(true);setHousingError('');
    async function load(){
      try{
        let saved=null;try{saved=localStorage.getItem(housingStorageKey(uf,currentDataRevision()||'static-'+manifest.sourceCommit));}catch{}
        if(saved){try{const charts=JSON.parse(saved);if(Array.isArray(charts)&&charts.length&&charts.every(chart=>chart.id&&Array.isArray(chart.series))){if(active){setHousing({uf,charts});setHousingLoading(false);}return;}}catch{}}
        const charts=await json('data/imob-'+uf+'.json');if(active)setHousing({uf,charts});
      }catch(reason){if(active)setHousingError(reason.message);}finally{if(active)setHousingLoading(false);}
    }
    load();return()=>{active=false;};
  },[uf,housingRetry,publicationReady]);

  useEffect(()=>{function back(){const next=route();setPage(next.page);setError('');if(catalog)setBankId(defaultBank(catalog,next.bank).id);}globalThis.addEventListener('popstate',back);return()=>globalThis.removeEventListener('popstate',back);},[catalog]);

  function navigate(destination){
    const next=PAGES.has(destination)?destination:'overview';setPage(next);setError('');
    const url=new URL(location.href);url.searchParams.set('view',next);
    if(next==='institutions'&&bankId)url.searchParams.set('bank',bankId);
    else for(const key of ['bank','panel','period','history','statement','periods'])url.searchParams.delete(key);
    history.pushState({},'',url);globalThis.scrollTo({top:0});
  }
  function openInstitution(bank){
    setBankId(bank.id);setPage('institutions');setError('');
    const url=new URL(location.href);url.searchParams.set('view','institutions');url.searchParams.set('bank',bank.id);
    for(const key of ['panel','period','history','statement','periods'])url.searchParams.delete(key);
    history.pushState({},'',url);globalThis.scrollTo({top:0});
  }
  const selectStatementInstitution=useCallback((bank,entity,periods)=>{
    const actual=catalog?.institutions.find(entry=>entry.id===bank.id&&entry.perimeter==='Prudencial');
    if(!actual)return;
    const url=statementNavigationUrl(location.href,actual,entity,periods);
    setBankId(actual.id);setPage('institutions');setError('');
    history.replaceState({},'',url);
  },[catalog]);
  function updateHousing(charts,selectedUf){if(activeUf.current===(selectedUf||uf))setHousing({uf:selectedUf||uf,charts});}

  if(!manifest||!catalog)return <div className="tc-boot"><strong>Toma Conta.</strong><p role={error?'alert':'status'}>{error||'Carregando dados…'}</p>{error&&<button type="button" onClick={()=>setRetry(value=>value+1)}>Tentar novamente</button>}</div>;
  if(page==='overview')return <SectionBoundary key="overview"><Landing catalog={catalog} sfn={sfn} onNavigate={navigate} onOpenInstitution={openInstitution}/></SectionBoundary>;
  const imob=housing.uf===uf?housing.charts:[];
  return <AppShell page={page} onNavigate={navigate}>
    {error&&<div className="tc-app-error" role="alert"><span>{error}</span><button type="button" onClick={()=>setError('')}>Fechar</button></div>}
    <SectionBoundary key={page}><Suspense fallback={<div className="tc-boot"><p role="status">Carregando a seção…</p></div>}>
    {page==='institutions'&&<InstitutionPage {...{catalog,bankId}} onSelect={openInstitution} onStatementSelect={selectStatementInstitution} statementIndex={statements} onRetryStatements={()=>setStatementsRetry(value=>value+1)}/>}
    {['sfn','imob','payments'].includes(page)&&<>
      {page==='imob'&&housingError?<div className="tc-app-error" role="alert"><span>{housingError}</span><button type="button" onClick={()=>setHousingRetry(value=>value+1)}>Tentar novamente</button></div>:null}
      <SeriesPages key={page} {...{page,manifest,sfn,extra,imob,uf,setUf}} loading={housingLoading} onError={setError}/>
    </>}
    {page==='update'&&<UpdatePage {...{manifest,catalog,imob,uf,setUf,publication}} statementIndex={statements} onImobChange={updateHousing} onError={setError}/>}
    </Suspense></SectionBoundary>
  </AppShell>;
}

createRoot(document.getElementById('root')).render(<App/>);
