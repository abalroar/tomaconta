import {BASE,currentDataRevision,datasetUrl} from './data.js';

/** Older immutable revisions predate Atlas. Only a missing file permits the
 * explicitly identified built-in series; transport and integrity errors fail. */
export async function loadAtlasAsset(name,{fetchImpl=globalThis.fetch,signal}={}){
  if(!['atlas-pf.json','atlas-pj.json'].includes(name))throw Error('Série Atlas desconhecida.');
  const revision=currentDataRevision(),path='data/'+name;
  let response=await fetchImpl(datasetUrl(path),{signal}),builtIn=revision===null;
  if(response.status===404&&revision){
    response=await fetchImpl(BASE+path,{signal});builtIn=true;
  }
  if(!response.ok)throw Error(`A série de crédito não pôde ser carregada (${response.status}).`);
  const received=response.headers.get('X-TomaConta-Revision');
  if(!builtIn&&received&&received!==revision)throw Error('A série recebida pertence a outra revisão. Recarregue a página.');
  const source=await response.json();
  if(currentDataRevision()!==revision)throw Error('A publicação mudou durante a consulta. Recarregue a página.');
  if(source.dims?.person!==(name==='atlas-pf.json'?'PF':'PJ')||!Array.isArray(source.rows)||!source.rows.length)throw Error('A série de crédito está incompleta.');
  return {source,builtIn,revision:builtIn?null:revision};
}
