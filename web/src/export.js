import {COLORS,dateLabel,periodOf,chartCategories,axisUnits,seriesAxis,percentAxis,download} from './data.js';

const xmlText=value=>value.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&amp;/g,'&');
const xmlAttribute=(tag,name)=>xmlText(tag.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1]||'');
function partPath(owner,target){
 const parts=target.startsWith('/')?[]:owner.split('/').slice(0,-1);
 for(const part of target.split('/')){if(part==='..')parts.pop();else if(part&&part!=='.')parts.push(part);}
 return parts.join('/');
}
const relationshipsPath=part=>part.replace(/([^/]+)$/,'_rels/$1.rels');
function relationship(xml,id){return [...xml.matchAll(/<Relationship\b[^>]*\/>/g)].map(match=>match[0]).find(tag=>xmlAttribute(tag,'Id')===id&&xmlAttribute(tag,'TargetMode')!=='External');}

// PptxGenJS 4.0.1 writes `value || ''` into ordinary chart worksheets,
// losing numeric zeros there while its native chart cache correctly keeps 0.
// Repair only those empty numeric cells identified by the cache's formula and
// point index. Missing observations, formulas and nonzero values stay intact.
// These XML forms belong to our generated OOXML, not to user-supplied documents.
export async function repairPptxChartWorkbooks(bytes){
 const {default:JSZip}=await import('jszip');
 const zip=await JSZip.loadAsync(bytes),workbooks=new Map();let changed=false;
 for(const entry of zip.file(/^ppt\/charts\/chart\d+\.xml$/)){
  const chart=await entry.async('string'),zeros=[];
  for(const [,reference] of chart.matchAll(/<c:numRef>([\s\S]*?)<\/c:numRef>/g)){
   const formula=xmlText(reference.match(/<c:f>([^<]*)<\/c:f>/)?.[1]||'');
   const range=/^('(?:[^']|'')*'|[^!]+)!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)$/.exec(formula);
   if(!range||range[2]!==range[4])continue;
   const sheet=range[1].replace(/^'|'$/g,'').replaceAll("''","'"),first=Number(range[3]),last=Number(range[5]);
   const cache=reference.match(/<c:numCache>([\s\S]*?)<\/c:numCache>/)?.[1]||'';
   for(const [,index,value] of cache.matchAll(/<c:pt idx="(\d+)">\s*<c:v>([^<]*)<\/c:v>\s*<\/c:pt>/g)){
    const row=first+Number(index);
    if(value.trim()!==''&&Number(value)===0&&row<=last)zeros.push({sheet,cell:range[2]+row});
   }
  }
  if(!zeros.length)continue;
  const externalId=chart.match(/<c:externalData\b[^>]*\br:id="([^"]+)"/)?.[1];
  const rels=zip.file(relationshipsPath(entry.name));
  if(!externalId||!rels)throw new Error('Não foi possível conferir a planilha do gráfico. Tente novamente.');
  const link=relationship(await rels.async('string'),externalId);
  if(!link)throw new Error('Planilha do gráfico não encontrada. Tente novamente.');
  const workbookPath=partPath(entry.name,xmlAttribute(link,'Target'));
  let state=workbooks.get(workbookPath);
  if(!state){
   const embedded=zip.file(workbookPath);
   if(!embedded)throw new Error('Planilha do gráfico não encontrada. Tente novamente.');
   const workbook=await JSZip.loadAsync(await embedded.async('uint8array'));
   const definition=await workbook.file('xl/workbook.xml').async('string');
   const links=await workbook.file('xl/_rels/workbook.xml.rels').async('string');
   state={workbook,sheets:new Map(),changed:false};
   for(const [tag] of definition.matchAll(/<sheet\b[^>]*\/>/g)){
    const sheetLink=relationship(links,xmlAttribute(tag,'r:id'));
    if(sheetLink)state.sheets.set(xmlAttribute(tag,'name'),{path:partPath('xl/workbook.xml',xmlAttribute(sheetLink,'Target')),xml:null,changed:false});
   }
   workbooks.set(workbookPath,state);
  }
  for(const {sheet,cell} of zeros){
   const target=state.sheets.get(sheet);
   if(!target)throw new Error('A referência do gráfico não corresponde à planilha. Tente novamente.');
   target.xml??=await state.workbook.file(target.path).async('string');
   target.xml=target.xml.replace(new RegExp(`<c\\b[^>]*\\br="${cell}"[^>]*>[\\s\\S]*?<\\/c>`),element=>{
    const type=xmlAttribute(element.slice(0,element.indexOf('>')+1),'t');
    if((type&&type!=='n')||/<f\b/.test(element))return element;
    const repaired=element.replace(/<v\s*\/>|<v>\s*<\/v>/,'<v>0</v>');
    if(repaired!==element){target.changed=true;state.changed=true;changed=true;}
    return repaired;
   });
  }
 }
 if(!changed)return bytes;
 for(const [path,state] of workbooks){
  if(!state.changed)continue;
  for(const sheet of state.sheets.values())if(sheet.changed)state.workbook.file(sheet.path,sheet.xml);
  zip.file(path,await state.workbook.generateAsync({type:'uint8array',compression:'DEFLATE'}));
 }
 return zip.generateAsync({type:'uint8array',compression:'DEFLATE'});
}
export function chartDataForPptx(chart){const dates=chartCategories(chart);return chart.series.map(s=>({name:s.name,labels:dates.map(dateLabel),values:dates.map(d=>{const v=s.data.find(p=>p[0]===d)?.[1];return v==null?null:percentAxis(chart,seriesAxis(chart,s))?v/100:v;})}));}
export function addChartForPptx(slide,types,chart,options={}){
 const prepared=chartDataForPptx(chart),groups=[];
 chart.series.forEach((series,index)=>{
  const axis=seriesAxis(chart,series),type=series.type==='bar'?'bar':'line';let group=groups.find(g=>g.axis===axis&&g.kind===type);
  if(!group){group={axis,kind:type,type:types[type],data:[],options:{secondaryValAxis:axis===1,secondaryCatAxis:axis===1,chartColors:[]}};groups.push(group);}
  group.data.push(prepared[index]);group.options.chartColors.push(COLORS[index%COLORS.length].slice(1));
 });
 const axes=axisUnits(chart),format=axis=>percentAxis(chart,axis)?'0.0%':'#,##0.0';
 const opts={...options,dataLabelFontFace:'Calibri',valAxisLabelFormatCode:format(0),showValAxisTitle:false,lineDataSymbol:'none',lineDataSymbolSize:2,valGridLine:{color:'E5E5E5',size:.5},valAxisLineColor:'CCCCCC',catAxisLineColor:'CCCCCC',valAxisLineSize:.5,catAxisLineSize:.5};
 if(axes.length>1){opts.valAxes=axes.map((unit,axis)=>({showValAxisTitle:false,valAxisLabelFormatCode:format(axis),valAxisLabelFontFace:'Calibri',valAxisLabelFontSize:7,valGridLine:axis===0?{color:'E5E5E5',size:.5}:{style:'none'},axisPos:axis===1?'r':'l'}));opts.catAxes=[{catAxisLabelPos:'low'},{catAxisHidden:true,catAxisLabelPos:'none'}];}
 const native=groups.map(({axis,kind,...group})=>group);
 if(native.length===1)slide.addChart(native[0].type,native[0].data,opts);else slide.addChart(native,opts);
}
export function coverageForCharts(charts){const ready=charts.filter(c=>c.series.some(s=>s.data.some(p=>p[1]!=null&&Number.isFinite(Number(p[1])))));return {total:charts.length,ready,missing:charts.filter(c=>!ready.includes(c)),complete:ready.length===charts.length};}
export function chartTitleForPptx(c){const title=c.title.replace(/<[^>]*>/g,'');return c.section&&(/mercadoimobiliario/i.test(c.source)||/^(contratacao_|estoque_|imoveis_)/.test(c.id))?`${title} · ${c.section}`:title;}
export function buildPptx(charts,title,PptxGenJS){
 const coverage=coverageForCharts(charts),ready=coverage.ready;if(!ready.length)throw new Error('Nenhum gráfico possui dados no intervalo selecionado.');
 const p=new PptxGenJS();p.layout='LAYOUT_WIDE';p.author='Toma Conta';p.subject='Dados oficiais do Banco Central';p.title=title;p.company='Toma Conta';p.lang='pt-BR';p.theme={headFontFace:'Calibri',bodyFontFace:'Calibri',lang:'pt-BR'};
 const label=coverage.complete?`${ready.length} gráficos · Banco Central do Brasil`:`Exportação parcial · ${ready.length} de ${charts.length} gráficos`;
 const cover=p.addSlide();cover.background={color:'FFFFFF'};cover.addText('TOMA CONTA',{x:.5,y:.5,w:11,h:.3,fontFace:'Calibri',fontSize:13,color:'777777'});cover.addText(title,{x:.5,y:2,w:12,h:1,fontFace:'Calibri',fontSize:32,bold:true,color:'111111'});cover.addText(label,{x:.5,y:3.2,w:12,h:.4,fontSize:16,color:'666666'});cover.addText('Recorte e fonte indicados em cada gráfico. Elementos editáveis.'+(!coverage.complete?' Gráficos sem dados relacionados ao final.':''),{x:.5,y:6.5,w:12,h:.4,fontSize:10,color:'777777'});
 for(let i=0;i<ready.length;i+=4){const slide=p.addSlide();slide.background={color:'FFFFFF'};slide.addText(title,{x:.35,y:.12,w:12,h:.25,fontFace:'Calibri',fontSize:10,color:'888888'});
  for(const [j,c] of ready.slice(i,i+4).entries()){const x=.4+(j%2)*6.55,y=.6+Math.floor(j/2)*3.35;slide.addText(chartTitleForPptx(c),{x,y,w:6.1,h:.35,fontSize:13,bold:true,color:'111111',breakLine:false});slide.addText(`${axisUnits(c).join(' / ')} · ${c.source} · ${periodOf(c)}`,{x,y:y+.38,w:6.1,h:.35,fontSize:7.5,color:'888888'});
   addChartForPptx(slide,p.ChartType,c,{x,y:y+.85,w:6.1,h:2.35,showTitle:false,showLegend:true,legendPos:'b',legendFontSize:7,catAxisLabelFontFace:'Calibri',catAxisLabelFontSize:7,valAxisLabelFontFace:'Calibri',valAxisLabelFontSize:7,chartColors:COLORS.map(v=>v.slice(1)),showValue:false,lineSize:1.5,showCatName:false,catAxisLabelRotate:0,showBorder:false,showSerName:false,showLeaderLines:false,barDir:'col',barGrouping:c.stacked?'stacked':'clustered',displayBlanksAs:'gap',showLegendKey:false,showPercent:false,layout:{x:.12,y:.08,w:.83,h:.72}});
  }
 }
 for(let i=0;i<coverage.missing.length;i+=12){const slide=p.addSlide();slide.background={color:'FFFFFF'};slide.addText('Cobertura da exportação parcial',{x:.5,y:.4,w:12,h:.5,fontFace:'Calibri',fontSize:24,bold:true,color:'111111'});slide.addText('Gráficos sem observações no intervalo selecionado:',{x:.5,y:1,w:12,h:.3,fontSize:12,color:'666666'});coverage.missing.slice(i,i+12).forEach((c,j)=>slide.addText(`${c.section||'Seção não informada'} · ${c.title.replace(/<[^>]*>/g,'')}`,{x:.5,y:1.5+j*.43,w:12,h:.4,fontFace:'Calibri',fontSize:12,color:'333333'}));}
 const fileName='Toma_Conta_'+(coverage.complete?'':'Parcial_')+title.replace(/[^\p{L}\p{N}]+/gu,'_')+'.pptx';
 return {presentation:p,coverage,fileName};
}
export async function exportPptx(charts,title='Toma Conta'){
 const {default:PptxGenJS}=await import('pptxgenjs');const {presentation,coverage,fileName}=buildPptx(charts,title,PptxGenJS);
 const bytes=await repairPptxChartWorkbooks(await presentation.write({outputType:'arraybuffer'}));
 download(new Blob([bytes],{type:'application/vnd.openxmlformats-officedocument.presentationml.presentation'}),fileName);
 return {total:coverage.total,exported:coverage.ready.length,complete:coverage.complete,missing:coverage.missing.map(c=>({id:c.id,title:c.title,section:c.section}))};
}
