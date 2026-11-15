import React, {useEffect, useId, useMemo, useState} from 'react';
import {ChartPanel, ExportMenu} from './Chart.jsx';
import {defaultInterval, sectionLabel, seriesCollections, seriesSections} from './series-data.js';

const TITLES = {sfn: 'Sistema financeiro', imob: 'Mercado imobiliário', payments: 'Pagamentos'};

export function PeriodFilters({window, setWindow, start, setStart, end, setEnd}) {
  return <>
    <label className="tc-field">Período<select value={window} onChange={event => setWindow(event.target.value)}>
      <option value="12">Últimos 12 meses</option><option value="24">Últimos 24 meses</option><option value="60">Últimos 5 anos</option><option value="all">Série completa</option><option value="interval">Intervalo personalizado</option>
    </select></label>
    {window === 'interval' && <><label className="tc-field">De<input type="month" value={start} onChange={event => setStart(event.target.value)}/></label><label className="tc-field">Até<input type="month" value={end} onChange={event => setEnd(event.target.value)}/></label></>}
  </>;
}

export default function SeriesPages({page, manifest, sfn = [], extra = [], imob = [], uf = 'br', setUf, loading = false, onError}) {
  const [window, setWindow] = useState('12');
  const defaults = useMemo(() => defaultInterval([...sfn, ...extra, ...imob]), [sfn, extra, imob]);
  const [start, setStart] = useState(defaults.start), [end, setEnd] = useState(defaults.end);
  const topics = useMemo(() => page === 'imob' ? manifest.imobSections : seriesSections(manifest, extra), [page, manifest, extra]);
  const [section, setSection] = useState(() => page === 'imob' ? manifest.imobSections[0] : seriesSections(manifest, extra)[0]);
  useEffect(() => {if (!topics.includes(section)) setSection(topics[0] || '');}, [topics, section]);
  const collections = useMemo(() => seriesCollections({sfn, extra, imob, window, start, end}), [sfn, extra, imob, window, start, end]);
  const charts = page === 'payments' ? collections.payments : collections[page].filter(chart => chart.section === section);
  const title = page === 'imob' ? `Mercado Imobiliário · ${section}` : page === 'payments' ? 'Meios de pagamento' : section;
  const loadingHousing = page === 'imob' && loading;
  const id = useId();
  return <>
    <section className="tc-page-header" aria-labelledby={`${id}-heading`}>
      <div className="tc-page-title"><h1 id={`${id}-heading`}>{TITLES[page]}</h1></div>
      <div className="tc-section-controls">
        {page !== 'payments' && <label className="tc-field tc-topic-field">Assunto<select value={section} onChange={event => setSection(event.target.value)}>{topics.map(topic => <option value={topic} key={topic}>{sectionLabel(topic)}</option>)}</select></label>}
        {page === 'imob' && <label className="tc-field">Abrangência<select value={uf} onChange={event => setUf?.(event.target.value)}>{(manifest.ufs || ['br']).map(value => <option key={value} value={value}>{value === 'br' ? 'Brasil' : value.toUpperCase()}</option>)}</select></label>}
        <PeriodFilters {...{window, setWindow, start, setStart, end, setEnd}}/>
        <ExportMenu charts={charts} title={title} allCharts={page !== 'payments' ? collections.all : undefined} collection={page === 'imob' ? collections.imob : undefined} disabled={loadingHousing} onError={onError}/>
      </div>
    </section>
    <div className="tc-page-content">
      {window === 'interval' && start && end && start > end && <p className="tc-inline-message" role="alert">A data inicial está depois da final. Ajuste o intervalo para consultar as séries.</p>}
      {loadingHousing ? <div className="tc-loading" role="status">Carregando dados para {uf === 'br' ? 'Brasil' : uf.toUpperCase()}…</div> : charts.length ? <div className="tc-series-grid">{charts.map(chart => <ChartPanel chart={chart} key={chart.id}/>)}</div> : <p className="tc-empty">Nenhum gráfico disponível neste assunto.</p>}
    </div>
  </>;
}
