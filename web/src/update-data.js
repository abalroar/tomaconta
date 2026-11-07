import {competenceLabel} from './series-data.js';

const UNITS = {pct_year: '% a.a.', pct: '%', pct_month: '% a.m.', brl_million: 'R$ milhões', brl_billion: 'R$ bilhões', index: 'Índice'};

export function housingStorageKey(uf,version='static'){
  if(!/^(?:br|ac|al|ap|am|ba|ce|df|es|go|ma|mt|ms|mg|pa|pb|pr|pe|pi|rj|rn|rs|ro|rr|sc|sp|se|to)$/.test(uf)||!(/^[a-f0-9]{32}$/.test(version)||/^static-[a-f0-9]{40}$/.test(version)||version==='static'))throw Error('Versão da cópia imobiliária inválida.');
  return `tomaconta-imob-${version}-${uf}`;
}

export function sgsChart(spec, values) {
  if (!spec || !Array.isArray(values) || !values.length) throw new Error('A consulta não retornou observações para esta série.');
  const data = values.map(row => {
    if (!/^\d{2}\/\d{2}\/\d{4}$/.test(row.data || '') || row.valor == null || String(row.valor).trim() === '' || !Number.isFinite(Number(row.valor))) throw new Error('O BCB retornou uma observação inválida. A série anterior foi preservada.');
    const date = row.data.split('/').reverse().join('-');
    const parsed = new Date(`${date}T00:00:00Z`);
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) throw new Error('O BCB retornou uma competência inválida. A série anterior foi preservada.');
    return [date, Number(row.valor)];
  });
  return {id: `live-${spec.code}`, title: spec.name, source: `BCB · SGS ${spec.code}`, unit: UNITS[spec.unit] || spec.unit, percent: String(spec.unit).startsWith('pct'), series: [{name: spec.name, type: 'line', data}]};
}

export function publishedSources(manifest, catalog, statementIndex,network) {
  const rows = [{id: 'institutions', name: 'Instituições financeiras', provider: 'BCB · IFData', period: catalog.latestPeriod, count: catalog.institutions.length, countLabel: 'instituições no histórico'}];
  if (statementIndex?.institutions?.length) {
    for (const scope of ['individual', 'prudential']) {
      const entries = statementIndex.institutions.filter(entry => entry.scope === scope);
      if (!entries.length) continue;
      const periods = entries.flatMap(entry => entry.periods || [entry.latestPeriod]).filter(Boolean).sort();
      rows.push({id: `statements-${scope}`, name: `Balanço e DRE · ${scope === 'individual' ? 'individual' : 'prudencial'}`, provider: scope === 'individual' ? 'BCB · COSIF 4010' : 'BCB · COSIF 4060/4066', period: periods.at(-1), count: entries.length, countLabel: 'instituições no histórico'});
    }
  }
  if(network?.position)rows.push({id:'network',name:'Rede de agências',provider:'BCB · IBGE',period:network.position,count:network.checks.selectedRecords,countLabel:'agências',url:'https://dadosabertos.bcb.gov.br/dataset/agencias'});
  return [...rows, ...(manifest.sources || []).map(source => ({...source, count: source.rows, countLabel: 'registros'}))];
}

export function publicationStatus(sgs, housing) {
  const sgsDate = Array.isArray(sgs) ? sgs.at(-1)?.data : null;
  const housingDate = housing?.value?.[0]?.Data;
  if (!sgsDate || !housingDate) throw new Error('A consulta não retornou as duas competências esperadas.');
  return `Publicações consultadas: SGS ${sgsDate} · Mercado imobiliário ${competenceLabel(housingDate)}.`;
}
