import React,{lazy,Suspense,useEffect,useId,useMemo,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,ChevronDown,Info,Menu,Pause,Play,X} from 'lucide-react';
import {BASE,currentDataRevision,json} from './data.js';
import {selectLandingCohort} from './landing-data.js';
import {APP_NAVIGATION} from './AppShell.jsx';
import InstitutionSearch from './InstitutionSearch.jsx';
import AtlasScene,{ATLAS_RATE_SCALE} from './AtlasScene.jsx';
import {makeCube,rate,percent,money,monthLabel,composition,productName} from './atlas-data.js';
import {loadAtlasAsset} from './atlas-publication.js';
import './atlas-landing.css';

const NetworkMap=lazy(()=>import('./NetworkMap.jsx'));
const packets=new Map();
function loadCredit(person){
  const key=(currentDataRevision()||'static')+':'+person;
  if(!packets.has(key))packets.set(key,Promise.all([loadAtlasAsset(`atlas-${person.toLowerCase()}.json`),json('data/bank-network-ufs.geojson')]).then(([packet,geo])=>({...packet,cube:makeCube(packet.source),geo})).catch(error=>{packets.delete(key);throw error;}));
  return packets.get(key);
}
const compactSegment=(text,kind)=>kind==='size'?text.replace('Porte ',''):text==='Sem rendimento'?'Sem renda':text==='Indisponível'?'N/D':text.replace(/^Mais de /,'').replace(/ salários? mínimos?/,'').replace(/ a /,'–').replace('Acima de 20','20+').replace('Até 1','Até 1');

function CreditAtlas({person,active}){
  const id=useId(),[packet,setPacket]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const [scene,setScene]=useState(0),[monthKey,setMonthKey]=useState(null),[uf,setUf]=useState(null),[playing,setPlaying]=useState(false),[motionRequested,setMotionRequested]=useState(false),[info,setInfo]=useState(false),[hoverPart,setHoverPart]=useState(null);
  const [filters,setFilters]=useState({PF:{segment:-1,product:-1,entered:false},PJ:{segment:-1,product:-1,entered:false}});
  const infoButton=useRef(null);
  useEffect(()=>{let live=true;setError('');setPlaying(false);loadCredit(person).then(value=>{if(live)setPacket({...value,person});}).catch(reason=>{if(live)setError(reason.message);});return()=>{live=false;};},[person,retry]);
  useEffect(()=>{if(!active)setPlaying(false);},[active]);
  useEffect(()=>{if(!info)return;const escape=event=>{if(event.key==='Escape'){setInfo(false);infoButton.current?.focus();}};document.addEventListener('keydown',escape);return()=>document.removeEventListener('keydown',escape);},[info]);
  const ready=packet?.person===person,cube=ready?packet.cube:null,ds=cube?.dims;
  const selectedFilter=filters[person],{segment,product}=selectedFilter;
  const month=ds?Math.max(0,monthKey===null?ds.months.length-1:ds.months.findLastIndex(value=>value<=monthKey)):0;
  const selected=ds?ds.ufs.findIndex(state=>state.uf===uf):-1;
  const series=useMemo(()=>cube?ds.months.map((_,m)=>ds.ufs.map((__,s)=>rate(cube.get(m,segment,product,s)))):[],[cube,segment,product]);
  const parts=useMemo(()=>cube?composition(cube,month,segment,selected):[],[cube,month,segment,selected]);
  function updateFilter(change){setFilters(previous=>({...previous,[person]:{...previous[person],...change}}));setMotionRequested(true);setPlaying(false);}
  function changeScene(next,manual=true){
    const value=(next+3)%3;setScene(value);setPlaying(false);setMotionRequested(manual);setHoverPart(null);
    if(value>0&&!selectedFilter.entered){const first=person==='PF'?ds.segments.findIndex(text=>/10 a 20/.test(text)):-1;setFilters(previous=>({...previous,[person]:{...previous[person],entered:true,segment:first>=0?first:previous[person].segment}}));}
  }
  if(!ready||error)return <section className="atlas-load" aria-label="Crédito" role={error?'alert':'status'}>{error?<><p>{error}</p><button onClick={()=>setRetry(value=>value+1)}>Tentar novamente</button></>:<p>Carregando crédito {person}…</p>}</section>;
  const pair=cube.get(month,segment,product,selected),value=rate(pair),national=rate(cube.get(month,segment,product));
  const scope=segment<0?(person==='PF'?'Todas as rendas':'Todos os portes'):ds.segments[segment];
  const currentProduct=product<0?'Carteira de crédito':productName(ds.products[product],person);
  const focusPart=parts[hoverPart??(product>=0?product:parts.findIndex(part=>/Rural/i.test(part.name)))];
  const scenes=['Brasil',person==='PF'?'Renda':'Porte','Modalidades'];
  const highlights=scene>0&&selected<0?['AM','SP'].map((state,i)=>({index:ds.ufs.findIndex(v=>v.uf===state),color:i?'#ec7000':'#315f78'})):[];
  return <section className="atlas-credit" aria-label={`Crédito de pessoas ${person==='PF'?'físicas':'jurídicas'}`} data-motion={motionRequested?'requested':'default'}>
    <div className="atlas-stage">
      <div className="atlas-heading"><div><div className="atlas-product"><h1>{currentProduct}</h1><ChevronDown size={17}/><select aria-label="Modalidade de crédito" value={product} onChange={event=>updateFilter({product:+event.target.value})}><option value={-1}>Carteira {person} completa</option>{parts.map(part=><option key={part.index} value={part.index}>{part.name} · {percent(part.share)} da carteira</option>)}</select></div><div className="atlas-location"><span>{selected<0?'Brasil':ds.ufs[selected].name}</span><ChevronDown size={12}/><select aria-label="Estado do tomador" value={uf||''} onChange={event=>{setUf(event.target.value||null);setMotionRequested(true);setPlaying(false);}}><option value="">Brasil</option>{ds.ufs.map(state=><option key={state.uf} value={state.uf}>{state.name}</option>)}</select>{selected>=0&&<button aria-label="Limpar estado selecionado" onClick={()=>setUf(null)}><X size={15}/></button>}</div><div className="atlas-scope">{scope}</div></div>
        <div className="atlas-reading"><strong aria-live={playing?'off':'polite'}>{percent(value)}</strong><span>Inadimplência</span>{selected>=0&&<small>Brasil: {percent(national)}</small>}</div>
      </div>
      <AtlasScene geo={packet.geo} states={ds.ufs} series={series} month={month} layout={scene===0?'map':'distribution'} selected={selected} highlights={highlights} playing={playing&&active} onSelect={index=>setUf(index<0?null:ds.ufs[index].uf)} onMonthChange={index=>setMonthKey(ds.months[index])} onPlayingChange={setPlaying} motionRequested={motionRequested}/>
      <div className="atlas-context">{scene===0?<div className="atlas-rate-legend" aria-label="Inadimplência, escala fixa em percentual">{ATLAS_RATE_SCALE.map((item,index)=><span key={item.min}><i style={{background:item.color}}/>{item.min}{index===5?'%+':''}</span>)}</div>:<span>UFs</span>}<span>Carteira: {money(pair?.[1])}</span></div>
    </div>
    {(scene>0||selectedFilter.entered)&&<div className="atlas-direct-controls">
      <div className="atlas-segment-control"><label htmlFor={id+'-segment'}>{person==='PF'?'Renda mensal':'Porte da empresa'}<span>{person==='PF'?'salários mínimos':''}</span></label><input id={id+'-segment'} aria-label={person==='PF'?'Faixa de renda':'Porte da empresa'} type="range" min={-1} max={ds.segments.length-1} value={segment} step={1} aria-valuetext={scope} onChange={event=>updateFilter({segment:+event.target.value})}/><div className="atlas-segment-ticks">{[-1,...ds.segments.keys()].map(index=><button key={index} aria-label={index<0?(person==='PF'?'Todas as rendas':'Todos os portes'):ds.segments[index]} aria-pressed={segment===index} onClick={()=>updateFilter({segment:index})}>{index<0?'Todas':compactSegment(ds.segments[index],ds.segmentKind)}</button>)}</div></div>
      {scene===2&&<div className="atlas-composition"><div className="atlas-composition-label"><span>{product>=0?person+' total: '+money(cube.get(month,segment,-1,selected)?.[1]):'Participação por modalidade'}</span><span>{focusPart&&<><i style={{background:focusPart.color}}/>{focusPart.short} {percent(focusPart.share)}</>}</span>{product>=0&&<button onClick={()=>updateFilter({product:-1})}>Todas</button>}</div><div className="atlas-composition-strip" role="group" aria-label="Participação por modalidade">{parts.map((part,index)=><button key={part.index} disabled={part.share===null||part.share===0} style={{transform:`translateX(${parts.slice(0,index).reduce((sum,p)=>sum+(p.share??0),0)}%) scaleX(${(part.share??0)/100})`,background:part.color,opacity:product<0||product===part.index?1:.25}} aria-pressed={product===part.index} aria-label={`${part.name}: ${percent(part.share)} da carteira. Selecionar modalidade`} title={`${part.name} · ${percent(part.share)}`} onClick={()=>updateFilter({product:product===part.index?-1:part.index})} onFocus={()=>setHoverPart(index)} onBlur={()=>setHoverPart(null)} onPointerEnter={()=>setHoverPart(index)} onPointerLeave={()=>setHoverPart(null)}/>)}</div></div>}
    </div>}
    <div className="atlas-bottom-controls"><div className="atlas-time"><button className="atlas-play" onClick={()=>{setMotionRequested(true);setPlaying(previous=>!previous);}} aria-label={playing?'Pausar animação':'Reproduzir animação'}>{playing?<Pause size={17}/>:<Play size={17}/>}</button><input aria-label="Competência do crédito" type="range" min={0} max={ds.months.length-1} step={1} value={month} aria-valuetext={monthLabel(ds.months[month])} onChange={event=>{setMonthKey(ds.months[+event.target.value]);setMotionRequested(true);setPlaying(false);}}/><time aria-live={playing?'off':'polite'}>{monthLabel(ds.months[month])}</time></div>
      <nav className="atlas-story-nav" aria-label="Exploração do crédito"><div role="tablist" aria-label="Cenas do crédito">{scenes.map((label,index)=><button key={index} id={id+'-scene-'+index} role="tab" aria-selected={scene===index} tabIndex={scene===index?0:-1} onClick={event=>changeScene(index,!!event.detail)} onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;changeScene(next,false);document.getElementById(id+'-scene-'+next)?.focus();}}}>{label}</button>)}</div><div className="atlas-arrows"><button aria-label="Cena anterior" onClick={event=>changeScene(scene-1,!!event.detail)}><ArrowLeft size={21}/></button><button aria-label="Próxima cena" onClick={event=>changeScene(scene+1,!!event.detail)}><ArrowRight size={23}/></button></div></nav>
    </div>
    <div className="atlas-source"><a href="https://www.bcb.gov.br/estabilidadefinanceira/scrdata" target="_blank" rel="noreferrer">BCB / SCR.data</a><button ref={infoButton} aria-label="Sobre os dados de crédito" aria-expanded={info} aria-controls={id+'-info'} onClick={()=>setInfo(previous=>!previous)}><Info size={15}/></button></div>
    {info&&<aside className="atlas-data-info" id={id+'-info'} aria-label="Sobre os dados de crédito"><button aria-label="Fechar informações" onClick={()=>{setInfo(false);infoButton.current?.focus();}}><X size={17}/></button><p>Saldo das operações com alguma parcela vencida há mais de 90 dias / carteira ativa. {person==='PF'?'Pessoas físicas; UF da residência do tomador.':'Pessoas jurídicas; UF informada para o tomador.'}</p><p>{monthLabel(ds.months[0])} a {monthLabel(ds.months.at(-1))}. Números e competências observados; o movimento entre pontos é uma transição visual. Ausências são N/D.</p><p>A participação por modalidade usa a carteira completa do recorte como denominador. {person==='PF'?'As faixas usam a renda informada em cada competência.':'Os portes seguem a classificação do BCB. As modalidades indicadas como “classificação PF” também constam no recorte PJ da fonte, conforme a nota 1 do de-para.'}</p>{packet.builtIn&&currentDataRevision()&&<p>Série distribuída com esta versão do site. A atualização compartilhada de SCR passa a publicar estes recortes na mesma revisão.</p>}<a href="https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf" target="_blank" rel="noreferrer">Metodologia BCB</a></aside>}
  </section>;
}

export default function AtlasLanding({catalog,onNavigate,onOpenInstitution}){
  const [mode,setMode]=useState(()=>new URLSearchParams(location.search).get('scene')==='map'?'agencies':'credit'),[visitedAgencies,setVisitedAgencies]=useState(mode==='agencies'),[person,setPerson]=useState('PF'),[menu,setMenu]=useState(false);
  const suggestions=useMemo(()=>selectLandingCohort(catalog,6),[catalog]);
  function navigate(event,page){if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();setMenu(false);onNavigate(page);}
  function selectMode(next){setMode(next);if(next==='agencies')setVisitedAgencies(true);const url=new URL(location.href);url.searchParams.set('scene',next==='agencies'?'map':'credit');history.replaceState({},'',url);}
  return <div className="atlas-landing"><div className="atlas-shell">
    <header className="atlas-site-header"><a className="atlas-wordmark" href={BASE} onClick={event=>navigate(event,'overview')}>Atlas <span>SFN</span></a><button className="atlas-menu" aria-label="Menu" aria-expanded={menu} aria-controls="atlas-main-nav" onClick={()=>setMenu(previous=>!previous)}><Menu size={22}/></button><nav id="atlas-main-nav" className={menu?'is-open':''} aria-label="Navegação principal">{APP_NAVIGATION.map(([key,label])=><a key={key} href={`${BASE}?view=${key}`} onClick={event=>navigate(event,key)}>{label}</a>)}</nav></header>
    <div className="atlas-tools"><div className="atlas-view-switch" role="group" aria-label="Mapas do Atlas"><button aria-pressed={mode==='credit'} onClick={()=>selectMode('credit')}>Crédito</button><button aria-pressed={mode==='agencies'} onClick={()=>selectMode('agencies')}>Agências</button></div>{mode==='credit'&&<div className="atlas-person-switch" role="group" aria-label="Tipo de cliente"><button aria-pressed={person==='PF'} onClick={()=>setPerson('PF')}>Pessoas físicas</button><button aria-pressed={person==='PJ'} onClick={()=>setPerson('PJ')}>Pessoas jurídicas</button></div>}<InstitutionSearch {...{catalog}} suggested={suggestions} onSelect={onOpenInstitution} placeholder="Instituição" label="Buscar instituição"/></div>
    <main className="atlas-main"><div hidden={mode!=='credit'}><CreditAtlas person={person} active={mode==='credit'}/></div>{visitedAgencies&&<section className="atlas-agencies" hidden={mode!=='agencies'} aria-label="Agências bancárias"><h1>Agências</h1><Suspense fallback={<div className="atlas-load" role="status">Carregando a rede de agências…</div>}><NetworkMap {...{catalog}} onOpen={onOpenInstitution}/></Suspense></section>}</main>
    <footer className="atlas-site-footer"><span>Atlas do Sistema Financeiro Brasileiro</span><a href="https://matheusprat.es">matheusprat.es</a></footer>
  </div></div>;
}
