import {COLORS,dateLabel,periodOf,chartCategories,axisUnits,seriesAxis,percentAxis} from './data.js';
export function chartDataForPptx(chart){const dates=chartCategories(chart);return chart.series.map(s=>({name:s.name,labels:dates.map(dateLabel),values:dates.map(d=>{const v=s.data.find(p=>p[0]===d)?.[1];return v==null?null:percentAxis(chart,seriesAxis(chart,s))?v/100:v;})}));}
export function addChartForPptx(slide,types,chart,options={}){
 const prepared=chartDataForPptx(chart),groups=[];
 chart.series.forEach((series,index)=>{
  const axis=seriesAxis(chart,series),type=series.type==='bar'?'bar':'line';let group=groups.find(g=>g.axis===axis&&g.kind===type);
  if(!group){group={axis,kind:type,type:types[type],data:[],options:{secondaryValAxis:axis===1,secondaryCatAxis:axis===1,chartColors:[]}};groups.push(group);}
  group.data.push(prepared[index]);group.options.chartColors.push(COLORS[index%COLORS.length].slice(1));
 });
 const axes=axisUnits(chart),format=axis=>percentAxis(chart,axis)?'0.0%':'#,##0.0';
 const opts={...options,valAxisLabelFormatCode:format(0),showValAxisTitle:false,lineDataSymbol:'none',lineDataSymbolSize:2,valGridLine:{color:'E5E5E5',size:.5},valAxisLineColor:'CCCCCC',catAxisLineColor:'CCCCCC',valAxisLineSize:.5,catAxisLineSize:.5};
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
 await presentation.writeFile({fileName});return {total:coverage.total,exported:coverage.ready.length,complete:coverage.complete,missing:coverage.missing.map(c=>({id:c.id,title:c.title,section:c.section}))};
}
