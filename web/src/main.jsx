import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {json} from './data.js';
import Landing from './Landing.jsx';
import AppShell from './AppShell.jsx';
import InstitutionPage from './InstitutionPage.jsx';
import SeriesPages from './SeriesPages.jsx';
import UpdatePage from './UpdatePage.jsx';
import '@fontsource-variable/hanken-grotesk';
import './style.css';

const PAGES=new Set(['overview','institutions','sfn','imob','payments','update']);
const route=()=>{const query=new URLSearchParams(location.search);return {page:PAGES.has(query.get('view'))?query.get('view'):'overview',bank:query.get('bank')};};
function defaultBank(catalog,id){return catalog.institutions.find(bank=>bank.id===id)||catalog.institutions.find(bank=>bank.key==='ITAU PRUDENCIAL')||catalog.institutions[0];}

function App(){
  const [page,setPage]=useState(route().page),[catalog,setCatalog]=useState(null),[manifest,setManifest]=useState(null),[sfn,setSfn]=useState([]),[extra,setExtra]=useState([]),[bankId,setBankId]=useState(''),[statements,setStatements]=useState(null),[error,setError]=useState('');
  const [uf,setUf]=useState('br'),[housing,setHousing]=useState({uf:'br',charts:[]}),[housingLoading,setHousingLoading]=useState(true),[housingError,setHousingError]=useState(''),[retry,setRetry]=useState(0),[housingRetry,setHousingRetry]=useState(0),[statementsRetry,setStatementsRetry]=useState(0);
  const activeUf=useRef(uf);activeUf.current=uf;

  useEffect(()=>{let active=true;setError('');
    Promise.all([json('data/manifest.json'),json('data/institutions.json'),json('data/sfn.json'),json('data/extra.json')]).then(([m,c,s,x])=>{
      if(!active)return;const selected=defaultBank(c,route().bank);setManifest(m);setCatalog(c);setSfn(s);setExtra(x);setBankId(selected.id);
      if(route().page==='institutions'&&route().bank&&route().bank!==selected.id){const url=new URL(location.href);url.searchParams.set('bank',selected.id);history.replaceState({},'',url);}
    }).catch(reason=>{if(active)setError(reason.message);});
    return()=>{active=false;};
  },[retry]);

  useEffect(()=>{if(!['institutions','update'].includes(page)||statements&&!statements.unavailable)return;let active=true;setStatements(null);json('data/statements/index.json').then(index=>{if(active)setStatements(index);}).catch(()=>{if(active)setStatements({unavailable:true,institutions:[]});});return()=>{active=false;};},[page,statementsRetry]);

  useEffect(()=>{let active=true;setHousingLoading(true);setHousingError('');
    async function load(){
      try{
        let saved=null;try{saved=localStorage.getItem('tomaconta-imob-'+uf);}catch{}
        if(saved){try{const charts=JSON.parse(saved);if(Array.isArray(charts)&&charts.length&&charts.every(chart=>chart.id&&Array.isArray(chart.series))){if(active){setHousing({uf,charts});setHousingLoading(false);}return;}}catch{}}
        const charts=await json('data/imob-'+uf+'.json');if(active)setHousing({uf,charts});
      }catch(reason){if(active)setHousingError(reason.message);}finally{if(active)setHousingLoading(false);}
    }
    load();return()=>{active=false;};
  },[uf,housingRetry]);

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
  function updateHousing(charts,selectedUf){if(activeUf.current===(selectedUf||uf))setHousing({uf:selectedUf||uf,charts});}

  if(!manifest||!catalog)return <div className="tc-boot"><strong>Toma Conta.</strong><p role={error?'alert':'status'}>{error||'Carregando dados…'}</p>{error&&<button type="button" onClick={()=>setRetry(value=>value+1)}>Tentar novamente</button>}</div>;
  if(page==='overview')return <Landing catalog={catalog} sfn={sfn} onNavigate={navigate} onOpenInstitution={openInstitution}/>;
  const imob=housing.uf===uf?housing.charts:[];
  return <AppShell page={page} onNavigate={navigate}>
    {error&&<div className="tc-app-error" role="alert"><span>{error}</span><button type="button" onClick={()=>setError('')}>Fechar</button></div>}
    {page==='institutions'&&<InstitutionPage {...{catalog,bankId}} onSelect={openInstitution} statementIndex={statements} onRetryStatements={()=>setStatementsRetry(value=>value+1)}/>}
    {['sfn','imob','payments'].includes(page)&&<>
      {page==='imob'&&housingError?<div className="tc-app-error" role="alert"><span>{housingError}</span><button type="button" onClick={()=>setHousingRetry(value=>value+1)}>Tentar novamente</button></div>:null}
      <SeriesPages key={page} {...{page,manifest,sfn,extra,imob,uf,setUf}} loading={housingLoading} onError={setError}/>
    </>}
    {page==='update'&&<UpdatePage {...{manifest,catalog,imob,uf,setUf}} statementIndex={statements} onImobChange={updateHousing} onError={setError}/>}
  </AppShell>;
}

createRoot(document.getElementById('root')).render(<App/>);
