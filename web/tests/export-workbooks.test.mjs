import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import JSZip from 'jszip';
import PptxGenJS from 'pptxgenjs';
import {buildPptx,repairPptxChartWorkbooks} from '../src/export.js';
import {filterChart} from '../src/data.js';

async function embedded(zip){
 const path=Object.keys(zip.files).find(name=>/^ppt\/embeddings\/.*\.xlsx$/.test(name));
 return {path,zip:await JSZip.loadAsync(await zip.file(path).async('uint8array'))};
}
const cell=(xml,ref)=>xml.match(new RegExp(`<c\\b[^>]*\\br="${ref}"[^>]*>[\\s\\S]*?<\\/c>`))?.[0];

test('native chart workbook preserves numeric zero and missing values on both axes',async()=>{
 const dates=['2026-01-31','2026-02-28','2026-03-31','2026-04-30'];
 const chart={id:'zero-null',title:'Valores e taxas',source:'BCB',unit:'R$ bi',axes:['R$ bi','%'],series:[
  {name:'Valor',type:'bar',axis:0,data:dates.map((d,i)=>[d,[0,null,-4,8][i]])},
  {name:'Taxa',type:'line',axis:1,data:dates.map((d,i)=>[d,[0,null,-2,12][i]])}
 ]};
 const {presentation}=buildPptx([chart],'Teste',PptxGenJS);
 const raw=await presentation.write({outputType:'arraybuffer'});
 const bytes=await repairPptxChartWorkbooks(raw);
 const original=await JSZip.loadAsync(raw),repaired=await JSZip.loadAsync(bytes);
 const before=await embedded(original),after=await embedded(repaired);
 const xml=await after.zip.file('xl/worksheets/sheet1.xml').async('string');
 assert.match(cell(xml,'B2'),/<v>0<\/v>/);assert.match(cell(xml,'C2'),/<v>0<\/v>/);
 assert.doesNotMatch(cell(xml,'B2'),/\bt=/);assert.doesNotMatch(cell(xml,'C2'),/\bt=/);
 assert.match(cell(xml,'B3'),/<v\s*\/>|<v>\s*<\/v>/);assert.match(cell(xml,'C3'),/<v\s*\/>|<v>\s*<\/v>/);
 assert.match(cell(xml,'B4'),/<v>-4<\/v>/);assert.match(cell(xml,'C4'),/<v>-0\.02<\/v>/);
 assert.match(cell(xml,'B5'),/<v>8<\/v>/);assert.match(cell(xml,'C5'),/<v>0\.12<\/v>/);
 // The entire presentation is unchanged except the native worksheet package.
 assert.deepEqual(Object.keys(repaired.files).sort(),Object.keys(original.files).sort());
 for(const [path,entry] of Object.entries(original.files)){
  if(entry.dir||path===before.path)continue;
  assert.deepEqual(await repaired.file(path).async('uint8array'),await entry.async('uint8array'),path);
 }
 for(const [path,entry] of Object.entries(before.zip.files)){
  if(entry.dir||['xl/worksheets/sheet1.xml','xl/styles.xml'].includes(path))continue;
  assert.deepEqual(await after.zip.file(path).async('uint8array'),await entry.async('uint8array'),path);
 }
 const previousStyles=await before.zip.file('xl/styles.xml').async('string'),styles=await after.zip.file('xl/styles.xml').async('string');
 const fontNames=xml=>[...xml.matchAll(/<name\b[^>]*\bval="([^"]*)"/g)].map(match=>match[1]);
 assert.ok(fontNames(styles).length>0&&fontNames(styles).every(name=>name==='Calibri'));
 const withoutNames=xml=>xml.replace(/(<name\b[^>]*\bval=")[^"]*(")/g,'$1FONT$2');
 assert.equal(withoutNames(styles),withoutNames(previousStyles),'all non-font styles and number formats stay byte-identical');
 const chartPath=Object.keys(repaired.files).find(path=>/^ppt\/charts\/chart\d+\.xml$/.test(path));
 const native=await repaired.file(chartPath).async('string');
 assert.match(native,/<c:barChart>/);assert.match(native,/<c:lineChart>/);
 assert.equal((native.match(/<c:valAx>/g)||[]).length,2);assert.match(native,/formatCode="0\.0%"/);
 assert.equal(await repairPptxChartWorkbooks(bytes),bytes,'already-correct packages require no rewrite');
});

test('real Comercial default-window zeros survive the embedded workbook without changing the chart',async()=>{
 const charts=JSON.parse(await readFile(new URL('../public/data/imob-br.json',import.meta.url),'utf8'));
 const chart=filterChart(charts.find(c=>c.id==='estoque_inadimplencia_pj'),'12');
 const {presentation}=buildPptx([chart],'Mercado Imobiliário',PptxGenJS);
 const raw=await presentation.write({outputType:'arraybuffer'});
 const original=await JSZip.loadAsync(raw),repaired=await JSZip.loadAsync(await repairPptxChartWorkbooks(raw));
 const workbook=await embedded(repaired),xml=await workbook.zip.file('xl/worksheets/sheet1.xml').async('string');
 for(const ref of ['E4','E5','E6','E7','E8'])assert.match(cell(xml,ref),/<v>0<\/v>/,ref);
 for(const path of Object.keys(original.files).filter(p=>/^ppt\/charts\/chart\d+\.xml$/.test(p)))
  assert.equal(await repaired.file(path).async('string'),await original.file(path).async('string'));
});

test('zero-free workbooks use Calibri while formulas, cached values and missing cells remain byte-identical',async()=>{
 const chart={id:'formula-fonts',title:'Dados',source:'BCB',unit:'R$ milhões',series:[{name:'Crédito',type:'line',data:[['2026-01-31',4],['2026-02-28',null],['2026-03-31',8]]}]};
 const {presentation}=buildPptx([chart],'Teste',PptxGenJS);
 const outer=await JSZip.loadAsync(await presentation.write({outputType:'arraybuffer'})),before=await embedded(outer);
 let xml=await before.zip.file('xl/worksheets/sheet1.xml').async('string');
 xml=xml.replace(cell(xml,'B4'),cell(xml,'B4').replace('<v>8</v>','<f>4*2</f><v>8</v>'));
 before.zip.file('xl/worksheets/sheet1.xml',xml);outer.file(before.path,await before.zip.generateAsync({type:'uint8array'}));
 const fixed=await JSZip.loadAsync(await repairPptxChartWorkbooks(await outer.generateAsync({type:'uint8array'}))),after=await embedded(fixed);
 assert.equal(await after.zip.file('xl/worksheets/sheet1.xml').async('string'),xml);
 const styles=await after.zip.file('xl/styles.xml').async('string');
 assert.ok([...styles.matchAll(/<name\b[^>]*\bval="([^"]*)"/g)].every(match=>match[1]==='Calibri'));
 assert.match(cell(xml,'B4'),/<f>4\*2<\/f><v>8<\/v>/);
 assert.match(cell(xml,'B3'),/<v\s*\/>|<v>\s*<\/v>/);
});
