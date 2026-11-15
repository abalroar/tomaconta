import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {validateFiles,validateDependencies} from '../server/shared.js';

const root=fileURLToPath(new URL('../../',import.meta.url));

test('the complete shipped generation satisfies the shared publication dependency contract',async()=>{
 const inventory=[],byHash=new Map();
 for(const [directory,prefix]of [['web/public/data','web/data'],['data/bundled','cache/bundled']]){
  const base=path.join(root,directory);
  for(const entry of await readdir(base,{recursive:true,withFileTypes:true})){
   if(!entry.isFile()||entry.name.startsWith('.')||entry.name.endsWith('.tmp')||entry.name.endsWith('.md'))continue;
   const filename=path.join(entry.parentPath,entry.name),content=await readFile(filename);
   const item={path:prefix+'/'+path.relative(base,filename).split(path.sep).join('/'),size:content.length,sha256:createHash('sha256').update(content).digest('hex'),encoding:'identity'};
   inventory.push(item);byHash.set(item.sha256,{filename,size:item.size});
  }
 }
 const files=validateFiles(inventory);
 const bucket={async get(key){
  const item=byHash.get(key.split('/').at(-1));
  return item?{size:item.size,text:()=>readFile(item.filename,'utf8')}:null;
 }};
 const summary={validation:{complete:true,failures:0},generation:{sourceCommit:'a'.repeat(40),modelVersion:'statement-v6',sourceFiles:inventory.filter(f=>f.path.startsWith('cache/bundled/')&&f.path.endsWith('.parquet')).map(({path,sha256,size})=>({path,sha256,size}))}};
 await validateDependencies(bucket,files,summary);
 assert.ok(files.size>1000,'full generation rather than a selected-entity sample');
 assert.ok(summary.generation.sourceFiles.length>10,'original source Parquets accompany the web dataset');
 const missing=new Map(files);missing.delete('cache/bundled/critical_screens/dados.parquet');
 await assert.rejects(()=>validateDependencies(bucket,missing,summary),/Dependência ausente/);
});
