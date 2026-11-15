import {BASE,pinDataRevision} from './data.js';
let sequence=0;

/** Resolve one immutable publication before any dataset request is allowed. */
export async function loadPublication({fetchImpl=globalThis.fetch,timeoutMs=20000,signal}={}){
 const request=++sequence,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
 const abort=()=>controller.abort();
 if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
 const current=()=>{if(controller.signal.aborted)throw new DOMException('Consulta da publicação cancelada.','AbortError');if(request!==sequence)throw Error('A consulta da publicação foi substituída.');};
 try{
  current();
  const response=await fetchImpl(`${BASE}api/shared/current`,{cache:'no-store',credentials:'same-origin',signal:controller.signal});
  if(response.status===404){current();pinDataRevision(null);return {revision:null,publishedAt:null,summary:null,builtIn:true,configured:false};}
  if(!response.ok)throw Error(`A publicação dos dados não pôde ser consultada (${response.status}). Tente novamente.`);
  let value;try{value=await response.json();}catch{if(controller.signal.aborted)current();throw Error('A publicação dos dados retornou uma resposta inválida. Tente novamente.');}
  if(!value||Array.isArray(value)||typeof value.builtIn!=='boolean'||typeof value.configured!=='boolean'||
    !(value.revision===null||typeof value.revision==='string'&&/^[a-f0-9]{32}$/.test(value.revision))||
    value.builtIn!==(value.revision===null)||value.revision!==null&&!value.configured)throw Error('A revisão publicada é inválida. Tente novamente.');
  current();
  pinDataRevision(value.revision);
  return {publishedAt:null,summary:null,...value};
 }catch(error){if(error.name==='AbortError'&&!signal?.aborted)throw Error('A consulta da publicação demorou mais que o esperado. Tente novamente.');throw error;}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
