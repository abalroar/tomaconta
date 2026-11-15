import {groupName} from './landing-data.js';

export const ANALYSIS_GROUPS=Object.freeze([
  {id:'balance',title:'Balanço',metrics:['assets','equity','credit','funding'],more:['liquidAssets','deposits','creditFunding'],initial:['assets','credit'],note:'O conceito de core funding muda em 2025.'},
  {id:'result',title:'Resultado',metrics:['profitYtd','profitQuarter','roe','roeQuarter'],more:[],initial:['roe'],note:'Lucro acumulado e trimestral mantêm suas janelas próprias.'},
  {id:'credit',title:'Carteira',metrics:['stage3Ratio','npl','problemAssets','expectedLossRatio'],more:['expectedLoss','stage2','stage3','creditCost'],initial:['stage3Ratio','npl'],note:'Séries da Res. 4.966 disponíveis conforme a cobertura da fonte.'},
  {id:'capital',title:'Capital',metrics:['cet1','basel','capitalPrincipal','rwa'],more:[],initial:['cet1','basel'],note:''},
].map(group=>Object.freeze({...group,metrics:Object.freeze(group.metrics),more:Object.freeze(group.more),initial:Object.freeze(group.initial)})));

const LABELS={profitYtd:'Lucro acumulado no ano',profitQuarter:'Lucro trimestral',roe:'ROE acumulado anualizado',roeQuarter:'ROE trimestral anualizado',stage3Ratio:'Estágio 3 / carteira',expectedLossRatio:'Perda esperada / carteira',npl:'Inadimplência',problemAssets:'Ativos problemáticos',creditFunding:'Crédito / captações',capitalPrincipal:'Capital principal',rwa:'Ativos ponderados pelo risco'};
const CHART_LABELS={credit:'Crédito',cet1:'CET1',basel:'Basileia',npl:'Inadimplência'};
const finite=value=>typeof value==='number'&&Number.isFinite(value);
export const metricLabel=(key,metrics)=>LABELS[key]||metrics[key]?.label||key;
export const chartMetricLabel=(key,metrics)=>CHART_LABELS[key]||metricLabel(key,metrics);
export const metricNote=(key,metrics)=>key==='roe'?'Lucro acumulado anualizado sobre o patrimônio líquido médio.':metrics[key]?.note||metrics[key]?.description||'';
export const metricUnit=(key,metrics,short=false)=>metrics[key]?.unit==='R$'?(short?'R$ bi':'R$ bilhões'):metrics[key]?.unit||'';
export function quarterLabel(period,full=false){const match=/^(\d{4})-Q([1-4])$/.exec(period||'');return match?`${['mar','jun','set','dez'][+match[2]-1]}/${full?match[1]:match[1].slice(-2)}`:period||'N/D';}
const quarterIndex=period=>{const match=/^(\d{4})-Q([1-4])$/.exec(period||'');if(!match)throw Error('Competência trimestral inválida.');return +match[1]*4+(+match[2]-1);};
const periodAt=index=>`${Math.floor(index/4)}-Q${index%4+1}`;
const dateAt=period=>{const [year,q]=period.split('-Q').map(Number);return new Date(Date.UTC(year,q*3,0)).toISOString().slice(0,10);};

export function metricNumber(value,key,metrics,{raw=false}={}){
  if(!finite(value))return 'N/D';
  const monetary=metrics[key]?.unit==='R$',shown=monetary&&!raw?value/1e9:value;
  const digits=raw?(monetary?2:8):shown!==0&&Math.abs(shown)<.01?Math.min(12,2-Math.floor(Math.log10(Math.abs(shown)))):2;
  return new Intl.NumberFormat('pt-BR',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(shown);
}

/** Only accept the exact requested entity. A late response must not cross the perimeter. */
export function validateInstitutionHistory(bank,payload){
  if(!bank||payload?.id!==bank.id||payload.perimeter!==bank.perimeter||!Array.isArray(payload.history))throw Error('O histórico recebido não corresponde à instituição e ao perímetro selecionados.');
  const periods=new Set();
  for(const row of payload.history){quarterIndex(row.period);if(periods.has(row.period))throw Error('Histórico com competência duplicada.');periods.add(row.period);}
  return payload;
}

export function historyThrough(payload,period,window='all'){
  const last=quarterIndex(period),first=window==='all'?-Infinity:last-Math.max(1,Number(window))+1;
  return (payload?.history||[]).filter(row=>{const at=quarterIndex(row.period);return at>=first&&at<=last;}).slice().sort((a,b)=>a.period.localeCompare(b.period));
}
export const observationAt=(payload,period)=>payload?.history?.find(row=>row.period===period)||null;
export function previousObservation(payload,period){return (payload?.history||[]).filter(row=>row.period<period).slice().sort((a,b)=>a.period.localeCompare(b.period)).at(-1)||null;}

/** Formatting only: the source owns every indicator and denominator. Missing quarters are gaps. */
function metricSeries(payload,period,window,key,metrics){
  const observed=historyThrough(payload,period,window);if(!observed.length)return [];
  const values=new Map(observed.map(row=>[row.period,row])),first=quarterIndex(observed[0].period),last=quarterIndex(period),scale=metrics[key]?.unit==='R$'?1e9:1;
  const result=[];
  for(let index=first;index<=last;index++){const p=periodAt(index),row=values.get(p),value=row?.values?.[key];result.push([row?.date||dateAt(p),finite(value)?value/scale:null]);}
  return result;
}

export function institutionChart({bank,payload,metrics,keys,period,window='all',id}){
  validateInstitutionHistory(bank,payload);
  const units=new Set(keys.map(key=>metrics[key]?.unit));if(units.size!==1)throw Error('Escolha indicadores com a mesma unidade para este gráfico.');
  return {id:id||'institution-'+keys.join('-'),title:keys.map(key=>metrics[key]?.label||key).join(' · '),section:bank.name,
    unit:metricUnit(keys[0],metrics),percent:metrics[keys[0]]?.unit==='%',source:'BCB / IFData · '+bank.perimeter,
    note:keys.map(key=>metricNote(key,metrics)).filter(Boolean).join(' '),
    series:keys.map(key=>({name:keys.length===1?bank.name:chartMetricLabel(key,metrics),type:'line',data:metricSeries(payload,period,window,key,metrics)}))};
}

/** Start at the first observed value; internal gaps and observed zero stay intact. */
export function trimChartStart(chart){
  const observed=chart.series.flatMap(series=>series.data.filter(([,value])=>finite(value)).map(([date])=>date)).sort();
  if(!observed.length)return chart;
  return {...chart,series:chart.series.map(series=>({...series,data:series.data.filter(([date])=>date>=observed[0])})),...(chart.totalData?{totalData:chart.totalData.filter(([date])=>date>=observed[0])}:{})};
}

/** Presentation decomposition only. Original CET1/Basel indicators and exports remain intact. */
export function capitalCompositionChart(options){
  const original=institutionChart({...options,keys:['cet1','basel'],id:'bank-capital'});
  const principal=original.series[0].data,total=original.series[1].data;
  const incompatible=principal.some(([,value],index)=>{
    const basel=total[index][1];
    if(value==null&&basel==null)return false;
    return !finite(value)||!finite(basel)||value<0||basel<value;
  });
  if(incompatible)return {...original,note:'Composição indisponível neste recorte. Os índices originais estão exibidos.',compositionAvailable:false};
  return {...original,title:'Composição do índice de Basileia',stacked:true,compositionAvailable:true,
    note:'Diferença para Basileia = Basileia total − CET1, em pontos percentuais.',
    totalData:total.map(point=>point.slice()),valueLabels:{total:true,innerSeries:0},
    series:[{name:'CET1',type:'bar',data:principal.map(point=>point.slice())},{name:'Diferença para Basileia',type:'bar',data:total.map(([date,value],index)=>[date,value==null?null:value-principal[index][1]])}]};
}

export function institutionExportCharts({bank,payload,metrics,period,window='all'}){
  return Object.keys(metrics).map(key=>institutionChart({bank,payload,metrics,keys:[key],period,window}));
}

export function comparisonChart({banks,histories,metrics,key,period,window='all',perimeter}){
  if(banks.length>4||new Set(banks.map(bank=>bank.id)).size!==banks.length)throw Error('A comparação aceita até quatro instituições distintas.');
  if(banks.some(bank=>bank.perimeter!==perimeter))throw Error('Selecione instituições do mesmo perímetro.');
  const byId=new Map(histories.map(payload=>[payload.id,payload]));
  return {id:'institution-comparison-'+key,title:metrics[key]?.label||key,unit:metricUnit(key,metrics),percent:metrics[key]?.unit==='%',source:'BCB / IFData · '+perimeter,note:metricNote(key,metrics),
    series:banks.map(bank=>{const payload=byId.get(bank.id);if(!payload)return {name:groupName(bank),type:'line',data:[]};validateInstitutionHistory(bank,payload);return {name:groupName(bank),type:'line',data:metricSeries(payload,period,window,key,metrics)};})};
}

/** Rank the whole observed perimeter before applying a name filter. Keep observed zero. */
export function institutionRanking(catalog,{perimeter,key,query=''}={}){
  const normalized=query.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
  return (catalog.institutions||[]).filter(bank=>bank.perimeter===perimeter&&bank.latestPeriod===catalog.latestPeriod&&finite(bank.latest?.[key]))
    .slice().sort((a,b)=>b.latest[key]-a.latest[key]||a.id.localeCompare(b.id))
    .map((bank,index)=>({bank,rank:index+1}))
    .filter(({bank})=>!normalized||(groupName(bank)+' '+bank.name).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR').includes(normalized));
}
