import React, {useEffect, useMemo, useRef, useState} from 'react';
import {BASE, json, number} from './data.js';
import {mergeImob} from './update.js';
import {ChartPanel, ExportMenu} from './Chart.jsx';
import {competenceLabel, latestChartPeriod} from './series-data.js';
import {publicationStatus, publishedSources, sgsChart} from './update-data.js';

function localHousing(uf) {
  try {const saved = JSON.parse(localStorage.getItem(`tomaconta-imob-${uf}`)); return Array.isArray(saved) && saved.length === 24;} catch {return false;}
}

async function official(path, label) {
  const response = await fetch(`${BASE}api/bcb?${path}`);
  if (!response.ok) throw new Error(`${label} indisponível (${response.status}). Tente novamente mais tarde.`);
  return response.json();
}

export default function UpdatePage({manifest, catalog, statementIndex, imob = [], uf = 'br', setUf, onImobChange, onError}) {
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState({});
  const [series, setSeries] = useState([]);
  const [seriesId, setSeriesId] = useState('saldo_livre_total');
  const [seriesError, setSeriesError] = useState('');
  const [seriesAttempt, setSeriesAttempt] = useState(0);
  const [live, setLive] = useState(null);
  const [savedHousing, setSavedHousing] = useState(() => localHousing(uf));
  const mounted = useRef(true), ufRef = useRef(uf);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => {ufRef.current = uf; setSavedHousing(localHousing(uf)); setStatus(value => ({...value, housing: ''}));}, [uf]);
  useEffect(() => {
    let active = true;
    setSeriesError('');
    json('data/sgs-series.json').then(values => {
      if (!Array.isArray(values) || !values.length) throw new Error('O catálogo SGS está vazio.');
      if (!active) return;
      setSeries(values);
      setSeriesId(current => values.some(item => item.alias === current) ? current : values[0].alias);
    }).catch(error => {if (active) setSeriesError(error.message);});
    return () => {active = false;};
  }, [seriesAttempt]);
  const sources = useMemo(() => publishedSources(manifest, catalog, statementIndex), [manifest, catalog, statementIndex]);
  function report(area, message) {if (mounted.current) setStatus(value => ({...value, [area]: message}));}
  function failure(area, error) {report(area, error.message); onError?.(error.message);}
  async function checkPublications() {
    setBusy('publications');
    report('publications', 'Consultando as publicações do BCB…');
    try {
      const [sgs, housing] = await Promise.all([official('source=sgs&code=20539&last=1', 'SGS'), official('source=imob&latest=1', 'Mercado imobiliário')]);
      report('publications', publicationStatus(sgs, housing));
    } catch (error) {failure('publications', error);} finally {if (mounted.current) setBusy('');}
  }
  async function refreshHousing() {
    const selectedUf = uf;
    setBusy('housing');
    report('housing', 'Consultando o BCB e validando as séries…');
    try {
      const [specs, result] = await Promise.all([json('data/imob-catalog.json'), official(`source=imob&uf=${encodeURIComponent(selectedUf)}`, 'Mercado imobiliário')]);
      if (!Array.isArray(result.value) || !result.value.length) throw new Error('O BCB não retornou observações. Sua cópia anterior foi preservada.');
      const updated = mergeImob(imob, specs, result.value, selectedUf, result._queryWindow);
      try {localStorage.setItem(`tomaconta-imob-${selectedUf}`, JSON.stringify(updated));}
      catch {throw new Error('O navegador não conseguiu salvar a atualização. Sua cópia anterior foi preservada. Libere espaço ou use outro navegador.');}
      if (mounted.current && ufRef.current === selectedUf) {
        onImobChange?.(updated, selectedUf);
        setSavedHousing(true);
        report('housing', `${number(result.value.length, 0)} observações consultadas. Cópia de ${selectedUf === 'br' ? 'Brasil' : selectedUf.toUpperCase()} atualizada neste navegador até ${competenceLabel(latestChartPeriod(updated))}.`);
      }
    } catch (error) {if (ufRef.current === selectedUf) failure('housing', error);} finally {if (mounted.current) setBusy('');}
  }
  async function restoreHousing() {
    const selectedUf = uf;
    setBusy('restore');
    report('housing', 'Carregando a versão publicada…');
    try {
      const published = await json(`data/imob-${selectedUf}.json`);
      if (!Array.isArray(published) || published.length !== 24) throw new Error('A versão publicada retornou um catálogo incompleto. Sua cópia anterior foi preservada.');
      localStorage.removeItem(`tomaconta-imob-${selectedUf}`);
      if (mounted.current && ufRef.current === selectedUf) {
        onImobChange?.(published, selectedUf);
        setSavedHousing(false);
        report('housing', `Versão publicada restaurada para ${selectedUf === 'br' ? 'Brasil' : selectedUf.toUpperCase()}.`);
      }
    } catch (error) {if (ufRef.current === selectedUf) failure('housing', error);} finally {if (mounted.current) setBusy('');}
  }
  async function consultSeries() {
    const spec = series.find(item => item.alias === seriesId);
    if (!spec) {report('sgs', 'Escolha uma série do catálogo antes de consultar.'); return;}
    setBusy('sgs');
    report('sgs', 'Consultando a série no BCB…');
    try {
      const values = await official(`source=sgs&code=${encodeURIComponent(spec.code)}`, 'SGS');
      const chart = sgsChart(spec, values);
      if (mounted.current) setLive(chart);
      report('sgs', 'Série carregada. Fonte e competência estão junto do gráfico.');
    } catch (error) {failure('sgs', error);} finally {if (mounted.current) setBusy('');}
  }
  return <>
    <section className="tc-page-header">
      <div className="tc-page-title"><h1>Atualizar base</h1><p>Consulte as publicações do BCB ou atualize a cópia imobiliária deste navegador.</p></div>
      <div className="tc-section-controls"><button type="button" className="tc-action" disabled={Boolean(busy)} onClick={checkPublications}>{busy === 'publications' ? 'Consultando…' : 'Verificar publicações do BCB'}</button></div>
      {status.publications && <p className="tc-operation-status" role="status" aria-live="polite">{status.publications}</p>}
    </section>
    <div className="tc-page-content">
      <section aria-labelledby="tc-published-title">
        <h2 className="tc-section-heading" id="tc-published-title">Base publicada</h2>
        <div className="tc-table-scroll"><table className="tc-data-table tc-sources-table"><thead><tr><th>Base</th><th>Fonte</th><th>Competência</th><th>Cobertura</th></tr></thead><tbody>{sources.map(source => <tr key={source.id}><td>{source.name}</td><td>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.provider}</a> : source.provider}</td><td>{competenceLabel(source.period)}</td><td>{number(source.count, 0)} {source.countLabel}</td></tr>)}</tbody></table></div>
      </section>
      <div className="tc-update-sections">
        <section aria-labelledby="tc-housing-update-title">
          <h2 id="tc-housing-update-title">Mercado imobiliário</h2>
          <p className="tc-section-description">A atualização consulta os últimos 12 meses. O histórico anterior e as séries encerradas são mantidos.</p>
          <div className="tc-update-controls"><label className="tc-field">Abrangência<select value={uf} disabled={Boolean(busy)} onChange={event => setUf?.(event.target.value)}>{(manifest.ufs || ['br']).map(value => <option key={value} value={value}>{value === 'br' ? 'Brasil' : value.toUpperCase()}</option>)}</select></label></div>
          <p className="tc-copy-context">{imob.length?'Em uso: '+(savedHousing ? 'cópia deste navegador' : 'versão publicada')+' · '+competenceLabel(latestChartPeriod(imob)):'Carregando a base desta abrangência…'}</p>
          <div className="tc-update-actions"><button type="button" className="tc-action tc-action-primary" disabled={Boolean(busy)||imob.length!==24} onClick={refreshHousing}>{busy === 'housing' ? 'Atualizando…' : 'Atualizar cópia local'}</button><button type="button" className="tc-text-action" disabled={Boolean(busy) || !savedHousing} onClick={restoreHousing}>{busy === 'restore' ? 'Restaurando…' : 'Restaurar versão publicada'}</button></div>
          {status.housing && <p className="tc-operation-status" role="status" aria-live="polite">{status.housing}</p>}
        </section>
        <section aria-labelledby="tc-sgs-update-title">
          <h2 id="tc-sgs-update-title">Séries SGS</h2>
          <p className="tc-section-description">Consulte uma série diretamente no BCB e exporte o resultado na unidade original.</p>
          <div className="tc-update-controls"><label className="tc-field tc-sgs-field">Série<select value={seriesId} disabled={Boolean(busy) || !series.length} onChange={event => setSeriesId(event.target.value)}>{series.length ? series.map(spec => <option key={spec.alias} value={spec.alias}>{spec.name} · {spec.code}</option>) : <option>Carregando catálogo…</option>}</select></label></div>
          {seriesError && <p className="tc-operation-status" role="alert">{seriesError} <button className="tc-text-action" type="button" onClick={() => setSeriesAttempt(seriesAttempt + 1)}>Tentar novamente</button></p>}
          <div className="tc-update-actions"><button type="button" className="tc-action tc-action-primary" disabled={Boolean(busy) || !series.length} onClick={consultSeries}>{busy === 'sgs' ? 'Consultando…' : 'Consultar no BCB'}</button></div>
          {status.sgs && <p className="tc-operation-status" role="status" aria-live="polite">{status.sgs}</p>}
        </section>
      </div>
      {live && <section className="tc-live-section"><div className="tc-live-toolbar"><h2>Consulta SGS</h2><ExportMenu charts={[live]} title={`SGS · ${live.title}`} onError={onError}/></div><ChartPanel chart={live}/></section>}
      <details className="tc-base-origin"><summary>Origem e alcance da atualização</summary><p>As consultas desta tela usam os serviços oficiais do BCB. A atualização imobiliária é salva neste navegador. A versão compartilhada do site é mantida pelo publicador.</p><p>Fonte da publicação: {manifest.sourceCommit?.slice(0, 7)} · preparada em {new Date(manifest.builtAt).toLocaleString('pt-BR')}. BNDU permanece excluído. Risco da Operação é histórico até dezembro/2024.</p></details>
    </div>
  </>;
}
