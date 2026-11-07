/** Dados da landing: seleção por competência, valores publicados e identidades preservadas. */
import {WEB_CHART_COLORS} from './chart-palette.js';
export const LANDING_GROUPS = Object.freeze([
  {id:'5f6d3c0745685d8f',code:'C0080099',name:'Itaú',color:'#ce623c',aliases:['Itaú Unibanco']},
  {id:'b0cbcee8867e0b37',code:'C0080329',name:'Banco do Brasil',color:'#aa8a22',aliases:['BB']},
  {id:'12651c6cfd2d796a',code:'C0080738',name:'Caixa',color:'#377f94',aliases:['Caixa Econômica Federal','CEF']},
  {id:'1271a247d1938e89',code:'C0080075',name:'Bradesco',color:'#a74f55',aliases:[]},
  {id:'1158033738ca5910',code:'C0080185',name:'Santander',color:'#b87565',aliases:[]},
  {id:'58c62dcbed64208d',code:'C0081847',name:'BNDES',color:'#597e68',aliases:[]},
  {id:'5d53c967bf0ddc8d',code:'C0080336',name:'BTG Pactual',color:'#405a79',aliases:['BTG']},
  {id:'825e73885fbb79d5',code:'C0084693',name:'Nu Pagamentos',color:'#8969a7',aliases:['Nu','Nubank']},
  {id:'1e6a5be08d9a6c50',code:'C0082475',name:'XP',color:'#626b73',aliases:[]},
  {id:'ac8036c1608c3e12',code:'C0080109',name:'Safra',color:'#8e8248',aliases:[]},
].map(profile=>Object.freeze({...profile,aliases:Object.freeze(profile.aliases)})));

const profilesById = new Map(LANDING_GROUPS.map(profile=>[profile.id,profile]));
const profilesByCode = new Map(LANDING_GROUPS.map(profile=>[profile.code,profile]));
const profileFor = group => typeof group==='string'
  ? profilesById.get(group)||profilesByCode.get(group)
  : profilesById.get(group?.id)||profilesByCode.get(group?.officialCode||group?.code||group?.CodInst);
const finite = value => typeof value==='number'&&Number.isFinite(value);

export function groupName(group){
  return profileFor(group)?.name||String(group?.name||group?.officialName||(typeof group==='string'?group:'Grupo não identificado')).replace(/\s*-\s*PRUDENCIAL\s*$/i,'').trim();
}

export function groupCode(group){
  return profileFor(group)?.code||group?.officialCode||group?.code||group?.CodInst||null;
}

export function groupColor(group){
  const profile=profileFor(group);if(profile)return profile.color;
  const identity=String(group?.id||groupCode(group)||group?.name||group||'');
  let hash=2166136261;for(const character of identity)hash=Math.imul(hash^character.charCodeAt(0),16777619)>>>0;
  return WEB_CHART_COLORS[hash%WEB_CHART_COLORS.length];
}

/** Retorna os objetos originais do catálogo; não reúne nomes ou perímetros. */
export function selectLandingCohort(catalog,limit=10){
  const count=Number.isFinite(limit)?Math.max(0,Math.floor(limit)):0;
  return (catalog?.institutions||[])
    .filter(group=>group.perimeter==='Prudencial'&&group.latestPeriod===catalog.latestPeriod&&finite(group.latest?.assets))
    .slice().sort((a,b)=>b.latest.assets-a.latest.assets||String(a.id).localeCompare(String(b.id)))
    .slice(0,count);
}

const CREDIT_COMPONENTS=Object.freeze(['PJ livre','PF livre','PJ direcionado','PF direcionado']);

/** Um gráfico comum de uma série. Exige os quatro componentes em cada mês. */
export function creditTotalFromCharts(charts,{start='2016-09',end}={}){
  const source=(charts||[]).find(chart=>chart.id==='credito_estoque-1');if(!source)return null;
  if(!['R$ bi','R$ bilhões'].includes(source.unit))throw new Error('Unidade inesperada no estoque de crédito publicado.');
  const components=CREDIT_COMPONENTS.map(name=>{
    const matches=source.series.filter(series=>series.name===name);
    if(matches.length>1)throw new Error('Componente de crédito duplicado: '+name);
    return matches[0]||null;
  });
  const maps=components.map(series=>{
    const points=new Map();for(const [date,value] of series?.data||[]){
      if(points.has(date))throw new Error('Competência de crédito duplicada: '+date);
      points.set(date,value);
    }return points;
  });
  const dates=[...new Set(maps.flatMap(points=>[...points.keys()]))].sort()
    .filter(date=>(!start||date.slice(0,7)>=start.slice(0,7))&&(!end||date.slice(0,7)<=end.slice(0,7)));
  const data=dates.map(date=>{
    const values=maps.map(points=>points.get(date));
    return [date,values.every(finite)?values.reduce((sum,value)=>sum+value,0):null];
  });
  return {id:'landing-credit-total',title:'Estoque total de crédito do SFN',section:source.section,
    unit:source.unit,source:source.source,percent:false,stacked:false,
    note:'Total derivado dos quatro componentes publicados: PF/PJ com recursos livres/direcionados. Exige os quatro valores por competência; lacunas permanecem N/D. Valores já em R$ bilhões, conforme o gráfico de origem.',
    sourceChartId:source.id,components:[...CREDIT_COMPONENTS],
    missingComponents:CREDIT_COMPONENTS.filter((name,index)=>!components[index]),
    series:[{name:'Total derivado do SFN',type:'line',data}]};
}

const quarterIndex=period=>{
  const match=/^(\d{4})-Q([1-4])$/.exec(period||'');
  if(!match)throw new Error('Competência trimestral inválida: '+period);
  return Number(match[1])*4+Number(match[2])-1;
};
const quarterLabel=index=>`${Math.floor(index/4)}-Q${index%4+1}`;

function indexedHistories(histories){
  const identities=new Set();
  return (histories||[]).map(payload=>{
    if(!payload?.id||identities.has(payload.id))throw new Error('Identidade de histórico ausente ou duplicada.');
    identities.add(payload.id);const rows=new Map();
    for(const row of payload.history||[]){quarterIndex(row.period);if(rows.has(row.period))throw new Error('Histórico com trimestre duplicado: '+row.period);rows.set(row.period,row);}
    return {id:payload.id,rows};
  });
}

function periodCoverage(indexed,{startPeriod='2018-Q1',endPeriod}={}){
  const observed=indexed.flatMap(payload=>[...payload.rows.keys()]).sort();
  if(!indexed.length||!observed.length)return {periods:[],blocks:[],missingPeriods:[]};
  const first=quarterIndex(startPeriod),last=quarterIndex(endPeriod||observed.at(-1));
  const blocks=[],missingPeriods=[];let current=[];
  for(let index=first;index<=last;index++){
    const period=quarterLabel(index),available=indexed.every(payload=>finite(payload.rows.get(period)?.values?.roe));
    if(available)current.push(period);
    else {missingPeriods.push(period);if(current.length){blocks.push(current);current=[];}}
  }
  if(current.length)blocks.push(current);
  return {periods:blocks.at(-1)?.slice()||[],blocks,missingPeriods};
}

/** Último bloco comum contínuo, sem atravessar uma lacuna de nenhum grupo. */
export function commonRoePeriods(histories,options={}){
  return periodCoverage(indexedHistories(histories),options).periods;
}

/** Frames publicados; values segue a ordem do cohort, ranking é decrescente. */
export function buildRoeRace(cohort,histories,options={}){
  const indexed=indexedHistories(histories),byId=new Map(indexed.map(payload=>[payload.id,payload]));
  if(new Set(cohort.map(group=>group.id)).size!==cohort.length)throw new Error('Grupo duplicado no recorte da corrida.');
  const selected=cohort.map(group=>{
    const payload=byId.get(group.id);if(!payload)throw new Error('Histórico indisponível para '+groupName(group));return payload;
  });
  const coverage=periodCoverage(selected,options);
  const frames=coverage.periods.map(period=>{
    const values=selected.map(payload=>payload.rows.get(period).values.roe);
    const ranking=cohort.map((group,index)=>({id:group.id,roe:values[index],value:values[index],
      name:groupName(group),officialName:group.name,color:groupColor(group),perimeter:group.perimeter,order:index}))
      .sort((a,b)=>b.roe-a.roe||a.order-b.order).map(({order,...row},index)=>({...row,rank:index+1}));
    return {period,values,ranking,leaderId:ranking[0]?.id||null};
  });
  const values=frames.flatMap(frame=>frame.values);
  return {...coverage,frames,minRoe:values.length?Math.min(...values):null,maxRoe:values.length?Math.max(...values):null};
}

export function normalizeInstitutionQuery(value){
  return String(value??'').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLocaleLowerCase('pt-BR')
    .replace(/[^\p{L}\p{N}]+/gu,' ').trim().replace(/\s+/g,' ');
}

const aliasesFor=group=>[
  ...(profileFor(group)?.aliases||[]),
  ...(Array.isArray(group.aliases)?group.aliases:group.aliases?[group.aliases]:[]),
  ...(group.id==='8debf22957381dff'?['Banco Inter']:[]),
];
const identifiersFor=group=>[
  group.id,group.key,groupCode(group),group.cnpj,group.cnpjBase,group.CodInst,
  ...(Array.isArray(group.identifiers)?group.identifiers:group.identifiers&&typeof group.identifiers==='object'?Object.values(group.identifiers):group.identifiers?[group.identifiers]:[]),
].filter(value=>value!=null);

// Cada novo snapshot recebe seu próprio índice; o WeakMap permite liberar os anteriores.
const institutionSearchIndexes=new WeakMap();
function institutionSearchIndex(catalog){
  if(!catalog||typeof catalog!=='object')return [];
  const cached=institutionSearchIndexes.get(catalog);if(cached)return cached;
  const index=(catalog.institutions||[]).map(group=>{
    const displayName=groupName(group),names=[displayName,group.name,...aliasesFor(group)].map(normalizeInstitutionQuery);
    const ids=identifiersFor(group).map(normalizeInstitutionQuery);
    const text=[...names,...ids,normalizeInstitutionQuery(group.perimeter)].join(' ');
    return {group,displayName,names,text,words:text.split(' '),compactIds:ids.map(value=>value.replaceAll(' ','')),
      current:group.latestPeriod===catalog.latestPeriod,color:groupColor(group),code:groupCode(group)};
  });
  institutionSearchIndexes.set(catalog,index);return index;
}

/** Pesquisa o catálogo inteiro e conserva nome oficial, id, histórico e perímetro. */
export function searchInstitutions(catalog,query,{limit=8,perimeter}={}){
  const normalized=normalizeInstitutionQuery(query);if(!normalized)return [];
  const tokens=normalized.split(' '),compact=normalized.replaceAll(' ','');
  const matches=[];
  for(const entry of institutionSearchIndex(catalog)){
    const {group,names,text,words}=entry;
    if(perimeter&&group.perimeter!==perimeter)continue;
    let score=entry.compactIds.includes(compact)?1000:
      names.some(value=>value===normalized)?900:names.some(value=>value.startsWith(normalized))?700:
      tokens.every(token=>words.some(word=>word.startsWith(token)))?500:
      tokens.every(token=>text.includes(token))?300:0;
    if(!score)continue;
    if(entry.current)score+=5;
    matches.push({score,entry});
  }
  return matches.sort((a,b)=>b.score-a.score||(b.entry.group.latest?.assets??-Infinity)-(a.entry.group.latest?.assets??-Infinity)||String(a.entry.group.id).localeCompare(String(b.entry.group.id)))
    .slice(0,Number.isFinite(limit)?Math.max(0,Math.floor(limit)):0)
    .map(({entry})=>({...entry.group,displayName:entry.displayName,color:entry.color,code:entry.code,perimeter:entry.group.perimeter||'Perímetro não informado'}));
}
