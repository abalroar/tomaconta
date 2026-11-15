import {groupCode} from './landing-data.js';

export const SCOPE_LABELS={prudential:'Prudencial',individual:'Individual'};
export function statementPeriodLabel(period,full=false){const match=/^(\d{4})(0[1-9]|1[0-2])$/.exec(period||'');return match?`${['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][+match[2]-1]}/${full?match[1]:match[1].slice(-2)}`:period||'N/D';}
export const samePeriods=(left,right)=>Array.isArray(left)&&Array.isArray(right)&&left.length===right.length&&left.every((period,index)=>period===right[index]);
export function validateStatementPacket(entity,periods,packet){
  if(packet?.id!==entity.id||packet.scope!==entity.scope||packet.code!==entity.code||!samePeriods(packet.periods,periods)||!Array.isArray(packet.tables)||packet.unit!=='R$ milhões'||packet.percentUnit!=='fraction')throw Error('As demonstrações recebidas não correspondem à instituição, ao perímetro e às competências escolhidas.');
  return packet;
}
export function preferredStatement(index,bank,crosswalk){
  const linked=crosswalk?.links?.[bank.id];
  if(linked){const entity=index.institutions.find(entry=>entry.id===linked.statementId&&entry.scope===linked.scope&&entry.code===linked.code);if(entity)return entity;}
  // These codes are the explicit, source-backed identities already used by the landing.
  const code=bank.perimeter==='Prudencial'?groupCode(bank):null;
  return code?index.institutions.find(entry=>entry.scope==='prudential'&&entry.code===code)||null:null;
}
/** Reverse only an exact, unique official link; aliases remain independent. */
export function statementAnalysisBank(catalog,crosswalk,entity){
  if(entity?.scope!=='prudential'||!/^C\d{7}$/.test(entity.code||'')||entity.id!==`prudential-${entity.code}`)return null;
  const matches=Object.entries(crosswalk?.links||{}).filter(([,link])=>link.statementId===entity.id&&link.scope===entity.scope&&link.code===entity.code);
  if(matches.length!==1)return null;
  const banks=(catalog?.institutions||[]).filter(bank=>bank.id===matches[0][0]&&bank.perimeter==='Prudencial');
  if(banks.length!==1)return null;
  const knownCode=groupCode(banks[0]);
  return knownCode&&knownCode!==entity.code?null:banks[0];
}
/** A reverse bank synchronization retains the already selected statement dates. */
export function statementSelectionForBank(index,bank,crosswalk,{entity=null,periods=[],requestedId,requestedPeriods}={}){
  const requested=index.institutions.find(entry=>entry.id===requestedId);
  if(requested)return {entity:requested,periods:selectedStatementPeriods(requested,requestedPeriods)};
  const preferred=preferredStatement(index,bank,crosswalk);
  if(!preferred)return {entity:null,periods:[]};
  const sameEntity=entity?.id===preferred.id&&entity.scope===preferred.scope&&entity.code===preferred.code;
  return {entity:preferred,periods:selectedStatementPeriods(preferred,sameEntity?periods:undefined)};
}
export function statementNavigationUrl(href,bank,entity,periods){
  if(bank?.perimeter!=='Prudencial'||!bank.id||entity?.scope!=='prudential'||!/^C\d{7}$/.test(entity.code||'')||entity.id!==`prudential-${entity.code}`)throw Error('Vínculo prudencial inválido.');
  const selected=selectedStatementPeriods(entity,periods);
  if(!Array.isArray(periods)||!samePeriods(selected,periods.slice().sort()))throw Error('Competências de demonstrações inválidas.');
  const url=new URL(href);
  for(const [key,value]of Object.entries({view:'institutions',bank:bank.id,panel:'statements',statement:entity.id,periods:selected.join(',')}))url.searchParams.set(key,value);
  return url;
}
export function statementSearchCatalog(index,scope){
  return {institutions:index.institutions.filter(entity=>entity.scope===scope).map(entity=>({...entity,key:entity.name,officialCode:entity.code,perimeter:scope==='individual'?`Individual · CNPJ-base ${entity.code}`:`Prudencial · ${entity.code}`,latestPeriod:statementPeriodLabel(entity.latestPeriod,true)}))};
}
export function selectedStatementPeriods(entity,requested){
  if(Array.isArray(requested)&&requested.length>=1&&requested.length<=8&&new Set(requested).size===requested.length&&requested.every(period=>entity.periods.includes(period)))return requested.slice().sort();
  return (entity.defaultPeriods?.length?entity.defaultPeriods:entity.periods.slice(-1)).slice().sort();
}
export function statementFileName(packet,entity,periods,format){
  const name=packet?.filename||`${entity.code}_Analise_Financeira_${periods[0]}${periods.length>1?'_a_'+periods.at(-1):''}`;
  return name.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_')+'.'+format;
}
