/* A resposta deve conter a janela mensal completa consultada, não um delta.
 * Só o resultado validado desta função pode substituir a cópia local. */
const forbidden=value=>/bndu|bens.nao.de.uso/i.test(String(value));
const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
function validDate(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))throw new Error('Data Olinda inválida');
 const d=new Date(value+'T00:00:00Z');
 if(!Number.isFinite(d.getTime())||d.toISOString().slice(0,10)!==value)throw new Error('Data Olinda inválida');
 const next=new Date(d.getTime()+86400000);
 if(next.getUTCDate()!==1)throw new Error('Competência Olinda fora do fechamento mensal');
 return value;
}
function validValue(value){
 if(value==null||!['number','string'].includes(typeof value)||(typeof value==='string'&&!value.trim()))throw new Error('Valor Olinda ausente');
 const n=Number(value);if(!Number.isFinite(n)||n<0)throw new Error('Valor Olinda inválido');return n;
}
const points=chart=>chart.series.flatMap(s=>s.data).filter(p=>p[1]!=null);

export function mergeImob(baseCharts,specs,rows,uf,queryWindow){
 uf=String(uf).toLowerCase();
 if(!/^(br|ac|al|ap|am|ba|ce|df|es|go|ma|mt|ms|mg|pa|pb|pr|pe|pi|rj|rn|rs|ro|rr|sc|sp|se|to)$/.test(uf))throw new Error('Abrangência inválida');
 if(!Array.isArray(baseCharts)||!Array.isArray(specs)||baseCharts.length!==24||specs.length!==24)throw new Error('Catálogo imobiliário deve conter 24 gráficos');
 const byId=new Map(specs.map(s=>[s.id,s]));
 if(byId.size!==24||new Set(baseCharts.map(c=>c.id)).size!==24||baseCharts.some(c=>!byId.has(c.id)))throw new Error('Catálogo e base imobiliária divergentes');
 for(const s of specs){
  if(forbidden(s.id+' '+s.title+' '+s.prefix)||typeof s.prefix!=='string'||!s.labels||!Object.keys(s.labels).length||!Number.isFinite(s.scale)||s.scale<=0)throw new Error('Catálogo imobiliário inválido ou contém BNDU');
 }
 if(baseCharts.some(c=>forbidden(c.id+' '+c.title)||!Array.isArray(c.series)))throw new Error('Base imobiliária inválida ou contém BNDU');
 if(!Array.isArray(rows)||!rows.length)throw new Error('Resposta Olinda sem observações');
 const fresh=new Map(specs.map(s=>[s.id,new Map()]));const seen=new Set();const dates=[];
 for(const row of rows){
  if(!row||typeof row.Info!=='string')throw new Error('Resposta Olinda sem código Info');
  const info=row.Info.toLowerCase();const spec=specs.find(s=>info.startsWith(s.prefix.toLowerCase()));
  if(!spec)continue; // BNDU e outros blocos fora do escopo aprovado não entram na cópia.
  const suffix='_'+uf;if(!info.endsWith(suffix))throw new Error('Resposta Olinda contém outra abrangência');
  let category=info.slice(spec.prefix.length,-suffix.length);
  if(spec.historical&&!own(spec.labels,category)){
   const line=['home_equity','sfh','fgts','livre','comercial'].find(line=>category.startsWith(line+'_'));
   if(line)category=category.slice(line.length+1);
  }
  if(!own(spec.labels,category))throw new Error('Categoria nova no BCB; revisar catálogo: '+row.Info);
  const date=validDate(row.Data),value=validValue(row.Valor);const key=info+'|'+date;
  if(seen.has(key))throw new Error('Resposta Olinda com série/competência duplicada');seen.add(key);
  if(spec.historical){if(date>'2024-12-31')throw new Error('Risco histórico recebeu competência posterior a dezembro/2024');continue;}
  dates.push(date);
  if(!fresh.get(spec.id).has(category))fresh.get(spec.id).set(category,[]);
  const scaled=value*spec.scale;if(!Number.isFinite(scaled))throw new Error('Valor Olinda fora da escala válida');
  fresh.get(spec.id).get(category).push([date,scaled]);
 }
 if(!dates.length)throw new Error('Resposta Olinda sem séries ativas do catálogo');
 dates.sort();let start=dates[0].slice(0,7),end=dates.at(-1).slice(0,7);
 if(queryWindow){
  if(!/^\d{4}-\d{2}-01$/.test(queryWindow.start||''))throw new Error('Janela consultada inválida');
  const endDate=validDate(queryWindow.end);const startDate=queryWindow.start;
  if(startDate>endDate||dates.some(date=>date<startDate||date>endDate))throw new Error('Resposta fora da janela consultada');
  start=startDate.slice(0,7);end=endDate.slice(0,7);
 }
 for(const c of baseCharts){const s=byId.get(c.id);if(!s.historical&&points(c).length&&!fresh.get(c.id).size)throw new Error('Cobertura ativa incompleta: '+c.title+' · '+c.id);}
 return baseCharts.map(c=>{
  const spec=byId.get(c.id);if(spec.historical)return structuredClone(c);
  const categories=[...new Set([...c.series.map(s=>s.category),...fresh.get(c.id).keys()])];
  if(categories.some(cat=>!own(spec.labels,cat)))throw new Error('Categoria inválida na base anterior');
  const series=categories.map(category=>{
   const previous=c.series.find(s=>s.category===category);const before=(previous?.data||[]).filter(([date])=>date.slice(0,7)<start||date.slice(0,7)>end);
   const data=[...before,...(fresh.get(c.id).get(category)||[])].sort((a,b)=>a[0].localeCompare(b[0]));
   return {...previous,name:previous?.name||spec.labels[category],category,type:previous?.type||(spec.stacked?'bar':'line'),data};
  });
  const updated={...c,series};const actual=points(updated).map(p=>p[0]).sort();
  return {...updated,latestPeriod:actual.length?actual.at(-1).slice(0,7):null};
 });
}
