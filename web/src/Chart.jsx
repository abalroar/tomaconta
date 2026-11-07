import React, {useEffect, useMemo, useRef, useState} from 'react';
import * as echarts from 'echarts';
import {axisUnits, chartOption, csvDownload, dateLabel, number, periodOf, seriesUnit, seriesAxis} from './data.js';
import {exportPptx} from './export.js';
import {chartLabel, chartTick, chartValue, showInnerLabel} from './chart-format.js';

export const WEB_CHART_COLORS = ['#315f78', '#bd7042', '#76589a', '#a68a2d', '#358572', '#a74f60', '#64717b', '#367caa'];
export const plainText = value => String(value ?? '').replace(/<[^>]*>/g, '').replaceAll('&amp;', '&');

export default function Chart({chart, height = 280, colors, compact = false, showLegend = true, valueLabels}) {
  const node = useRef(null);
  useEffect(() => {
    if (!node.current) return;
    const instance = echarts.init(node.current, null, {renderer: 'svg'});
    const option = chartOption(chart);
    const ink = '#213e50', muted = '#506a76';
    option.color = colors || chart.colors || WEB_CHART_COLORS;
    option.textStyle = {...option.textStyle, color: ink, fontSize: 11};
    option.legend = {...option.legend, show: showLegend, textStyle: {...option.legend.textStyle, color: muted, fontFamily: 'Hanken Grotesk Variable, Hanken Grotesk, Arial, sans-serif'}};
    option.tooltip = {...option.tooltip, backgroundColor: '#fff', borderColor: '#bdced3', textStyle: {color: ink, fontFamily: 'Hanken Grotesk Variable, Hanken Grotesk, Arial, sans-serif', fontSize: 12}};
    option.xAxis = {...option.xAxis, axisLabel: {...option.xAxis.axisLabel, color: muted, fontSize: 11}, axisLine: {lineStyle: {color: '#ccdadd'}}};
    option.yAxis = option.yAxis.map((axis, index) => ({...axis, scale:chart.series.some(series=>series.type==='bar'&&seriesAxis(chart,series)===index)?false:axis.scale, nameTextStyle: {...axis.nameTextStyle, color: muted}, axisLabel: {...axis.axisLabel, color: muted, fontSize: 11, formatter: value => chartTick(value)}, splitLine: {...axis.splitLine, lineStyle: {color: '#e0e8eb'}}}));
    const labelSettings = valueLabels === undefined ? chart.valueLabels : valueLabels;
    const totals = new Map(chart.totalData || []);
    const lastBar = option.series.findLastIndex(series => series.type === 'bar');
    option.series = option.series.map((series, index) => {
      const presented = {...series, label: {...series.label, show: false}, tooltip: {...series.tooltip, valueFormatter: value => chartValue(value, seriesUnit(chart, chart.series[index]))}};
      if (labelSettings && series.type === 'bar') {
        const total = labelSettings.total && index === lastBar;
        const inner = labelSettings.innerSeries === index;
        if (total || inner) {
          presented.label = {show: true, position: total ? 'top' : 'inside', color: total ? ink : '#fff', fontSize: 11, fontFamily: 'Hanken Grotesk Variable, Hanken Grotesk, Arial, sans-serif', ...(total ? {} : {backgroundColor: series.itemStyle?.color || option.color[index % option.color.length], padding: [1, 2], align: 'center'}), formatter: params => {
            if (!total) {
              const plotWidth = Math.max(0, (node.current?.clientWidth || 0) - Number(option.grid.left || 0) - Number(option.grid.right || 0));
              if (!showInnerLabel(params.dataIndex, option.xAxis.data.length, plotWidth)) return '';
            }
            return chartLabel(total ? totals.get(params.name ?? option.xAxis.data[params.dataIndex]) : params.value);
          }};
          presented.labelLayout = {hideOverlap: true};
        }
      }
      return presented;
    });
    if (compact) {
      option.legend = {...option.legend, bottom: undefined, top: 0, left: 0};
      option.grid = {...option.grid, left: 48, right: option.yAxis.length > 1 ? 48 : 12, top: showLegend ? 46 : 28, bottom: 28};
    }
    instance.setOption(option);
    let lastWidth = node.current.clientWidth;
    const resize = new ResizeObserver(() => {
      const width = node.current?.clientWidth || 0;
      instance.resize();
      if (labelSettings && width !== lastWidth) instance.setOption({series: option.series});
      lastWidth = width;
    });
    resize.observe(node.current);
    return () => {resize.disconnect(); instance.dispose();};
  }, [chart, colors, compact, showLegend, valueLabels]);
  return <div className="tc-chart" style={{height}} ref={node} role="img" aria-label={`${plainText(chart.title)}. ${axisUnits(chart).join(' / ')}. ${periodOf(chart)}.`}/>;
}

export function ChartPanel({chart}) {
  const [table, setTable] = useState(false);
  const [tablePage, setTablePage] = useState(0);
  const rows = useMemo(() => chart.series.flatMap((series, index) => series.data.map(([date, value]) => ({date, value, name: series.name, unit: seriesUnit(chart, series), key: `${index}-${date}`}))).reverse(), [chart]);
  useEffect(() => setTablePage(0), [chart]);
  const size = 50;
  const visibleRows = rows.slice(tablePage * size, (tablePage + 1) * size);
  const hasValues = rows.some(row => row.value != null && Number.isFinite(Number(row.value)));
  return <article className="tc-chart-panel">
    <header className="tc-chart-panel-heading">
      <div><h2>{plainText(chart.title)}</h2><p>{axisUnits(chart).join(' / ')}</p></div>
      <button type="button" className="tc-text-action" aria-label={`${table ? 'Ver gráfico' : 'Ver tabela'} de ${plainText(chart.title)}`} aria-pressed={table} onClick={() => setTable(!table)}>{table ? 'Gráfico' : 'Tabela'}</button>
    </header>
    {table ? <>
      <div className="tc-table-scroll"><table className="tc-data-table"><thead><tr><th>Data / categoria</th><th>Série</th><th>Valor</th><th>Unidade</th></tr></thead><tbody>{visibleRows.map(row => <tr key={row.key}><td>{dateLabel(row.date)}</td><td>{row.name}</td><td>{number(row.value, 2)}</td><td>{row.unit}</td></tr>)}</tbody></table></div>
      {rows.length > size && <div className="tc-table-pagination"><span>{tablePage * size + 1}–{Math.min(rows.length, (tablePage + 1) * size)} de {rows.length}</span><div><button type="button" disabled={!tablePage} onClick={() => setTablePage(tablePage - 1)}>Anterior</button><button type="button" disabled={(tablePage + 1) * size >= rows.length} onClick={() => setTablePage(tablePage + 1)}>Próximas</button></div></div>}
    </> : hasValues ? <Chart chart={chart}/> : <p className="tc-empty">Sem observações neste intervalo. Escolha outro período para consultar a série.</p>}
    <footer className="tc-chart-source"><span>Fonte: {chart.source} · {periodOf(chart)}</span>{chart.historical && <span>Série encerrada</span>}</footer>
    {chart.note && <details className="tc-chart-note"><summary>Conceito e abrangência</summary><p>{plainText(chart.note)}</p></details>}
  </article>;
}

export function ExportMenu({charts = [], title, allCharts, collection, onError, disabled = false}) {
  const node = useRef(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  useEffect(() => {
    function outside(event) {if (node.current?.open && !node.current.contains(event.target)) node.current.open = false;}
    function escape(event) {if (event.key === 'Escape' && node.current?.open) {node.current.open = false; node.current.querySelector('summary')?.focus();}}
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape);};
  }, []);
  async function pptx(items, name) {
    if (busy || disabled) return;
    setBusy(true);
    setStatus('Preparando PPTX…');
    try {
      const result = await exportPptx(items, name);
      setStatus(result.complete ? 'PPTX preparado.' : `PPTX parcial: ${result.exported} de ${result.total} gráficos com observações. As ausências constam do arquivo.`);
    } catch (error) {
      setStatus(error.message);
      onError?.(error.message);
    } finally {setBusy(false);}
  }
  function csv() {
    try {csvDownload(charts, title); setStatus('CSV preparado.');} catch (error) {setStatus(error.message); onError?.(error.message);}
  }
  return <details ref={node} className="tc-export-menu">
    <summary>Exportar</summary>
    <div className="tc-export-options">
      <strong>{title}</strong>
      <button type="button" disabled={busy || disabled || !charts.length} onClick={csv}>CSV do recorte</button>
      <button type="button" disabled={busy || disabled || !charts.length} onClick={() => pptx(charts, title)}>PPTX do recorte</button>
      {collection && <button type="button" disabled={busy || disabled || !collection.length} onClick={() => pptx(collection, 'Mercado Imobiliário')}>Mercado imobiliário completo</button>}
      {allCharts && <button type="button" disabled={busy || disabled || !allCharts.length} onClick={() => pptx(allCharts, 'Estatísticas do Sistema Financeiro Nacional')}>Deck completo do SFN</button>}
      {status && <p role="status" aria-live="polite">{status}</p>}
    </div>
  </details>;
}
