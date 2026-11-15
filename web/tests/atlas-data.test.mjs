import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {makeCube,rate,composition,productName} from '../src/atlas-data.js';

const load=async name=>JSON.parse(await readFile(new URL('../public/data/'+name,import.meta.url)));
const [pf,pj,validation]=await Promise.all(['atlas-pf.json','atlas-pj.json','atlas-validation.json'].map(load));
const sum=rows=>rows.length?rows.reduce((value,row)=>[value[0]+row[4],value[1]+row[5]],[0,0]):null;
const close=(a,b)=>assert.ok(Math.abs(a-b)<=Math.max(1,Math.abs(b))*1e-12,`${a} != ${b}`);

test('PF income and PJ size retain separate source dimensions and every official modality',()=>{
  assert.deepEqual(pf.dims.segments,['Sem rendimento','Até 1 salário mínimo','Mais de 1 a 2 salários mínimos','Mais de 2 a 3 salários mínimos','Mais de 3 a 5 salários mínimos','Mais de 5 a 10 salários mínimos','Mais de 10 a 20 salários mínimos','Acima de 20 salários mínimos','Indisponível']);
  assert.deepEqual(pj.dims.segments,['Micro','Pequeno','Médio','Grande','Indisponível']);
  assert.equal(pf.dims.segmentKind,'income');assert.equal(pj.dims.segmentKind,'size');
  assert.equal(pf.dims.products.length,7);assert.equal(pj.dims.products.length,11);
  assert.equal(pj.classificationExceptions.length,2);
  for(const item of pj.classificationExceptions)assert.match(productName(item.product,'PJ'),/classificação PF/);
  assert.ok(!productName(pj.dims.products[0],'PJ').startsWith('PJ - '));
  for(const source of [pf,pj]){
    assert.equal(source.unit,'R$ mil');assert.equal(source.dims.months.length,31);
    assert.equal(source.periodStart,'2024-01');assert.equal(source.periodEnd,'2026-07');
    assert.equal(new Set(source.dims.ufs.map(uf=>uf.uf)).size,27);
    assert.ok(source.checks.originalQuery.reduce((count,check)=>count+check.cuts,0)>10000);
    assert.ok(source.checks.originalQuery.every(check=>check.maxRateDifferencePP<.00002));
  }
});

test('indexed PF and PJ aggregates match independent sums across all intersections and marginal totals',()=>{
  for(const source of [pf,pj]){
    const cube=makeCube(source),last=source.dims.months.length-1;
    for(const [month,segment,product,state] of [[0,-1,-1,-1],[last,-1,-1,-1],[last,0,-1,25],[last,3,0,2],[0,-1,3,9],[12,2,1,-1],[last,-1,source.dims.products.length-1,-1]]){
      const rows=source.rows.filter(row=>row[0]===month&&(segment<0||row[2]===segment)&&(product<0||row[3]===product)&&(state<0||row[1]===state));
      const expected=sum(rows),actual=cube.get(month,segment,product,state);
      if(expected===null)assert.equal(actual,null);else expected.forEach((value,index)=>close(actual[index],value));
    }
    close(rate(cube.get(last)),source.checks.latest.ratePct);
    for(const invalid of [[.5,-1,-1,-1],[-1,-1,-1,-1],[last,999,-1,-1],[last,-1,-1,27]])assert.equal(cube.get(...invalid),null);
  }
});

test('an absent source cell stays N/D while an observed zero numerator stays zero',()=>{
  for(const source of [pf,pj]){
    const cube=makeCube(source),present=new Set(source.rows.map(row=>row.slice(0,4).join(':')));
    let absent=null;
    for(let i=0;i<source.dims.segments.length&&!absent;i++)for(let p=0;p<source.dims.products.length&&!absent;p++){
      if(!present.has([0,0,i,p].join(':')))absent=[0,i,p,0];
    }
    assert.ok(absent);assert.equal(cube.get(...absent),null);assert.equal(rate(cube.get(...absent)),null);
    const row=source.rows.find(row=>row[4]===0&&row[5]>0);assert.ok(row);
    assert.equal(rate(cube.get(row[0],row[2],row[3],row[1])),0);
  }
});

test('composition closes to the full PF/PJ cohort without resetting denominator on modality selection',()=>{
  for(const source of [pf,pj]){
    const cube=makeCube(source);
    for(const month of [0,12,30])for(const segment of [-1,0,3,source.dims.segments.length-1])for(const state of [-1,0,9,25]){
      const total=cube.get(month,segment,-1,state),parts=composition(cube,month,segment,state);
      if(total?.[1]>0){
        close(parts.reduce((value,part)=>value+(part.share??0),0),100);
        close(parts.reduce((value,part)=>value+(part.pair?.[1]??0),0),total[1]);
        for(const part of parts)if(part.pair)close(part.share,part.pair[1]/total[1]*100);
      }else assert.ok(parts.every(part=>part.share===null));
    }
  }
});

test('published validation hashes identify the actual delivered PF/PJ cubes',async()=>{
  for(const person of validation.persons){
    const bytes=await readFile(new URL('../public/'+person.asset.path,import.meta.url));
    assert.equal(bytes.length,person.asset.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'),person.asset.sha256);
  }
  assert.equal(pf.sourceRevision,pj.sourceRevision);
  assert.deepEqual(pf.sourceFiles,pj.sourceFiles);
  assert.ok(pf.sourceFiles.every(file=>/^[a-f0-9]{64}$/.test(file.sha256)));
});

test('incompatible or duplicate coordinates fail instead of silently changing balances',()=>{
  const source={...pf,rows:[pf.rows[0],pf.rows[0]]};assert.throws(()=>makeCube(source),/incompatível/);
  assert.throws(()=>makeCube({...pf,dims:{...pf.dims,person:'PJ'}}),/incompatíveis/);
  assert.throws(()=>makeCube({...pf,rows:[[0,0,0,0,null,1]]}),/incompatível/);
});
