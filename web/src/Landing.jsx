import React,{lazy,Suspense,useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,Menu,Pause,Play} from 'lucide-react';
import {BASE,json,number} from './data.js';
import InstitutionSearch from './InstitutionSearch.jsx';
import {selectLandingCohort,groupName,groupColor,creditTotalFromCharts,buildRoeRace} from './landing-data.js';
import {tabNavigation} from './tab-navigation.js';
import './landing.css';
import './explorer.css';

const NetworkMap=lazy(()=>import('./NetworkMap.jsx'));
const SCENES=[['map','Agências'],['race','Rentabilidade'],['size','Porte'],['credit','Crédito']];

const months=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
const dateLabel=date=>`${months[+date.slice(5,7)-1]}/${date.slice(0,4)}`;
const periodLabel=period=>{const [year,q]=String(period||'').split('-Q');return q?`${months[+q*3-1]}/${year}`:period||'N/D';};
const money=value=>value==null?'N/D':`R$ ${number(value/1e9,1)} bi`;
const historyCache=new Map();
function bankHistory(bank){if(!historyCache.has(bank.historyPath))historyCache.set(bank.historyPath,json(bank.historyPath).catch(error=>{historyCache.delete(bank.historyPath);throw error;}));return historyCache.get(bank.historyPath);}
function useChartWidth(){const ref=useRef(null),[width,setWidth]=useState(0);useEffect(()=>{if(!ref.current)return;const observer=new ResizeObserver(entries=>setWidth(Math.round(entries[0].contentRect.width)));observer.observe(ref.current);return()=>observer.disconnect();},[]);return [ref,width];}
function Source({children,sgs=false}){return <details className="tc-source"><summary>Fonte: BCB / {sgs?'SGS':'IFData'}</summary><div>{children}<a href={sgs?'https://www.bcb.gov.br/estatisticas/estatisticasmonetariascredito':'https://www3.bcb.gov.br/ifdata/'} target="_blank" rel="noreferrer">Consultar a fonte</a></div></details>;}

function Credit({chart}){
  const [ref,width]=useChartWidth(),[focused,setFocused]=useState(null),[announcement,setAnnouncement]=useState(''),points=chart?.series?.[0]?.data||[],valid=points.filter(p=>p[1]!=null);
  if(!valid.length)return <div ref={ref} className="tc-credit-chart"><p className="tc-empty">Série de crédito indisponível.</p></div>;
  const w=width||600,h=350,p={left:36,right:18,top:38,bottom:35},first=valid[0],last=valid.at(-1),focus=focused==null?null:points[focused];
  const t0=Date.parse(first[0]),t1=Date.parse(last[0]),top=Math.max(2,Math.ceil(Math.max(...valid.map(p=>p[1]))/1000/2)*2);
  const x=date=>p.left+(Date.parse(date)-t0)/(t1-t0||1)*(w-p.left-p.right),y=value=>h-p.bottom-value/1000/top*(h-p.top-p.bottom);
  const segments=[];let segment=[];
  points.forEach(point=>{if(point[1]==null){if(segment.length)segments.push(segment);segment=[];}else segment.push(point);});if(segment.length)segments.push(segment);
  function inspect(event){const box=event.currentTarget.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,((event.clientX-box.left)/box.width*w-p.left)/(w-p.left-p.right))),time=t0+ratio*(t1-t0);let closest=0,distance=Infinity;points.forEach((point,index)=>{const gap=Math.abs(Date.parse(point[0])-time);if(gap<distance){distance=gap;closest=index;}});setFocused(closest);}
  function keyboard(event){if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;event.preventDefault();if(event.key==='Escape'){setFocused(null);return;}const index=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,(focused??points.length-1)+(event.key==='ArrowLeft'?-1:1)));setFocused(index);setAnnouncement(`${dateLabel(points[index][0])}: ${points[index][1]==null?'N/D':number(points[index][1]/1000,2)+' trilhões de reais'}`);}
  return <div ref={ref} className="tc-credit-chart">{width>0&&<svg viewBox={`0 0 ${w} ${h}`} role="img" tabIndex={0} onPointerMove={inspect} onPointerLeave={()=>setFocused(null)} onKeyDown={keyboard} aria-label={`Crédito do SFN: R$ ${number(first[1]/1000,2)} trilhões em ${dateLabel(first[0])} e R$ ${number(last[1]/1000,2)} trilhões em ${dateLabel(last[0])}, em valores nominais. Setas percorrem os meses.`}>
    <title>Saldo de crédito do SFN · R$ trilhões nominais</title>
    {Array.from({length:5},(_,i)=>top*i/4).map(value=><g key={value}><line className="tc-grid" x1={p.left} x2={w-p.right} y1={y(value*1000)} y2={y(value*1000)}/><text x={p.left-8} y={y(value*1000)+4} textAnchor="end">{number(value,Number.isInteger(value)?0:1)}</text></g>)}
    {segments.map((points,i)=>{const d=points.map(([date,value],j)=>`${j?'L':'M'}${x(date)},${y(value)}`).join(' ');return <g key={i}><path className="tc-credit-area" d={`${d} L${x(points.at(-1)[0])},${h-p.bottom} L${x(points[0][0])},${h-p.bottom} Z`}/><path className="tc-series-line" d={d}/></g>;})}
    <circle className="tc-series-point" cx={x(last[0])} cy={y(last[1])} r={4}/>{focus?<g><line className="tc-credit-inspector" x1={x(focus[0])} x2={x(focus[0])} y1={p.top} y2={h-p.bottom}/>{focus[1]!=null&&<circle className="tc-series-point" cx={x(focus[0])} cy={y(focus[1])} r={5}/>}<text className="tc-credit-inspector-value" x={Math.max(p.left+4,Math.min(w-p.right-4,x(focus[0])))} y={p.top-13} textAnchor={x(focus[0])>w/2?'end':'start'}>{dateLabel(focus[0])} · {focus[1]==null?'N/D':number(focus[1]/1000,2)}</text></g>:<text className="tc-final-value" x={w-p.right} y={y(last[1])-13} textAnchor="end">{number(last[1]/1000,2)}</text>}
    <text x={p.left} y={h-7}>{dateLabel(first[0])}</text><text x={w-p.right} y={h-7} textAnchor="end">{dateLabel(last[0])}</text>
  </svg>}<span className="tc-sr" role="status" aria-live="polite">{announcement}</span></div>;
}

function Slope({cohort,onChoose,tall=false}){
  const [ref,width]=useChartWidth(),[focused,setFocused]=useState(null);
  const ordered=useMemo(()=>cohort.filter(b=>b.latest.roe!=null).slice().sort((a,b)=>b.latest.roe-a.latest.roe||b.latest.assets-a.latest.assets),[cohort]);
  const ranks=new Map(ordered.map((bank,index)=>[bank.id,index]));
  const w=width||800,h=tall?400:286,narrow=w<470,lx=narrow?104:174,rx=w-(narrow?104:174),y=index=>(tall?60:49)+index*(tall?33:22);
  const short={'Banco do Brasil':'BB','Nu Pagamentos':'Nu','BTG Pactual':'BTG','Santander':'Sant.'};
  return <div ref={ref} className={`tc-slope-chart${focused?' has-focus':''}`}>
    {width>0&&<svg viewBox={`0 0 ${w} ${h}`} aria-label="Posições por ativos e ROE entre os dez maiores por ativos">
      <title>Ativos e ROE</title><text className="tc-slope-label tc-column-label" x={0} y={17}>Ativos{!narrow?' · R$ bi':''}</text><text className="tc-slope-label tc-column-label" x={w} y={17} textAnchor="end">ROE · %</text>
      {cohort.map((bank,index)=>{
        const name=groupName(bank),label=narrow?(short[name]||name):name,left=y(index),right=y(ranks.get(bank.id)??cohort.length),hasRoe=ranks.has(bank.id);
        const d=`M${lx},${left} C${w*.45},${left} ${w*.55},${right} ${rx},${right}`;
        return <a key={bank.id} href="#institution" className={`tc-slope-link${focused===bank.id?' is-focus':''}`} style={{'--bank-color':groupColor(bank)}}
          aria-label={`${name}: ${index+1}º por ativos, ${hasRoe?`${ranks.get(bank.id)+1}º por ROE, ${number(bank.latest.roe,1)}%`:'ROE N/D'}. Abrir instituição.`}
          onPointerEnter={()=>setFocused(bank.id)} onPointerLeave={event=>{if(!event.currentTarget.matches(':focus-visible'))setFocused(null);}}
          onFocus={()=>setFocused(bank.id)} onBlur={()=>setFocused(null)} onClick={event=>{event.preventDefault();onChoose(bank);}}>
          {hasRoe&&<><path className="tc-slope-path" d={d}/><path className="tc-slope-hit" d={d}/><circle className="tc-slope-dot" cx={rx} cy={right} r={3}/></>}
          <circle className="tc-slope-dot" cx={lx} cy={left} r={3}/><text className="tc-slope-label" x={0} y={left+4}>{index+1}. {label}</text>
          {!narrow&&<text className="tc-slope-value" x={lx-8} y={left+4} textAnchor="end">{number(bank.latest.assets/1e9,0)}</text>}
          {hasRoe&&<><text className="tc-slope-label" x={rx+8} y={right+4}>{label}</text><text className="tc-slope-value" x={w} y={right+4} textAnchor="end">{number(bank.latest.roe,1)}</text></>}
        </a>;
      })}
    </svg>}
  </div>;
}

function Race({cohort,race,onChoose,failed=false,embedded=false}){
  const plotRef=useRef(null),sectionRef=useRef(null),yearRef=useRef(null),quarterRef=useRef(null),progressRef=useRef(null),liveRef=useRef(null),nodes=useRef({}),control=useRef(null);
  const [phase,setPhase]=useState('paused');
  const lo=Math.min(0,Math.floor((race?.minRoe??0)/10)*10),hi=Math.max(10,Math.ceil((race?.maxRoe??70)/10)*10),span=hi-lo,zero=-lo/span*100;
  useEffect(()=>{
    if(!race?.periods?.length||race.periods.length<2)return;
    const periods=race.periods,frames=race.frames.map(frame=>frame.values),format=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
    let position=0,raf=0,lastClock=null,playing=false,finished=false,settling=false,inView=false,currentVisual=null,visibleQuarter=-1;
    const reduce=globalThis.matchMedia('(prefers-reduced-motion: reduce)');let manuallyPaused=reduce.matches;
    const clamp=t=>Math.max(0,Math.min(1,t)),smooth=t=>{t=clamp(t);return t*t*(3-2*t);};
    function at(pos){
      const i=Math.min(periods.length-2,Math.floor(pos)),t=pos-i,a=frames[i],b=frames[i+1],values=a.map((v,j)=>v+(b[j]-v)*t);
      const lanes=cohort.map((bank,j)=>{let rank=0;cohort.forEach((other,k)=>{if(j===k)return;const tie=(j-k)*1e-9,d0=a[k]-a[j]+tie,d1=b[k]-b[j]+tie;if((d0>0)===(d1>0)){rank+=d0>0?1:0;return;}const cross=clamp(-d0/(d1-d0)),start=Math.max(0,cross-.14),end=Math.min(1,cross+.14);rank+=(d0>0?1:0)+(d1>0?1:-1)*smooth((t-start)/(end-start||1));});return rank;});
      return {values,lanes};
    }
    function paint(view){
      currentVisual=view;const ordered=cohort.map((_,j)=>j).sort((a,b)=>view.values[b]-view.values[a]||a-b),rank=new Map(ordered.map((j,i)=>[j,i+1]));
      cohort.forEach((bank,j)=>{const node=nodes.current[bank.id],value=view.values[j],start=(Math.min(0,value)-lo)/span*100;if(!node?.row)return;
        node.row.style.transform=`translateY(calc(${view.lanes[j].toFixed(5)} * var(--race-row-height)))`;node.row.style.zIndex=String(cohort.length+2-rank.get(j));
        node.bar.style.transform=`translateX(${start.toFixed(5)}%) scaleX(${Math.abs(value)/span})`;node.rank.textContent=String(rank.get(j));const label=format.format(value)+'%';if(node.value.textContent!==label)node.value.textContent=label;
      });
    }
    function paintDate(){const index=Math.min(periods.length-1,Math.floor(position));if(index!==visibleQuarter){visibleQuarter=index;yearRef.current.textContent=periods[index].slice(0,4);quarterRef.current.textContent=`${periods[index].slice(-1)}º trimestre`;cohort.forEach((bank,j)=>nodes.current[bank.id].row.setAttribute('aria-label',`${groupName(bank)}: ROE ${format.format(frames[index][j])}%, ${periodLabel(periods[index])}. Abrir instituição.`));}progressRef.current.style.transform=`scaleX(${position/(periods.length-1)})`;}
    function cancel(){if(raf)cancelAnimationFrame(raf);raf=0;lastClock=null;settling=false;}
    function phaseTo(value){setPhase(value);plotRef.current?.classList.toggle('is-playing',value==='playing');}
    function suspend(){cancel();playing=false;phaseTo(finished?'finished':'paused');}
    function start(){if(playing||document.hidden||!inView||manuallyPaused||finished)return;cancel();playing=true;phaseTo('playing');raf=requestAnimationFrame(tick);}
    function pause(){
      const from=currentVisual;cancel();playing=false;manuallyPaused=true;settling=true;phaseTo('paused');position=Math.round(position);const to=at(position),start=performance.now();
      const settle=now=>{const t=clamp((now-start)/170),e=1-Math.pow(1-t,3);paint({values:from.values.map((v,j)=>v+(to.values[j]-v)*e),lanes:from.lanes.map((v,j)=>v+(to.lanes[j]-v)*e)});if(t<1){raf=requestAnimationFrame(settle);return;}raf=0;settling=false;paintDate();liveRef.current.textContent=`${periodLabel(periods[position])}. Animação pausada.`;};raf=requestAnimationFrame(settle);
    }
    function tick(now){if(!playing)return;if(lastClock==null)lastClock=now;position=Math.min(periods.length-1,position+(now-lastClock)/1050);lastClock=now;paint(at(position));paintDate();if(position>=periods.length-1){playing=false;finished=true;raf=0;phaseTo('finished');liveRef.current.textContent=`${periodLabel(periods.at(-1))}. Fim da animação.`;return;}raf=requestAnimationFrame(tick);}
    control.current=()=>{if(playing){pause();return;}cancel();if(finished){finished=false;position=0;}manuallyPaused=false;start();};
    paint(at(0));paintDate();
    const observer=new IntersectionObserver(entries=>{inView=entries[0].isIntersecting&&entries[0].intersectionRatio>=.2;if(inView)start();else suspend();},{threshold:.2});observer.observe(sectionRef.current);
    const visibility=()=>{if(document.hidden)suspend();else start();};document.addEventListener('visibilitychange',visibility);
    const preference=event=>{if(event.matches){manuallyPaused=true;suspend();position=Math.round(position);paint(at(position));paintDate();}};reduce.addEventListener('change',preference);
    return()=>{cancel();observer.disconnect();document.removeEventListener('visibilitychange',visibility);reduce.removeEventListener('change',preference);control.current=null;};
  },[race,cohort,lo,hi,span,onChoose]);
  return <section className="tc-section tc-race" ref={sectionRef} aria-labelledby={embedded?undefined:'race-title'} aria-label={embedded?'Corrida de ROE dos dez maiores':undefined}>
    <div className="tc-heading"><div>{!embedded&&<h2 id="race-title">A fila anda</h2>}<p>ROE anualizado · %</p></div><div className="tc-film-aside"><div className="tc-date"><span ref={yearRef}/><small ref={quarterRef}/></div><button type="button" className="tc-film-button" disabled={(race?.periods?.length||0)<2} aria-label={phase==='playing'?'Pausar animação':phase==='finished'?'Reproduzir animação novamente':'Reproduzir animação'} onClick={()=>control.current?.()}>{phase==='playing'?<Pause size={17} strokeWidth={1.5}/>:<Play size={17} strokeWidth={1.5}/>}</button></div></div>
    {race?.periods?.length>=2?<>
      <div className="tc-race-axis" aria-hidden="true"><span/><span/><div className="tc-ticks"><span style={{left:0}}>{lo}</span>{lo<0&&<span style={{left:zero+'%'}}>0</span>}<span style={{left:'100%'}}>{hi}</span></div><span/></div>
      <div className="tc-race-rows" ref={plotRef} role="group" aria-label="Instituições ordenadas por ROE" style={{'--zero':zero+'%','--group-count':cohort.length}}>
        {cohort.map(bank=>{const node=key=>element=>{(nodes.current[bank.id]??={})[key]=element;};return <button type="button" key={bank.id} ref={node('row')} className="tc-race-row" style={{'--bank-color':groupColor(bank)}} onClick={()=>onChoose(bank)} aria-label={groupName(bank)+'. Abrir instituição.'}><span ref={node('rank')} className="tc-rank"/><span className="tc-bank-label">{groupName(bank)}</span><span className="tc-bar-space"><span ref={node('bar')} className="tc-bar"/></span><span ref={node('value')} className="tc-race-value"/></button>;})}
      </div><div className="tc-film-progress" aria-hidden="true"><span ref={progressRef}/></div>
    </>:<div className="tc-race-empty" role="status">{race||failed?'Histórico de ROE indisponível.':'Carregando histórico…'}</div>}
    <span className="tc-sr" ref={liveRef} aria-live="polite"/>
    <Source><p>Amostra fixa dos dez maiores por ativos em {periodLabel(cohort[0]?.latestPeriod)}, acompanhada desde {race?.periods?.[0]?periodLabel(race.periods[0]):'o início do histórico comum'}. O movimento e os valores entre trimestres são interpolados somente para a animação. Ao pausar, a leitura se alinha a uma observação publicada.</p><p>As identidades e os perímetros seguem as séries existentes. Códigos oficiais neste conjunto estão disponíveis a partir de dezembro/2025; o regime contábil muda em 2025.</p></Source>
  </section>;
}

function ProfileChart({bank,history}){
  const [ref,width]=useChartWidth(),hist=(history?.history||[]).slice(-8),valid=hist.filter(row=>row.values.roe!=null);
  if(!valid.length)return <div ref={ref} className="tc-profile-chart"><p className="tc-empty">ROE indisponível neste período.</p></div>;
  const w=width||400,h=180,p={left:37,right:14,top:29,bottom:28},values=valid.map(row=>row.values.roe),mn=Math.min(...values),mx=Math.max(...values),pad=Math.max((mx-mn)*.18,1),lo=mn-pad,hi=mx+pad;
  const t0=Date.parse(hist[0].date),t1=Date.parse(hist.at(-1).date),x=date=>p.left+(Date.parse(date)-t0)/(t1-t0||1)*(w-p.left-p.right),y=value=>h-p.bottom-(value-lo)/(hi-lo)*(h-p.top-p.bottom);
  let previous=false;const path=hist.map(row=>{if(row.values.roe==null){previous=false;return '';}const segment=`${previous?'L':'M'}${x(row.date)},${y(row.values.roe)}`;previous=true;return segment;}).join(' '),last=valid.at(-1);
  return <div ref={ref} className="tc-profile-chart">{width>0&&<svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`ROE anualizado de ${groupName(bank)}, últimos oito trimestres, até ${periodLabel(hist.at(-1).period)}`}><title>ROE anualizado · últimos oito trimestres</title><text x={p.left} y={12}>ROE anualizado · %</text>{[lo,(lo+hi)/2,hi].map(value=><g key={value}><line className="tc-grid" x1={p.left} x2={w-p.right} y1={y(value)} y2={y(value)}/><text x={p.left-7} y={y(value)+4} textAnchor="end">{number(value,1)}</text></g>)}<path className="tc-series-line" d={path}/><circle className="tc-series-point" cx={x(last.date)} cy={y(last.values.roe)} r={4}/><text x={p.left} y={h-5}>{periodLabel(hist[0].period)}</text><text x={w-p.right} y={h-5} textAnchor="end">{periodLabel(hist.at(-1).period)}</text></svg>}</div>;
}

function BankPreview({bank,onOpen}){
  const [history,setHistory]=useState(null),[error,setError]=useState('');
  useEffect(()=>{let active=true;setHistory(null);setError('');bankHistory(bank).then(value=>{if(active)setHistory(value);}).catch(()=>{if(active)setError('Histórico indisponível.');});return()=>{active=false;};},[bank]);
  const values=bank.latest;
  return <section className="tc-section tc-profile" id="institution" style={{'--selected-bank':groupColor(bank)}} aria-labelledby="tc-bank-name">
    <div className="tc-profile-top"><h2 id="tc-bank-name">{groupName(bank)}</h2><p>{periodLabel(bank.latestPeriod)} · {bank.perimeter.toLocaleLowerCase('pt-BR')}</p></div>
    <div className="tc-profile-body"><div><dl className="tc-metrics">{[['ROE anualizado',values.roe==null?'N/D':number(values.roe,1)+'%'],['Ativo total',money(values.assets)],['Patrimônio líquido',money(values.equity)],['Lucro no ano',money(values.profitYtd)]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><button className="tc-open-analysis" type="button" onClick={()=>onOpen(bank)}>Abrir análise</button></div>{history?<ProfileChart bank={bank} history={history}/>:<p className="tc-profile-loading" role="status">{error||'Carregando histórico…'}</p>}</div>
    <Source><p>{bank.name}. ROE acumulado anualizado sobre patrimônio líquido médio. O lucro acumulado reinicia a cada ano. Ausências são N/D; carteira e estágio 3 têm mudança de regime contábil em 2025.</p></Source>
  </section>;
}

export default function Landing({catalog,sfn,onNavigate,onOpenInstitution}){
  const cohort=useMemo(()=>selectLandingCohort(catalog),[catalog]),suggested=useMemo(()=>selectLandingCohort(catalog,15).slice(10),[catalog]);
  const [selected,setSelected]=useState(()=>cohort[0]?.id),[networkSelection,setNetworkSelection]=useState(null),[scene,setScene]=useState(()=>{const id=new URLSearchParams(location.search).get('scene');return SCENES.some(([key])=>key===id)?id:'map';}),[sceneMotion,setSceneMotion]=useState(false),[histories,setHistories]=useState(null),[loadError,setLoadError]=useState(false),[retry,setRetry]=useState(0),[menu,setMenu]=useState(false);
  useEffect(()=>{let active=true;setHistories(null);setLoadError(false);Promise.all(cohort.map(bankHistory)).then(value=>{if(active)setHistories(value);}).catch(()=>{if(active)setLoadError(true);});return()=>{active=false;};},[cohort,retry]);
  const raceResult=useMemo(()=>{try{return {value:histories?buildRoeRace(cohort,histories):null,error:false};}catch{return {value:null,error:true};}},[cohort,histories]);
  const credit=useMemo(()=>{try{return creditTotalFromCharts(sfn);}catch{return null;}},[sfn]);
  const race=raceResult.value,historyUnavailable=loadError||raceResult.error;
  const selectedBank=catalog.institutions.find(bank=>bank.id===selected)||cohort[0];
  const selectBank=useCallback(bank=>{setSelected(bank.id);setNetworkSelection(bank.id);},[]);
  const choose=useCallback(bank=>{setSelected(bank.id);setNetworkSelection(bank.id);document.getElementById('institution')?.scrollIntoView({behavior:'auto',block:'start'});},[]);
  function changeScene(id,event){setSceneMotion(!!event?.detail);setScene(id);const url=new URL(location.href);url.searchParams.set('scene',id);history.replaceState({},'',url);}
  function nextScene(offset,event){const index=SCENES.findIndex(([id])=>id===scene);changeScene(SCENES[(index+offset+SCENES.length)%SCENES.length][0],event);}
  const links=[['institutions','Instituições'],['sfn','Sistema financeiro'],['imob','Mercado imobiliário'],['payments','Pagamentos'],['update','Atualizar base']];
  return <div className="tc-landing">
    <header className="tc-nav"><a className="tc-wordmark" href={BASE} onClick={event=>{event.preventDefault();onNavigate('overview');}}>Toma Conta</a><button className="tc-nav-toggle" type="button" aria-label="Abrir navegação" aria-expanded={menu} onClick={()=>setMenu(!menu)}><Menu size={22}/></button><nav className={menu?'is-open':''} aria-label="Navegação principal">{links.map(([id,label])=><a href={`${BASE}?view=${id}`} key={id} onClick={event=>{event.preventDefault();setMenu(false);onNavigate(id);}}>{label}</a>)}</nav></header>
    <main className="tc-explorer" aria-label="Explorar os dados do Toma Conta">
      <div className="tc-explorer-controls"><div className="tc-explorer-navigation"><div className="tc-explorer-tabs" role="tablist" aria-label="Explorações">{SCENES.map(([id,label])=><button type="button" role="tab" key={id} id={`tc-scene-${id}`} aria-selected={scene===id} tabIndex={scene===id?0:-1} aria-controls="tc-explorer-pane" onKeyDown={event=>{setSceneMotion(false);tabNavigation(event);}} onClick={event=>changeScene(id,event)}>{label}</button>)}</div><div className="tc-explorer-arrows"><button type="button" aria-label="Exploração anterior" onClick={event=>nextScene(-1,event)}><ArrowLeft size={18} strokeWidth={1.6}/></button><button type="button" aria-label="Próxima exploração" onClick={event=>nextScene(1,event)}><ArrowRight size={18} strokeWidth={1.6}/></button></div></div><InstitutionSearch catalog={catalog} suggested={suggested} onSelect={onOpenInstitution} placeholder="Buscar uma instituição" label="Buscar instituição"/></div>
      <div className="tc-explorer-title">{scene==='map'?<><h1>Na praça</h1><p>Agências bancárias no Brasil</p></>:scene==='race'?<><h1>A fila anda</h1><p>Dez maiores por ativos em {periodLabel(catalog.latestPeriod)}</p></>:scene==='size'?<><h1 className="tc-dual-title" aria-label="Tamanho e documento"><span>Tamanho</span><span>Documento</span></h1><p>Dez maiores · {periodLabel(catalog.latestPeriod)}</p></>:<><h1>Uma década na conta</h1><p>Crédito no Brasil · R$ trilhões nominais</p></>}</div>
      <div className={'tc-explorer-content'+(sceneMotion?' has-motion':'')} role="tabpanel" id="tc-explorer-pane" aria-labelledby={`tc-scene-${scene}`}>
        <div className={'tc-explore-pane tc-pane-'+scene} key={scene}>
          {scene==='map'&&<Suspense fallback={<div className="tc-scene-loading" role="status">Carregando o mapa…</div>}><NetworkMap {...{catalog}} onOpen={onOpenInstitution} onSelectBank={selectBank} selectedAnalysisId={networkSelection}/></Suspense>}
          {scene==='race'&&<><Race cohort={cohort} race={race} onChoose={choose} failed={historyUnavailable} embedded/>{historyUnavailable&&<p className="tc-history-error" role="status">Histórico indisponível. <button type="button" onClick={()=>setRetry(value=>value+1)}>Tentar novamente</button></p>}</>}
          {scene==='size'&&<><Slope cohort={cohort} onChoose={choose} tall/><Source><p>Posições por ativos e ROE dentro da amostra selecionada, na mesma competência. Cada linha conserva a cor de seu banco.</p></Source></>}
          {scene==='credit'&&<><Credit chart={credit}/><Source sgs><p>Saldo de crédito do SFN. Soma dos quatro componentes de crédito livre e direcionado, PF e PJ, usados no Toma Conta. Valores nominais, sem ajuste pela inflação. Meses incompletos permanecem sem dado.</p></Source></>}
        </div>
      </div>
    </main>
    {selectedBank&&<BankPreview bank={selectedBank} onOpen={onOpenInstitution}/>}
    <footer className="tc-landing-footer"><span>Toma Conta</span><a href="https://matheusprat.es">matheusprat.es</a></footer>
  </div>;
}
