import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const read=async path=>JSON.parse(await readFile(new URL(`../public/data/${path}`,import.meta.url),'utf8'));
const [network,catalog,crosswalk]=await Promise.all(['bank-network.json','institutions.json','statements/crosswalk.json'].map(read));

test('network snapshot covers only the declared three bank segments and retains its source position',()=>{
  assert.equal(network.schemaVersion,1);
  assert.equal(network.position,'2026-11-05');
  assert.equal(network.unit,'agências');
  assert.deepEqual(network.segments,['Banco Comercial','Banco Múltiplo','Caixa Econômica Federal']);
  assert.equal(network.banks.length,139);
  assert.equal(network.checks.sourceRecords,13574);
  assert.equal(network.checks.sourceCnpjBases,639);
  assert.equal(network.checks.selectedRecords,12818);
  assert.equal(network.checks.duplicateFullCnpj,0);
  assert.ok(network.banks.every(bank=>network.segments.includes(bank.segment)&&/^\d{8}$/.test(bank.idCnpjBase)));
  assert.equal(new Set(network.banks.map(bank=>bank.idCnpjBase)).size,139);
});

test('municipal, bank and UF totals independently reconcile to 12818 branch records',()=>{
  const counts=new Map(),municipalities=new Map(),ufs=new Map();
  for(const municipality of network.municipalities){
    assert.equal(municipality.total,Object.values(municipality.banks).reduce((sum,count)=>sum+count,0),municipality.ibge);
    assert.equal(municipality.bankCount,Object.keys(municipality.banks).length,municipality.ibge);
    for(const [cnpj,count]of Object.entries(municipality.banks)){
      assert.ok(Number.isInteger(count)&&count>0);
      counts.set(cnpj,(counts.get(cnpj)||0)+count);
      municipalities.set(cnpj,(municipalities.get(cnpj)||0)+1);
      const key=cnpj+':'+municipality.uf;ufs.set(key,(ufs.get(key)||0)+count);
    }
  }
  for(const bank of network.banks){
    assert.equal(bank.count,counts.get(bank.idCnpjBase),bank.idCnpjBase);
    assert.equal(bank.municipalities,municipalities.get(bank.idCnpjBase),bank.idCnpjBase);
    for(const [uf,count]of Object.entries(bank.ufCounts))assert.equal(count,ufs.get(bank.idCnpjBase+':'+uf));
    assert.equal(Object.values(bank.ufCounts).reduce((sum,count)=>sum+count,0),bank.count);
  }
  assert.equal([...counts.values()].reduce((sum,count)=>sum+count,0),12818);
  assert.equal(network.banks.reduce((sum,bank)=>sum+bank.count,0),12818);
  assert.equal(network.checks.mappedAgencies,12818);
  assert.equal(network.checks.unmappedAgencies,0);
  assert.deepEqual(network.unmappedMunicipalities,[]);
  assert.equal(network.checks.reconciled,true);
});

test('territorial points are municipal aggregates and distinguish zero coverage from unavailable geometry',()=>{
  assert.equal(network.municipalities.length,5571);
  assert.equal(new Set(network.municipalities.map(municipality=>municipality.ibge)).size,5571);
  assert.equal(network.municipalities.filter(municipality=>municipality.total>0).length,2885);
  assert.equal(network.municipalities.filter(municipality=>municipality.total===0).length,2686);
  assert.equal(network.municipalities.filter(municipality=>municipality.bankCount===1).length,1080);
  assert.equal(new Set(network.municipalities.map(municipality=>municipality.uf)).size,27);
  assert.ok(network.municipalities.filter(municipality=>municipality.total>0).every(municipality=>Number.isFinite(municipality.lon)&&Number.isFinite(municipality.lat)));
  assert.equal(network.checks.unavailablePointAgencies,0);
  assert.deepEqual(network.checks.codeMappings,{'exact-7-digit':12818});
  const unavailable=network.municipalities.filter(municipality=>municipality.lon==null||municipality.lat==null);
  assert.deepEqual(unavailable.map(municipality=>[municipality.ibge,municipality.total,municipality.lon,municipality.lat]),[['4121356',0,null,null]]);
  assert.deepEqual(unavailable[0].banks,{});
  assert.match(network.methods.point,/Não representa endereço de agência/);
});

test('five largest banks and representative cities retain exact CNPJ identities and observed counts',()=>{
  assert.deepEqual(network.banks.slice(0,5).map(bank=>[bank.idCnpjBase,bank.count,bank.municipalities]),[
    ['00000000',3909,2290],['00360305',2986,1622],['60746948',1899,1125],['60701190',1170,683],['90400888',1075,562],
  ]);
  assert.equal(network.checks.fiveLargestAgencies,11039);
  assert.ok(Math.abs(network.checks.fiveLargestSharePct-11039/12818*100)<1e-8);
  const saoPaulo=network.municipalities.find(municipality=>municipality.ibge==='3550308');
  assert.deepEqual([saoPaulo.name,saoPaulo.uf,saoPaulo.total,saoPaulo.bankCount],['São Paulo','SP',1022,102]);
});

test('all available analysis links use official individual-to-group membership and the existing unique crosswalk',()=>{
  const linked=network.banks.filter(bank=>bank.analysisLink);
  assert.equal(linked.length,100);
  assert.equal(network.checks.analysisLinks,100);
  assert.deepEqual(network.checks.analysisLinkStatuses,{linked:100,'no-compatible-analysis':39});
  for(const bank of linked){
    const link=bank.analysisLink;
    assert.equal(link.scope,'prudential');
    assert.equal(link.effectivePeriod,'202606');
    assert.equal(link.statementId,'prudential-'+link.code);
    assert.equal(link.sourceSha256,network.sources.ifdataMembership.sources.individual.sha256);
    const matching=Object.entries(crosswalk.links).filter(([,entry])=>entry.statementId===link.statementId&&entry.scope===link.scope&&entry.code===link.code);
    assert.equal(matching.length,1);
    assert.equal(matching[0][0],link.analysisId);
    assert.equal(catalog.institutions.find(institution=>institution.id===link.analysisId).perimeter,'Prudencial');
    assert.match(link.method,/CNPJ-base = c33; c15/);
  }
  assert.equal(network.banks.find(bank=>bank.idCnpjBase==='60701190').analysisLink.analysisId,'5f6d3c0745685d8f');
  assert.ok(network.banks.filter(bank=>!bank.analysisLink).every(bank=>bank.analysisLink===null&&bank.analysisLinkStatus==='no-compatible-analysis'));
});

test('IBGE geometry asset and official-source provenance have stable hashes and pagination evidence',async()=>{
  const bytes=await readFile(new URL('../public/'+network.geometry.path,import.meta.url));
  assert.equal(bytes.length,network.geometry.bytes);
  assert.equal(createHash('sha256').update(bytes).digest('hex'),network.geometry.sha256);
  const geo=JSON.parse(bytes);
  assert.equal(geo.type,'FeatureCollection');
  assert.equal(geo.features.length,27);
  assert.equal(new Set(geo.features.map(feature=>feature.properties.uf)).size,27);
  assert.ok(geo.features.every(feature=>['Polygon','MultiPolygon'].includes(feature.geometry.type)));
  const source=network.sources.agencies;
  assert.equal(source.license,'ODbL-1.0');
  assert.equal(source.pages.length,14);
  assert.equal(source.pages.reduce((sum,page)=>sum+page.rows,0),13574);
  assert.equal(source.pages.at(-1).rows,574);
  assert.ok(source.pages.every((page,index)=>page.skip===index*1000&&/^[a-f0-9]{64}$/.test(page.sha256)));
  assert.equal(network.sources.stateGeometry.license,'CC-BY-4.0');
  assert.match(network.sources.stateGeometry.url,/servicodados\.ibge\.gov\.br\/api\/v4\/malhas/);
});
