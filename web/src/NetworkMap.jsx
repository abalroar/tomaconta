import React,{useCallback,useEffect,useId,useMemo,useRef,useState} from 'react';
import {LocateFixed,MapPin,Maximize2,Minimize2,Minus,Plus,Search,X} from 'lucide-react';
import {datasetUrl,json,number} from './data.js';
import {groupName} from './landing-data.js';
import NetworkCanvas from './NetworkCanvas.jsx';
import {findNetworkMunicipalities,municipalityBanks,networkAnalysisBank,networkColor,networkName,networkPosition,networkSummary,validateNetwork} from './network-data.js';
import './network.css';

let networkCache=null,networkCacheKey=null;
async function loadNetwork(){
  const key=datasetUrl('data/bank-network.json');if(networkCacheKey!==key){networkCache=null;networkCacheKey=key;}
  if(!networkCache)networkCache=json('data/bank-network.json').then(validateNetwork).then(async data=>{
    if(!/^data\/bank-network-[a-z-]+\.geojson$/.test(data.geometry?.path||''))throw Error('A geografia da rede está indisponível.');
    const geometry=await json(data.geometry.path);return {data,geometry};
  }).catch(error=>{networkCache=null;throw error;});
  return networkCache;
}

function CitySearch({data,onSelect}){
  const id=useId(),root=useRef(null),[query,setQuery]=useState(''),[open,setOpen]=useState(false),[active,setActive]=useState(-1);
  const results=useMemo(()=>findNetworkMunicipalities(data,query),[data,query]);
  function choose(city,event){onSelect(city,!!event?.detail);setQuery('');setOpen(false);setActive(-1);}
  function keydown(event){
    if(event.key==='Escape'){setOpen(false);return;}
    if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();setOpen(true);setActive(current=>Math.max(0,Math.min(results.length-1,current+(event.key==='ArrowDown'?1:-1))));}
    if(event.key==='Enter'&&open&&results.length){event.preventDefault();choose(results[Math.max(0,active)]);}
  }
  return <div className="tc-network-city-search" ref={root} onBlur={event=>{if(!root.current?.contains(event.relatedTarget))setOpen(false);}}>
    <label><Search size={15} strokeWidth={1.6} aria-hidden="true"/><input role="combobox" aria-label="Buscar município no mapa" aria-autocomplete="list" aria-expanded={open&&!!query.trim()} aria-controls={`${id}-results`} aria-activedescendant={open&&active>=0&&results[active]?`${id}-${results[active].ibge}`:undefined} placeholder="Encontrar um município" autoComplete="off" spellCheck={false} value={query} onFocus={()=>setOpen(true)} onChange={event=>{setQuery(event.target.value);setOpen(true);setActive(-1);}} onKeyDown={keydown}/></label>
    {open&&query.trim()&&<div className="tc-network-city-results" role="listbox" id={`${id}-results`} aria-label="Municípios encontrados">{results.map((city,index)=><button type="button" role="option" aria-selected={active===index} id={`${id}-${city.ibge}`} key={city.ibge} onPointerMove={()=>setActive(index)} onClick={event=>choose(city,event)}><span>{city.name}</span><small>{city.uf}</small></button>)}{!results.length&&<p role="status">Município não encontrado.</p>}</div>}
  </div>;
}

function Place({data,city,selectedBank,catalog,onBank,onOpen,onClear,locked}){
  const [all,setAll]=useState(false);
  useEffect(()=>setAll(false),[city?.ibge]);
  if(!city)return null;
  const rows=municipalityBanks(data,city),shown=all?rows:rows.slice(0,5),selected=selectedBank?city.banks[selectedBank.idCnpjBase]||0:null,analysis=networkAnalysisBank(selectedBank,catalog);
  return <aside className={'tc-network-place'+(locked?' is-locked':'')} aria-label={`Agências em ${city.name}`}>
    <div className="tc-network-place-heading"><h3>{city.name}{' '}<span>{city.uf}</span></h3>{locked&&<button type="button" className="tc-network-close" aria-label="Limpar município selecionado" onClick={onClear}><X size={15}/></button>}</div>
    <p>{number(city.total,0)} {city.total===1?'agência':'agências'} · {rows.length} {rows.length===1?'banco':'bancos'}</p>
    {selectedBank&&<p className="tc-network-place-selection">{networkName(selectedBank)}: {number(selected,0)}</p>}
    {city.total===0?<p className="tc-network-place-empty">Nenhuma agência neste recorte do cadastro.</p>:<><div className="tc-network-place-banks">{shown.map(({bank,count})=>{
      return <div className="tc-network-place-bank" key={bank.idCnpjBase}><button type="button" onClick={()=>onBank(bank)} aria-pressed={selectedBank?.idCnpjBase===bank.idCnpjBase} title={bank.name}><span className="tc-network-bank-mark" style={{background:networkColor(bank)}}/><span>{networkName(bank)}</span><strong>{number(count,0)}</strong></button></div>;
    })}</div>{rows.length>5&&<button className="tc-network-show-all" type="button" onClick={()=>setAll(value=>!value)}>{all?'Recolher':`Ver os ${rows.length} bancos`}</button>}</>}
    {locked&&analysis&&<button className="tc-network-place-open" type="button" onClick={()=>onOpen(analysis)}>Analisar {groupName(analysis)}</button>}
    {(!Number.isFinite(city.lon)||!Number.isFinite(city.lat))&&<p className="tc-network-place-empty">Ponto geográfico indisponível.</p>}
  </aside>;
}

export default function NetworkMap({catalog,onOpen,onSelectBank,selectedAnalysisId}){
  const root=useRef(null),api=useRef(null),[packet,setPacket]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[selectedId,setSelectedId]=useState(null),[previewId,setPreviewId]=useState(null),[hoverCity,setHoverCity]=useState(null),[lockedCity,setLockedCity]=useState(null),[exclusive,setExclusive]=useState(false),[fullscreen,setFullscreen]=useState(false),[fullscreenAvailable,setFullscreenAvailable]=useState(false);
  useEffect(()=>{let active=true;setError('');loadNetwork().then(result=>{if(active)setPacket(result);}).catch(reason=>{if(active)setError(reason.message);});return()=>{active=false;};},[retry]);
  useEffect(()=>{setFullscreenAvailable(!!document.fullscreenEnabled);const change=()=>setFullscreen(document.fullscreenElement===root.current);document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change);},[]);
  const data=packet?.data,activeId=previewId||selectedId,selectedBank=data?.banks.find(bank=>bank.idCnpjBase===selectedId)||null,activeBank=data?.banks.find(bank=>bank.idCnpjBase===activeId)||null;
  const onHover=useCallback(city=>setHoverCity(city),[]),onPick=useCallback(city=>setLockedCity(city),[]);
  useEffect(()=>{if(!data||!selectedAnalysisId||data.banks.find(bank=>bank.idCnpjBase===selectedId)?.analysisLink?.analysisId===selectedAnalysisId)return;const matches=data.banks.filter(bank=>bank.analysisLink?.analysisId===selectedAnalysisId).sort((a,b)=>b.count-a.count||a.idCnpjBase.localeCompare(b.idCnpjBase));setSelectedId(matches[0]?.idCnpjBase||null);},[data,selectedAnalysisId]);
  const summary=useMemo(()=>data?networkSummary(data,activeId):null,[data,activeId]);
  function bankSelect(bank){setSelectedId(bank?.idCnpjBase||null);setPreviewId(null);setExclusive(false);const analysis=networkAnalysisBank(bank,catalog);if(analysis)onSelectBank?.(analysis);}
  function citySelect(city,animated=false){setLockedCity(city);setHoverCity(null);api.current?.focusCity(city,animated);}
  async function toggleFullscreen(){try{if(fullscreen)await document.exitFullscreen();else await root.current?.requestFullscreen();}catch{setFullscreenAvailable(false);}}
  const city=lockedCity||hoverCity,analysis=networkAnalysisBank(activeBank,catalog),showExclusive=exclusive&&!activeId,exclusiveCount=data?.municipalities.filter(city=>city.total>0&&Object.keys(city.banks).length===1).length||0;
  if(!packet)return <div className="tc-network-load" role={error?'alert':'status'}>{error?<><p>{error}</p><button type="button" onClick={()=>setRetry(value=>value+1)}>Tentar novamente</button></>:<p>Carregando a rede de agências…</p>}</div>;
  return <div className={'tc-network'+(fullscreen?' is-fullscreen':'')} ref={root}>
    <div className="tc-network-field">
      <p className="tc-network-mobile-summary">{showExclusive?`${number(exclusiveCount,0)} municípios com um banco`:`${number(summary.branches,0)} agências · ${number(summary.municipalities,0)} municípios`}</p>
      <NetworkCanvas {...{data}} geometry={packet.geometry} bankId={activeId} cityId={city?.ibge||null} exclusive={showExclusive} {...{onHover,onPick}} apiRef={api}/>
      <div className="tc-network-banks" onPointerLeave={()=>setPreviewId(null)}>
        <p className="tc-network-count">{showExclusive?number(exclusiveCount,0):number(summary.branches,0)}<span>{showExclusive?'municípios com um banco':'agências'}</span></p>
        {!showExclusive&&<p className="tc-network-reach">em {number(summary.municipalities,0)} municípios</p>}
        <div className="tc-network-main-banks" role="group" aria-label="Destacar rede de um banco"><button type="button" className={!selectedId&&!exclusive?'is-selected':''} aria-pressed={!selectedId&&!exclusive} onClick={()=>{setExclusive(false);bankSelect(null);}} onPointerEnter={()=>setPreviewId(null)}>Todos os bancos</button>{data.banks.slice(0,5).map(bank=><button type="button" key={bank.idCnpjBase} className={selectedId===bank.idCnpjBase?'is-selected':''} aria-pressed={selectedId===bank.idCnpjBase} onPointerEnter={event=>{if(event.pointerType==='mouse')setPreviewId(bank.idCnpjBase);}} onFocus={()=>{}} onClick={()=>bankSelect(bank)}><span className="tc-network-bank-mark" style={{background:networkColor(bank)}}/>{networkName(bank)}</button>)}</div>
        <label className="tc-network-more-banks"><span>Outros bancos</span><select aria-label="Escolher outro banco no mapa" value={selectedId&&data.banks.slice(5).some(bank=>bank.idCnpjBase===selectedId)?selectedId:''} onChange={event=>bankSelect(data.banks.find(bank=>bank.idCnpjBase===event.target.value))}><option value="">Escolher banco</option>{data.banks.slice(5).map(bank=><option key={bank.idCnpjBase} value={bank.idCnpjBase}>{networkName(bank)}</option>)}</select></label>
      </div>
      <div className="tc-network-top-tools"><CitySearch data={data} onSelect={citySelect}/></div>
      {city?<Place {...{data,city,catalog}} selectedBank={previewId?null:selectedBank} onBank={bankSelect} onOpen={onOpen} onClear={()=>setLockedCity(null)} locked={!!lockedCity}/>:<aside className="tc-network-reading">
        {showExclusive?<><h3>Uma instituição</h3><p>Municípios com agências de um único banco no cadastro.</p><button type="button" onClick={()=>setExclusive(false)}>Voltar à rede inteira</button></>:activeBank?<><h3>{networkName(activeBank)}</h3><p>{number(summary.branches,0)} agências em {number(summary.municipalities,0)} municípios.</p>{analysis&&activeId===selectedId&&<button type="button" className="tc-network-open" onClick={()=>onOpen(analysis)}>Analisar {groupName(analysis)}</button>}</>:<><p className="tc-network-concentration">BB, Caixa, Bradesco, Itaú e Santander reúnem <strong>{number(data.checks.fiveLargestSharePct,1)}%</strong> das agências.</p><button type="button" onClick={()=>{setSelectedId(null);setPreviewId(null);setExclusive(true);}}>Onde há um único banco</button></>}
      </aside>}
      <div className="tc-network-zoom" aria-label="Controles do mapa"><button type="button" onClick={event=>api.current?.zoomBy(1.6,!!event.detail)} aria-label="Aproximar mapa"><Plus size={18}/></button><button type="button" onClick={event=>api.current?.zoomBy(1/1.6,!!event.detail)} aria-label="Afastar mapa"><Minus size={18}/></button><button type="button" onClick={event=>api.current?.reset(!!event.detail)} aria-label="Voltar ao Brasil"><LocateFixed size={17}/></button>{fullscreenAvailable&&<button type="button" onClick={toggleFullscreen} aria-label={fullscreen?'Sair do mapa ampliado':'Ampliar mapa'}>{fullscreen?<Minimize2 size={17}/>:<Maximize2 size={17}/>}</button>}</div>
      <div className="tc-network-legend" aria-hidden="true"><span>Tamanho do ponto: agências</span><svg width="115" height="33" viewBox="0 0 115 33"><circle cx="10" cy="12" r="1.3"/><circle cx="45" cy="12" r="5.6"/><circle cx="94" cy="12" r="12.5"/><text x="10" y="32" textAnchor="middle">1</text><text x="45" y="32" textAnchor="middle">100</text><text x="94" y="32" textAnchor="middle">500</text></svg></div>
    </div>
    <footer className="tc-network-footer"><span><MapPin size={13} strokeWidth={1.7} aria-hidden="true"/> Pontos por município · {networkPosition(data.position)}</span><details><summary>Fonte: BCB / IBGE</summary><div><p>Agências de bancos múltiplos, comerciais e Caixa. Cada ponto representa um município; tamanho pela quantidade de agências. As coordenadas são pontos internos da geografia municipal do IBGE, sem localização de endereço.</p><p>Postos, correspondentes e cooperativas têm cadastros próprios. Os vínculos com conglomerados usam a competência informada no cadastro IF.data de cada ligação; a rede de agências está na posição de {networkPosition(data.position)}.</p><p>Um município sem agências neste recorte pode ter outras formas de atendimento. A rede atual não permite reconstruir fechamentos históricos.</p><p><a href="https://dadosabertos.bcb.gov.br/dataset/agencias" target="_blank" rel="noreferrer">Cadastro BCB</a><a href="https://servicodados.ibge.gov.br/api/docs/malhas?versao=4" target="_blank" rel="noreferrer">Geografia IBGE</a><a href={datasetUrl('data/bank-network.json')} download>Dados do mapa</a></p></div></details></footer>
  </div>;
}
