/** Public BCB agency register, aggregated by official IBGE municipality. */
import {groupCode} from './landing-data.js';
export const NETWORK_BRANDS = Object.freeze({
  '00000000':{name:'Banco do Brasil',short:'BB',color:'#b49612',ink:'#78620a'},
  '00360305':{name:'Caixa',short:'Caixa',color:'#087eaa',ink:'#006389'},
  '60746948':{name:'Bradesco',short:'Bradesco',color:'#cf334b',ink:'#a2253b'},
  '60701190':{name:'Itaú',short:'Itaú',color:'#eb6b21',ink:'#a64512'},
  '90400888':{name:'Santander',short:'Santander',color:'#bd3540',ink:'#a2212d'},
  '30306294':{name:'BTG Pactual',short:'BTG',color:'#254d78',ink:'#254d78'},
  '58160789':{name:'Safra',short:'Safra',color:'#37596b',ink:'#37596b'},
});
export const networkName=bank=>NETWORK_BRANDS[bank?.idCnpjBase]?.name||bank?.name||'Todos os bancos';
export const networkColor=bank=>NETWORK_BRANDS[bank?.idCnpjBase]?.color||'#317d8a';
export const normalizeSearch=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR').replace(/\s+/g,' ').trim();
export const networkPosition=position=>{const [year,month,day]=String(position||'').split('-');return year&&month&&day?`${day}/${month}/${year}`:'N/D';};

export function validateNetwork(value){
  if(!value||!/^\d{4}-\d{2}-\d{2}$/.test(value.position)||!Array.isArray(value.banks)||!Array.isArray(value.municipalities))throw Error('O cadastro da rede não está disponível.');
  const banks=new Map(),municipalities=new Set(),counts=new Map();let total=0;
  for(const bank of value.banks){
    if(!/^\d{8}$/.test(bank.idCnpjBase)||banks.has(bank.idCnpjBase)||!Number.isInteger(bank.count)||bank.count<0||!Number.isInteger(bank.municipalities)||bank.municipalities<0)throw Error('O cadastro da rede contém uma identidade incompatível.');
    banks.set(bank.idCnpjBase,bank);counts.set(bank.idCnpjBase,{count:0,municipalities:0});
  }
  for(const municipality of value.municipalities){
    const point=Number.isFinite(municipality.lon)&&Number.isFinite(municipality.lat)&&Math.abs(municipality.lon)<=180&&Math.abs(municipality.lat)<=90;
    if(!/^\d{7}$/.test(municipality.ibge)||municipalities.has(municipality.ibge)||!municipality.name||!municipality.uf||(!point&&!(municipality.lon==null&&municipality.lat==null&&municipality.total===0))||!Number.isInteger(municipality.total)||municipality.total<0||!municipality.banks)throw Error('A geografia da rede contém um município incompatível.');
    municipalities.add(municipality.ibge);let sum=0;
    for(const [id,count]of Object.entries(municipality.banks)){
      if(!banks.has(id)||!Number.isInteger(count)||count<=0)throw Error('A distribuição municipal da rede está incompleta.');
      sum+=count;const record=counts.get(id);record.count+=count;record.municipalities+=1;
    }
    if(sum!==municipality.total)throw Error('As contagens municipais da rede não fecham.');total+=sum;
  }
  for(const bank of value.banks){const checked=counts.get(bank.idCnpjBase);if(checked.count!==bank.count||checked.municipalities!==bank.municipalities)throw Error('As contagens por banco da rede não fecham.');}
  if(value.banks.reduce((sum,bank)=>sum+bank.count,0)!==total)throw Error('A contagem nacional da rede não fecha.');
  return value;
}

export function networkSummary(data,bankId=null){
  const municipalities=data.municipalities.filter(city=>bankId?(city.banks[bankId]||0)>0:city.total>0);
  const branches=bankId?data.banks.find(bank=>bank.idCnpjBase===bankId)?.count:municipalities.reduce((sum,city)=>sum+city.total,0);
  return {branches:branches??null,municipalities:municipalities.length,singleBankMunicipalities:municipalities.filter(city=>Object.keys(city.banks).length===1).length};
}

export function municipalityBanks(data,city){
  const byId=new Map(data.banks.map(bank=>[bank.idCnpjBase,bank]));
  return Object.entries(city?.banks||{}).map(([id,count])=>({bank:byId.get(id),count})).filter(row=>row.bank).sort((a,b)=>b.count-a.count||a.bank.idCnpjBase.localeCompare(b.bank.idCnpjBase));
}

export function findNetworkMunicipalities(data,query,limit=8){
  const normalized=normalizeSearch(query);if(!normalized)return [];
  const ufs=new Set(data.municipalities.map(city=>city.uf.toLowerCase())),tokens=normalized.split(' ');
  const selected=/^\d{7}$/.test(normalized)?data.municipalities.filter(city=>city.ibge===normalized):data.municipalities.filter(city=>tokens.every(token=>ufs.has(token)?city.uf.toLowerCase()===token:normalizeSearch(city.name).includes(token)));
  return selected.sort((a,b)=>Number(normalizeSearch(b.name)===normalized)-Number(normalizeSearch(a.name)===normalized)||b.total-a.total||a.name.localeCompare(b.name,'pt-BR')).slice(0,limit);
}

/** IBGE RFC 7946 rings are normalized for D3's small-area spherical winding. */
export function networkGeometryForD3(geometry){
  function ring(value,outer){
    const area=value.slice(1).reduce((sum,point,index)=>sum+value[index][0]*point[1]-point[0]*value[index][1],0);
    return (outer?area>0:area<0)?value.slice().reverse():value.map(point=>point.slice());
  }
  function polygon(value){return value.map((points,index)=>ring(points,index===0));}
  function shape(value){if(value.type==='Polygon')return {...value,coordinates:polygon(value.coordinates)};if(value.type==='MultiPolygon')return {...value,coordinates:value.coordinates.map(polygon)};throw Error('Geometria da rede incompatível.');}
  if(geometry.type!=='FeatureCollection')throw Error('Geografia da rede incompatível.');
  return {...geometry,features:geometry.features.map(feature=>({...feature,geometry:shape(feature.geometry)}))};
}

export function networkAnalysisBank(dataBank,catalog){
  const link=dataBank?.analysisLink;
  if(!link||link.scope!=='prudential'||!/^C\d{7}$/.test(link.code||'')||link.statementId!==`prudential-${link.code}`)return null;
  const matches=catalog.institutions.filter(bank=>bank.id===link.analysisId&&bank.perimeter==='Prudencial');
  if(matches.length!==1)return null;
  const knownCode=groupCode(matches[0]);
  return knownCode&&knownCode!==link.code?null:matches[0];
}
