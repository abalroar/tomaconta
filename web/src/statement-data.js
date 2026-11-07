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
