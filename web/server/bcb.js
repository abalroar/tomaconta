/** Proxy de fontes públicas do BCB; destinos e limites são definidos no servidor. */
export async function bcbProxy(url, fetcher = fetch) {
  const source = url.searchParams.get('source');
  let target,queryWindow;
  if (source === 'sgs') {
    const code=url.searchParams.get('code');
    if (!/^\d{1,6}$/.test(code||'')) return Response.json({error:'Série inválida'},{status:400});
    const last=url.searchParams.get('last')==='1';
    target=new URL(`https://api.bcb.gov.br/dados/serie/bcdata.sgs.${code}/dados${last?'/ultimos/1':''}`);
    target.searchParams.set('formato','json');
    if(!last) target.searchParams.set('dataInicial',`01/01/${new Date().getUTCFullYear()-9}`);
  } else if(source==='imob') {
    const uf=url.searchParams.get('uf')||'br';
    if(!'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to br'.split(' ').includes(uf)) return Response.json({error:'UF inválida'},{status:400});
    target=new URL('https://olinda.bcb.gov.br/olinda/servico/MercadoImobiliario/versao/v1/odata/mercadoimobiliario');
    target.searchParams.set('$format','json');target.searchParams.set('$select','Data,Info,Valor');
    target.searchParams.set('$filter',"Info eq 'credito_estoque_carteira_credito_pf_sfh_br'");
    target.searchParams.set('$orderby','Data desc');target.searchParams.set('$top','1');
    if(url.searchParams.get('latest')!=='1') {
      try {
        const response=await fetcher(target.toString().replaceAll('+','%20'),{signal:AbortSignal.timeout(25000),headers:{Accept:'application/json'}});
        if(!response.ok) throw Error('probe');
        const obj=await response.json(),latest=obj.value?.[0]?.Data;
        if(!/^\d{4}-\d{2}-\d{2}/.test(latest||'')) throw Error('date');
        const since=new Date(latest.slice(0,7)+'-01T12:00:00Z');since.setUTCMonth(since.getUTCMonth()-11);
        queryWindow={start:since.toISOString().slice(0,10),end:latest.slice(0,10)};
        target.searchParams.set('$filter',`Data ge '${since.toISOString().slice(0,10)}' and endswith(Info,'_${uf}')`);
        target.searchParams.set('$orderby','Data asc,Info asc');target.searchParams.set('$top','12000');
      } catch{return Response.json({error:'Não foi possível consultar a competência do BCB'},{status:502});}
    }
  } else return Response.json({error:'Fonte inválida'},{status:400});
  try {
    const upstream=await fetcher(target.toString().replaceAll('+','%20'),{signal:AbortSignal.timeout(25000),headers:{Accept:'application/json'},cf:{cacheTtl:300,cacheEverything:true}});
    if(!upstream.ok)return Response.json({error:'A fonte oficial está temporariamente indisponível'},{status:502});
    const payload=await upstream.json();
    if(source==='imob'&&(!Array.isArray(payload.value)||payload.value.length>=12000||payload['@odata.nextLink']))return Response.json({error:'Cobertura excede o limite de consulta; versão anterior preservada'},{status:502});
    return Response.json(source==='imob'&&queryWindow?{...payload,_queryWindow:queryWindow}:payload,{headers:{'Cache-Control':'public, max-age=60','X-Content-Type-Options':'nosniff','X-TomaConta-Source':source}});
  }catch{return Response.json({error:'Tempo de consulta ao BCB excedido'},{status:502});}
}
