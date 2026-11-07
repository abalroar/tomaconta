/** Presentation only. Values and units stay in the source scale. */
export function chartNumber(value, digits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/D';
  const number = Object.is(value, -0) ? 0 : value;
  const magnitude = Math.abs(number);
  const needed = magnitude > 0 && magnitude < 10 ** -digits ? Math.max(digits, 2 - Math.floor(Math.log10(magnitude))) : digits;
  if (needed > 12) return new Intl.NumberFormat('pt-BR', {notation: 'scientific', minimumFractionDigits: 2, maximumFractionDigits: 2}).format(number);
  return new Intl.NumberFormat('pt-BR', {minimumFractionDigits: digits, maximumFractionDigits: needed}).format(number);
}

export function chartTick(value, percent = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/D';
  const number = Object.is(value, -0) ? 0 : value;
  const digits = number === 0 ? 0 : Math.max(0, 3 - Math.floor(Math.log10(Math.abs(number))));
  const shown = digits > 12
    ? new Intl.NumberFormat('pt-BR', {notation: 'scientific', minimumFractionDigits: 2, maximumFractionDigits: 2}).format(number)
    : new Intl.NumberFormat('pt-BR', {minimumFractionDigits: 0, maximumFractionDigits: digits}).format(number);
  return shown + (percent ? '%' : '');
}

export function chartValue(value, unit) {
  const shown = chartNumber(value);
  return shown === 'N/D' ? shown : `${shown}${unit ? ` ${unit}` : ''}`;
}

export function chartLabel(value) {
  return typeof value === 'number' && Number.isFinite(value) ? chartNumber(value, 1) : '';
}

/** Choose annotations only; all columns and their tooltip values remain present. */
export function showInnerLabel(index, count, plotWidth, spacing = 42) {
  if (!Number.isInteger(index) || !Number.isInteger(count) || count <= 0 || index < 0 || index >= count) return false;
  const last = count - 1;
  if (index === 0 || index === last) return true;
  const categoryWidth = Math.max(0, Number(plotWidth) || 0) / count;
  const step = categoryWidth > 0 ? Math.max(1, Math.ceil(spacing / categoryWidth)) : count;
  return index % step === 0 && index <= last - step;
}
