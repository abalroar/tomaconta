import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {geoArea,geoBounds,geoMercator,geoPath} from 'd3-geo';
import {
  validateNetwork,networkSummary,municipalityBanks,findNetworkMunicipalities,
  networkAnalysisBank,networkGeometryForD3,normalizeSearch,networkPosition,
} from '../src/network-data.js';

const read=async path=>JSON.parse(await readFile(new URL(`../public/data/${path}`,import.meta.url),'utf8'));
const [network,geometry,catalog]=await Promise.all(['bank-network.json','bank-network-ufs.geojson','institutions.json'].map(read));

test('interface accepts the complete real network including one unavailable zero point and reconciles national statistics',()=>{
  const before=structuredClone(network);
  assert.equal(validateNetwork(network),network);
  assert.deepEqual(networkSummary(network),{branches:12818,municipalities:2885,singleBankMunicipalities:1080});
  const absent=network.municipalities.filter(city=>city.lon===null||city.lat===null);
  assert.deepEqual(absent.map(city=>[city.ibge,city.total]),[['4121356',0]]);
  assert.equal(networkPosition(network.position),'05/11/2026');
  assert.equal(networkPosition(null),'N/D');
  assert.deepEqual(network,before);
});

test('interface rejects duplicate identities, unknown banks and a positive point without valid geography',()=>{
  const duplicateBank={...network,banks:[...network.banks,network.banks[0]]};
  assert.throws(()=>validateNetwork(duplicateBank),/identidade/);
  const duplicateCity={...network,municipalities:[...network.municipalities,network.municipalities[0]]};
  assert.throws(()=>validateNetwork(duplicateCity),/município/);
  const city=network.municipalities.find(city=>city.total>0);
  const missing={...network,municipalities:network.municipalities.map(item=>item.ibge===city.ibge?{...item,lon:null,lat:null}:item)};
  assert.throws(()=>validateNetwork(missing),/município/);
  const unknown={...network,municipalities:network.municipalities.map(item=>item.ibge===city.ibge?{...item,banks:{...item.banks,'99999999':1},total:item.total+1}:item)};
  assert.throws(()=>validateNetwork(unknown),/distribuição municipal/);
});

test('municipal and bank views retain source counts, sorted institutions, real zero and unavailable identity',()=>{
  assert.deepEqual(networkSummary(network,'00000000'),{branches:3909,municipalities:2290,singleBankMunicipalities:network.municipalities.filter(city=>city.banks['00000000']>0&&city.bankCount===1).length});
  assert.deepEqual(networkSummary(network,'not-published'),{branches:null,municipalities:0,singleBankMunicipalities:0});
  const zero=network.municipalities.find(city=>city.total===0&&city.lon!==null);
  assert.deepEqual(municipalityBanks(network,zero),[]);
  const saoPaulo=network.municipalities.find(city=>city.ibge==='3550308');
  const listed=municipalityBanks(network,saoPaulo);
  assert.equal(listed.length,102);
  assert.equal(listed.reduce((total,row)=>total+row.count,0),1022);
  assert.ok(listed.every((row,index)=>!index||listed[index-1].count>=row.count));
  assert.deepEqual(listed.map(row=>[row.bank.idCnpjBase,row.count]),Object.entries(saoPaulo.banks).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])));
  const observedZero={...network,banks:[...network.banks,{idCnpjBase:'99999999',count:0,municipalities:0}]};
  assert.equal(networkSummary(observedZero,'99999999').branches,0);
});

test('search normalizes accents and treats official UF and seven-digit municipality codes as exact identities',()=>{
  assert.equal(normalizeSearch('  SÃO   PAULO '),'sao paulo');
  assert.equal(findNetworkMunicipalities(network,'SÃO PAULO')[0].ibge,'3550308');
  assert.equal(findNetworkMunicipalities(network,'sao paulo sp')[0].ibge,'3550308');
  assert.deepEqual(findNetworkMunicipalities(network,'3550308').map(city=>city.ibge),['3550308']);
  assert.deepEqual(findNetworkMunicipalities(network,'355030'),[]);
  assert.deepEqual(findNetworkMunicipalities(network,'9999999'),[]);
  assert.deepEqual(findNetworkMunicipalities(network,'  '),[]);
  for(const [query,count]of [['SP',645],['es',78],['DF',1]]){
    const found=findNetworkMunicipalities(network,query,6000);
    assert.equal(found.length,count,query);
    assert.ok(found.every(city=>city.uf===query.toUpperCase()));
  }
  assert.equal(findNetworkMunicipalities(network,'SP',3).length,3);
  assert.equal(findNetworkMunicipalities(network,'rio rj',8)[0].ibge,'3304557');
});

test('all 100 official links retain prudential identity and reject individual, missing or contradicted group codes',()=>{
  const linked=network.banks.filter(bank=>bank.analysisLink);
  assert.equal(linked.length,100);
  for(const bank of linked){
    const analysis=networkAnalysisBank(bank,catalog);
    assert.equal(analysis.id,bank.analysisLink.analysisId);
    assert.equal(analysis.perimeter,'Prudencial');
  }
  const unavailable=network.banks.filter(bank=>bank.analysisLink===null);
  assert.equal(unavailable.length,39);
  assert.ok(unavailable.every(bank=>networkAnalysisBank(bank,catalog)===null));
  const itau=network.banks.find(bank=>bank.idCnpjBase==='60701190');
  const wrong={...itau,analysisLink:{...itau.analysisLink,code:'C0080075',statementId:'prudential-C0080075'}};
  assert.equal(networkAnalysisBank(wrong,catalog),null);
  const individual={...itau,analysisLink:{...itau.analysisLink,scope:'individual',code:'60701190',statementId:'individual-60701190'}};
  assert.equal(networkAnalysisBank(individual,catalog),null);
  const invalidPerimeter={institutions:catalog.institutions.map(bank=>bank.id===itau.analysisLink.analysisId?{...bank,perimeter:'Individual'}:bank)};
  assert.equal(networkAnalysisBank(itau,invalidPerimeter),null);
});

test('27 IBGE state geometries normalize D3 winding to Brazilian land and fit the viewport rather than the world',()=>{
  const before=structuredClone(geometry);
  const normalized=networkGeometryForD3(geometry);
  assert.equal(normalized.features.length,27);
  assert.deepEqual(new Set(normalized.features.map(feature=>feature.properties.uf)),new Set(geometry.features.map(feature=>feature.properties.uf)));
  assert.ok(geoArea(normalized)>.19&&geoArea(normalized)<.23);
  assert.ok(normalized.features.every(feature=>geoArea(feature)>0&&geoArea(feature)<.1));
  const [[west,south],[east,north]]=geoBounds(normalized);
  assert.ok(west>-74.1&&west<-73&&east>-35&&east<-34&&south>-34&&south<-33&&north>5&&north<6);
  const projection=geoMercator().fitExtent([[20,20],[1180,680]],normalized);
  const path=geoPath(projection);
  const [[left,top],[right,bottom]]=path.bounds(normalized);
  assert.ok(left>=20-1e-8&&top>=20-1e-8&&right<=1180+1e-8&&bottom<=680+1e-8);
  assert.ok(right-left>500&&bottom-top>600);
  assert.ok(normalized.features.every(feature=>path(feature).startsWith('M')&&!path(feature).includes('NaN')));
  assert.deepEqual(geometry,before);
  assert.throws(()=>networkGeometryForD3({type:'Point',coordinates:[0,0]}),/Geografia/);
});
