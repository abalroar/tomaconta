import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {filterChart,periodOf,chartOption,chartCategories,number,seriesUnit} from '../src/data.js';
import {chartDataForPptx,addChartForPptx,coverageForCharts,chartTitleForPptx,buildPptx} from '../src/export.js';

const read=async name=>JSON.parse(await readFile(new URL('../public/data/'+name,import.meta.url),'utf8'));
const chart=data=>({id:'test',title:'Test',unit:'%',percent:true,series:[{name:'Série',type:'line',data}]});

test('rolling uses calendar months when latest day31 targets month30',()=>{
 const c=chart([['2026-04-01',1],['2026-04-30',2],['2026-05-31',3]]);
 assert.deepEqual(filterChart(c,'2').series[0].data,c.series[0].data);
});

test('rolling March31 includes February and leap-yearFebruary',()=>{
 for(const year of [2024,2025]){
  const data=[[`${year}-01-31`,1],[`${year}-02-01`,2],[`${year}-02-${year===2024?'29':'28'}`,3],[`${year}-03-31`,4]];
  assert.deepEqual(filterChart(chart(data),'2').series[0].data,data.slice(1));
 }
});

test('twelve calendar months cross years and preserve internal nulls',()=>{
 const data=[['2024-12-31',1],['2025-01-01',2],['2025-02-28',null],['2025-12-31',0]];
 assert.deepEqual(filterChart(chart(data),'12').series[0].data,data.slice(1));
});

test('trailing unpublished nulls do not move the rolling anchor',()=>{
 const c=chart([['2026-04-30',1],['2026-05-31',2],['2026-06-30',null]]);
 assert.deepEqual(filterChart(c,'2').series[0].data,c.series[0].data.slice(0,2));
 assert.equal(periodOf(c),'04/2026 a 05/2026');
});

test('explicit month interval is inclusive and may have no intersection',()=>{
 const c=chart([['2025-12-31',1],['2026-01-01',2],['2026-01-31',3],['2026-02-28',4]]);
 assert.deepEqual(filterChart(c,'interval','2026-01','2026-01').series[0].data,c.series[0].data.slice(1,3));
 assert.equal(filterChart(c,'interval','2027-01','2027-12').series[0].data.length,0);
 assert.equal(filterChart(c,'interval','2026-03','2026-01').series[0].data.length,0);
 assert.equal(periodOf(filterChart(c,'interval','2027-01','2027-12')),'Sem dados no período');
 assert.deepEqual(filterChart(c,'all','2026-01','2026-01').series[0].data,c.series[0].data);
});

test('filtering does not mutate source or siblingseries',()=>{
 const c=chart([['2025-12-31',null],['2026-01-31',0]]);const original=structuredClone(c);
 filterChart(c,'1');assert.deepEqual(c,original);
});

test('categoricalUF preserves source ordering and uses explicit competence',()=>{
 const c={...chart([['RO',11.5],['AC',7.3],['SP',8.2]]),latestPeriod:'2026-07'};
 assert.equal(filterChart(c,'12'),c);
 assert.equal(filterChart(c,'interval','2025-01','2025-12'),c);
 assert.deepEqual(chartCategories(c),['RO','AC','SP']);
 assert.deepEqual(chartOption(c).xAxis.data,['RO','AC','SP']);
 assert.equal(periodOf(c),'07/2026');
 assert.equal(periodOf({...c,latestPeriod:null}),'Recorte categórico');
});

test('missing points stay null in screen and nativeOffice values; zero stayszero',()=>{
 const c={...chart([['2026-01-31',0],['2026-02-28',null],['2026-03-31',12.3]]),series:[
  {name:'A',data:[['2026-01-31',0],['2026-02-28',null],['2026-03-31',12.3]]},
  {name:'B',data:[['2026-03-31',5]]}]};
 assert.deepEqual(chartOption(c).series[0].data,[0,null,12.3]);
 assert.equal(chartOption(c).series[0].connectNulls,false);
 assert.deepEqual(chartDataForPptx(c)[0].values,[0,null,.12300000000000001]);
 assert.deepEqual(chartDataForPptx(c)[1].values,[null,null,.05]);
 assert.equal(number(null),'N/D');assert.equal(number(''),'N/D');assert.equal(number(0),'0,0');
});

test('real riskseries endDecember2024 and rolling window follows their own competence',async()=>{
 const charts=await read('imob-br.json');const risk=charts.filter(c=>c.historical);
 assert.equal(risk.length,2);assert.ok(!charts.some(c=>/bndu/i.test(c.id+' '+c.title)));
 for(const c of risk){
  const dates=filterChart(c,'12').series.flatMap(s=>s.data.map(p=>p[0])).sort();
  assert.equal(dates.at(-1),'2024-12-31');assert.ok(dates[0]>='2024-01-01');
  assert.equal(filterChart(c,'interval','2026-01','2026-12').series.flatMap(s=>s.data).length,0);
 }
});

test('real SCR dataarepercentpoints and Office conversionhappensonce',async()=>{
 const charts=await read('extra.json');const regional=charts.find(c=>c.id==='scr-7');
 assert.equal(regional.unit,'%');assert.equal(regional.percent,true);assert.equal(periodOf(regional),'07/2026');
 assert.ok(regional.series[0].data.every(p=>/^[A-Z]{2}$/.test(p[0])));
 const values=regional.series[0].data.map(p=>p[1]);assert.ok(Math.max(...values)>1&&Math.max(...values)<100);
 const native=chartDataForPptx(regional)[0];assert.equal(native.values[0],values[0]/100);
});

test('real SPB monetaryunits are preserved; sharesaddto100%',async()=>{
 const charts=await read('extra.json');const money=charts.find(c=>c.id==='spb-mensal-valor');
 assert.equal(money.unit,'R$ milhões');assert.equal(money.percent,false);
 assert.deepEqual(chartDataForPptx(money)[0].values,money.series[0].data.map(p=>p[1]));
 for(const id of ['spb-participacao-valor','spb-participacao-quantidade']){
  const c=charts.find(c=>c.id===id);const totals=new Map();
  for(const s of c.series)for(const [d,v]of s.data)if(v!=null)totals.set(d,(totals.get(d)||0)+v);
  assert.ok([...totals.values()].every(v=>Math.abs(v-100)<1e-7));
 }
});

test('IF.data preserves sourcehash, financialscope, sourceunits and auditedJune2026 values',async()=>{
 const catalog=await read('institutions.json');assert.match(catalog.source.sha256,/^[a-f0-9]{64}$/);
 assert.equal(catalog.metrics.assets.unit,'R$');assert.equal(catalog.metrics.roe.unit,'%');assert.equal(catalog.metrics.roe.sourceScale,100);
 const bank=catalog.institutions.find(b=>b.key==='ITAU PRUDENCIAL');assert.ok(bank);assert.match(bank.perimeter,/prudencial/i);
 const h=await read(bank.historyPath.replace(/^data\//,''));const june=h.history.find(r=>r.period==='2026-Q2');
 assert.equal(june.date,'2026-06-30');assert.equal(june.values.assets,2846417632562.91);assert.equal(june.values.roe,20.66501736);
 assert.equal(june.values.cet1,12.30870927);assert.equal(h.history.length,bank.historyCount);
 assert.deepEqual(h.history.at(-1).values,bank.latest);
 assert.ok(catalog.institutions.some(b=>b.latest.cet1===null));
});

test('real concessoes-1 retains barBRL and line-months on separate screenandOfficeaxes',async()=>{
 const charts=await read('sfn.json');const c=filterChart(charts.find(c=>c.id==='concessoes-1'),'12');
 assert.deepEqual(c.axes,['R$ bi','meses']);const screen=chartOption(c);
 assert.equal(screen.yAxis.length,2);assert.deepEqual(screen.yAxis.map(a=>a.position),['left','right']);
 assert.equal(screen.series[0].type,'bar');assert.equal(screen.series[1].type,'line');assert.equal(screen.series[1].yAxisIndex,1);
 assert.equal(seriesUnit(c,c.series[0]),'R$ bi');assert.equal(seriesUnit(c,c.series[1]),'meses');
 const calls=[];addChartForPptx({addChart:(...args)=>calls.push(args)},{bar:'BAR',line:'LINE'},c,{x:1,y:1,w:6,h:3});
 assert.equal(calls.length,1);const [groups,options]=calls[0];
 assert.deepEqual(groups.map(g=>g.type),['BAR','LINE']);assert.equal(groups[1].options.secondaryValAxis,true);
 assert.equal(groups[1].options.secondaryCatAxis,true);assert.equal(options.valAxes.length,2);
 assert.deepEqual(options.valAxes.map(a=>a.valAxisTitle),['R$ bi','meses']);
 assert.deepEqual(groups[0].data[0].values,c.series[0].data.map(p=>p[1]));
 assert.deepEqual(groups[1].data[0].values,c.series[1].data.map(p=>p[1]));
});

test('percentconversionfollows each axisunit ratherthanwholechartflag',()=>{
 const c={...chart([['2026-01-31',100]]),unit:'R$ bi',percent:false,axes:['R$ bi','% a.a.'],series:[
  {name:'Valor',type:'bar',axis:0,data:[['2026-01-31',100]]},
  {name:'Taxa',type:'line',axis:1,data:[['2026-01-31',12]]}]};
 assert.deepEqual(chartDataForPptx(c).map(s=>s.values),[[100],[.12]]);
 assert.equal(chartOption(c).yAxis[0].axisLabel.formatter(12),'12');
 assert.equal(chartOption(c).yAxis[1].axisLabel.formatter(12),'12%');
 const calls=[];addChartForPptx({addChart:(...args)=>calls.push(args)},{bar:'BAR',line:'LINE'},c);
 assert.deepEqual(calls[0][1].valAxes.map(a=>a.valAxisLabelFormatCode),['#,##0.0','0.0%']);
});

test('nativeOfficeXML contains actual combocharts and twovaluescales',async()=>{
 const {default:PptxGenJS}=await import('pptxgenjs');const {default:JSZip}=await import('jszip');
 const c=filterChart((await read('sfn.json')).find(c=>c.id==='concessoes-1'),'12');
 const p=new PptxGenJS();p.layout='LAYOUT_WIDE';addChartForPptx(p.addSlide(),p.ChartType,c,{x:.5,y:.5,w:12,h:6});
 const bytes=await p.write({outputType:'nodebuffer'});const zip=await JSZip.loadAsync(bytes);
 const xml=await zip.file('ppt/charts/chart1.xml').async('string');
 assert.match(xml,/<c:barChart>/);assert.match(xml,/<c:lineChart>/);assert.equal((xml.match(/<c:valAx>/g)||[]).length,2);
 assert.match(xml,/R\$ bi/);assert.match(xml,/meses/);assert.match(xml,/<c:axPos val="r"/);
});

test('emptysecondaryunitfallstoexplicitprimarypercentageunit',()=>{
 const c={...chart([['2026-01-31',10]]),unit:'% da carteira',axes:['% da carteira',''],series:[{name:'Direita',axis:1,data:[['2026-01-31',10]]}]};
 assert.equal(seriesUnit(c,c.series[0]),'% da carteira');assert.deepEqual(chartDataForPptx(c)[0].values,[.1]);
});

test('partialexportsreportcoverageincoverfilenameandmissingsectionannex',async()=>{
 const {default:PptxGenJS}=await import('pptxgenjs');const {default:JSZip}=await import('jszip');
 const present={...chart([['2026-07-31',12]]),id:'contratacao_valor_pf',title:'Valor contratado',section:'Contratação · PF',source:'BCB · Olinda/MercadoImobiliario'};
 const absent={...chart([]),id:'estoque_risco_pf',title:'Risco da operação',section:'Estoque · PF',source:'BCB · Olinda/MercadoImobiliario'};
 const {presentation,coverage,fileName}=buildPptx([present,absent],'Mercado Imobiliário',PptxGenJS);
 assert.equal(coverage.total,2);assert.equal(coverage.ready.length,1);assert.equal(coverage.complete,false);assert.deepEqual(coverage.missing,[absent]);assert.match(fileName,/Parcial/);
 const zip=await JSZip.loadAsync(await presentation.write({outputType:'nodebuffer'}));
 const cover=await zip.file('ppt/slides/slide1.xml').async('string');const panel=await zip.file('ppt/slides/slide2.xml').async('string');const annex=await zip.file('ppt/slides/slide3.xml').async('string');
 assert.match(cover,/Exportação parcial/);assert.match(cover,/1 de 2 gráficos/);assert.match(panel,/Valor contratado · Contratação · PF/);
 assert.match(annex,/Estoque · PF · Risco da operação/);assert.equal(chartTitleForPptx(present),'Valor contratado · Contratação · PF');
});

test('emptyexportsabortandzeroisavalidobservation',()=>{
 const empty=chart([['2026-01-31',null]]);assert.throws(()=>buildPptx([empty],'Vazio',class{}),/Nenhum gráfico/);
 const zero=chart([['2026-01-31',0]]);assert.equal(coverageForCharts([zero]).complete,true);assert.equal(coverageForCharts([zero]).ready.length,1);
});
