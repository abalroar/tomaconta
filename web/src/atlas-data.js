/** Presentation queries over the original SCR numerator and portfolio balances. */
export const ATLAS_PRODUCT_COLORS=Object.freeze([
  '#315f78','#ec7000','#137fb8','#c5534b','#15887c','#56626c',
  '#8a4a36','#b17838','#527d3b','#3153a4','#976f77',
]);
export const rate=pair=>pair&&pair[1]>0?pair[0]/pair[1]*100:null;
export const percent=value=>value==null?'N/D':value.toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})+'%';
export const money=value=>value==null?'N/D':'R$ '+(value/(value>=1e6?1e6:value>=1e3?1e3:1)).toLocaleString('pt-BR',{maximumFractionDigits:1})+(value>=1e6?' bi':value>=1e3?' mi':' mil');
export const monthLabel=value=>['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][+value.slice(5,7)-1]+'/'+value.slice(0,4);
export function productName(value,person=''){
  const label=value.replace(/^P[FJ] - /,'').replace('Empréstimo com consignação em folha','Consignado').replace('Empréstimo sem consignação em folha','Pessoal sem consignação');
  return person==='PJ'&&value.startsWith('PF - ')?label+' (classificação PF)':label;
}
export function shortProduct(value,person=''){
  return productName(value,person).replace('Rural e agroindustrial','Rural').replace('Cartão de crédito','Cartão')
    .replace('Pessoal sem consignação','Pessoal').replace('Financiamento de infraestrutura/desenvolvimento/projeto e outros créditos','Infraestrutura / projetos')
    .replace('Cheque especial e conta garantida','Cheque / conta garantida').replace('Operações com recebíveis','Recebíveis').replace('Outros créditos','Outros')
    .replace(' (classificação PF)',' (PF)');
}

/**
 * Index additive balances once, including all marginal totals. An observed zero
 * remains distinguishable from an absent cell. -1 means the entire dimension.
 */
export function makeCube(source){
  if(source?.schemaVersion!==1||source.unit!=='R$ mil'||!['PF','PJ'].includes(source.person))throw new Error('Base Atlas incompatível.');
  const dims=source.dims;
  if(!dims||dims.person!==source.person||dims.segmentKind!==(source.person==='PF'?'income':'size')||
      !['months','ufs','segments','products'].every(key=>Array.isArray(dims[key])&&dims[key].length)||!Array.isArray(source.rows))throw new Error('Dimensões Atlas incompatíveis.');
  const nm=dims.months.length,ni=dims.segments.length+1,np=dims.products.length+1,ns=dims.ufs.length+1;
  const size=nm*ni*np*ns,n=new Float64Array(size),d=new Float64Array(size),present=new Uint8Array(size);
  const key=(m,i,p,s)=>((m*ni+i+1)*np+p+1)*ns+s+1;
  const seen=new Set();
  for(const row of source.rows){
    const [m,s,i,p,numerator,denominator]=row,k=key(m,i,p,s);
    if(row.length!==6||![[m,nm],[s,ns-1],[i,ni-1],[p,np-1]].every(([value,max])=>Number.isInteger(value)&&value>=0&&value<max)||
      !Number.isFinite(numerator)||!Number.isFinite(denominator)||numerator<0||denominator<0||numerator>denominator||seen.has(k))throw new Error('Saldo ou coordenada Atlas incompatível.');
    seen.add(k);
    for(const segment of [-1,i])for(const product of [-1,p])for(const state of [-1,s]){
      const index=key(m,segment,product,state);n[index]+=numerator;d[index]+=denominator;present[index]=1;
    }
  }
  return {dims,get(m,i=-1,p=-1,s=-1){
    if(![[m,0,nm],[i,-1,ni-1],[p,-1,np-1],[s,-1,ns-1]].every(([value,min,max])=>Number.isInteger(value)&&value>=min&&value<max))return null;
    const index=key(m,i,p,s);return present[index]?[n[index],d[index]]:null;
  }};
}

/** Always use the complete same-cohort portfolio as the composition denominator. */
export function composition(cube,month,segment,state=-1){
  const total=cube.get(month,segment,-1,state),person=cube.dims.person;
  return cube.dims.products.map((name,index)=>{
    const pair=cube.get(month,segment,index,state);
    return {index,name:productName(name,person),short:shortProduct(name,person),pair,
      share:pair&&total?.[1]>0?pair[1]/total[1]*100:null,color:ATLAS_PRODUCT_COLORS[index%ATLAS_PRODUCT_COLORS.length]};
  });
}
