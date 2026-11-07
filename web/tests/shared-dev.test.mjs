import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';

test('Vite serves the real shared API in explicit static mode without simulating a configured backend',async()=>{
  const root=fileURLToPath(new URL('..',import.meta.url));
  const server=await createServer({root,configFile:fileURLToPath(new URL('../vite.config.js',import.meta.url)),server:{host:'127.0.0.1',port:0},logLevel:'error'});
  try{
    await server.listen();
    const base=`http://127.0.0.1:${server.httpServer.address().port}/tomaconta/api/shared`;
    const current=await fetch(`${base}/current`);
    assert.equal(current.status,200);
    assert.deepEqual(await current.json(),{revision:null,builtIn:true,configured:false});
    const job=await fetch(`${base}/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'mercado_imobiliario'})});
    assert.equal(job.status,503);
    assert.match((await job.json()).error,/não foi configurada/);
  }finally{await server.close();}
});
