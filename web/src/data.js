export const BASE=import.meta.env?.BASE_URL ?? '/';
let dataRevision=null;
export const currentDataRevision=()=>dataRevision;
export function pinDataRevision(revision){
 if(revision!==null&&(typeof revision!=='string'||!/^[a-f0-9]{32}$/.test(revision)))throw Error('A revisão publicada é inválida. Recarregue a página.');
 dataRevision=revision;
 return dataRevision;
}
export const datasetRoot=()=>dataRevision?`${BASE}api/shared/data/${dataRevision}/`:`${BASE}data/`;
export function datasetPath(path){
 if(typeof path!=='string'||!/^data\/[A-Za-z0-9_./-]+$/.test(path)||path.slice(5).split('/').some(part=>!part||part==='.'||part==='..'))throw Error('O endereço dos dados é inválido.');
 return path.slice(5);
}
export const datasetUrl=path=>datasetRoot()+datasetPath(path);
export function validateDatasetRoot(value,origin=globalThis.location?.href||'http://localhost/'){
 if(typeof value!=='string'||/[?#\\%]/.test(value)||/(?:^|\/)\.\.?(?:\/|$)/.test(value))throw Error('Origem dos dados inválida.');
 const url=new URL(value,origin),site=new URL(origin),staticPath=new URL(`${BASE}data/`,site).pathname,sharedPath=new URL(`${BASE}api/shared/data/`,site).pathname;
 const shared=url.pathname.startsWith(sharedPath)&&/^[a-f0-9]{32}\/$/.test(url.pathname.slice(sharedPath.length));
 if(url.origin!==site.origin||url.username||url.password||url.search||url.hash||!(url.pathname===staticPath||shared))throw Error('Origem dos dados inválida.');
 return url.href;
}
export const COLORS=['#ec7000','#171717','#8b8c8d','#a64a00','#d1d2d3','#f7ae62','#555759','#b56a20'];
export const number=(v,d=1)=>v==null||v===''||!Number.isFinite(+v)?'N/D':new Intl.NumberFormat('pt-BR',{maximumFractionDigits:d,minimumFractionDigits:d}).format(+v);
export const dateLabel=v=>/^\d{4}-\d{2}/.test(v||'')?`${v.slice(5,7)}/${v.slice(0,4)}`:v||'N/D';
export async function json(path){
 const revision=dataRevision,url=datasetUrl(path),r=await fetch(url);if(!r.ok)throw new Error(`Dados indisponíveis (${r.status}). Tente novamente.`);
 const responseRevision=r.headers.get('X-TomaConta-Revision');
 if(revision&&responseRevision&&responseRevision!==revision)throw Error('Os dados recebidos pertencem a outra revisão. Recarregue a página.');
 let value;
 if(!path.endsWith('.json.gz'))value=await r.json();
 else{const bytes=new Uint8Array(await r.arrayBuffer());
 // Asset servers may already have decoded gzip through Content-Encoding.
 if(bytes[0]!==0x1f||bytes[1]!==0x8b)value=JSON.parse(new TextDecoder().decode(bytes));
 else{if(typeof DecompressionStream!=='function')throw new Error('Este navegador não consegue abrir a base de demonstrações. Atualize o navegador e tente novamente.');
 value=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();}}
 if(revision!==dataRevision)throw Error('A revisão dos dados mudou durante a consulta. Recarregue a página.');
 return value;
}
export function filterChart(chart,window='12',start='',end=''){
 const dates=chart.series.flatMap(s=>s.data.filter(p=>p[1]!=null).map(p=>p[0])).filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x));
 if(!dates.length)return chart;
 const latest=dates.sort().at(-1);let from=start,to=end;
 if(window!=='interval'&&window!=='all'){const [year,month]=latest.split('-').map(Number);const d=new Date(Date.UTC(year,month-1-(+window-1),1));from=d.toISOString().slice(0,10);to=latest.slice(0,7);}
 if(window==='all')from=to='';
 return {...chart,series:chart.series.map(s=>({...s,data:s.data.filter(([x])=>(!from||x>=from)&&(!to||x.slice(0,7)<=to.slice(0,7)))}))};
}
export function periodOf(chart){const points=chart.series.flatMap(s=>s.data.filter(p=>p[1]!=null));const xs=points.map(p=>p[0]).filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)).sort();return xs.length?`${dateLabel(xs[0])} a ${dateLabel(xs.at(-1))}`:points.length?(chart.latestPeriod?dateLabel(chart.latestPeriod):'Recorte categórico'):'Sem dados no período';}
export function chartCategories(chart){const xs=[...new Set(chart.series.flatMap(s=>s.data.map(p=>p[0])))];return xs.every(x=>/^\d{4}-\d{2}-\d{2}$/.test(x))?xs.sort():xs;}
export const axisUnits=chart=>chart.axes?.length?chart.axes.map(unit=>unit||chart.unit||chart.axes[0]||''):[chart.unit||''];
export const seriesAxis=(chart,series)=>series.axis===1&&axisUnits(chart).length>1?1:0;
export const seriesUnit=(chart,series)=>axisUnits(chart)[seriesAxis(chart,series)];
export const percentAxis=(chart,axis=0)=>axisUnits(chart)[axis].includes('%')||(!chart.axes?.length&&axis===0&&chart.percent);
export function csvDownload(charts,name='tomaconta'){
 const escape=v=>'"'+String(v??'').replaceAll('"','""')+'"';
 const rows=[['Gráfico','Série','Data / categoria','Valor','Unidade','Fonte'],...charts.flatMap(c=>c.series.flatMap(s=>s.data.map(([d,v])=>[c.title,s.name,d,v,seriesUnit(c,s),c.source])))];
 download(new Blob(['\ufeff'+rows.map(r=>r.map(escape).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}),name+'.csv');
}
export function download(blob,name){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
export function chartOption(chart){
 const dates=chartCategories(chart),axes=axisUnits(chart);
 return {color:COLORS,animation:false,textStyle:{fontFamily:'Hanken Grotesk Variable, Hanken Grotesk, Arial, sans-serif'},tooltip:{trigger:'axis',confine:true},legend:{bottom:0,type:'scroll',textStyle:{fontSize:11,color:'#555'},itemWidth:10,itemHeight:3},grid:{left:65,right:axes.length>1?65:20,top:28,bottom:65},xAxis:{type:'category',data:dates,axisLabel:{color:'#777',fontSize:10,formatter:dateLabel,hideOverlap:true},axisTick:{show:false},axisLine:{lineStyle:{color:'#ddd'}}},yAxis:axes.map((unit,axis)=>({type:'value',position:axis===1?'right':'left',name:unit,nameTextStyle:{fontSize:10,color:'#777'},scale:!chart.stacked||axis>0,axisLine:{show:false},splitLine:{show:axis===0,lineStyle:{color:'#ececea'}},axisLabel:{color:'#777',fontSize:10,formatter:v=>number(v,Math.abs(v)<10?1:0)+(percentAxis(chart,axis)?'%':'')}})),series:chart.series.map((s,i)=>({name:s.name,type:s.type||'line',yAxisIndex:seriesAxis(chart,s),stack:chart.stacked&&s.type==='bar'?'total-'+seriesAxis(chart,s):undefined,data:dates.map(d=>s.data.find(p=>p[0]===d)?.[1]??null),tooltip:{valueFormatter:v=>number(v,2)+' '+seriesUnit(chart,s)},showSymbol:false,connectNulls:false,lineStyle:{width:i===0?2.6:1.8,type:i>5?'dashed':'solid'},emphasis:{focus:'series'},barMaxWidth:30}))};
}
