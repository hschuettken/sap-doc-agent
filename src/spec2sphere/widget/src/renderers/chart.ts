import type { EnhanceResponse } from '../types';

export function render(data: EnhanceResponse): string {
  const content = data.content as Record<string, unknown>;
  const rawValues: unknown = content['values'] ?? content['series'];
  const values: number[] = Array.isArray(rawValues)
    ? (rawValues as unknown[]).map(v => Number(v)).filter(n => !isNaN(n))
    : [];

  if (values.length === 0) {
    return `<div class="s2s-chart-empty">No chart data</div>`;
  }

  const W = 200;
  const H = 40;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const step = values.length > 1 ? W / (values.length - 1) : W;
  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = H - ((v - min) / range) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const svg =
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:${W}px;height:${H}px;display:block;">` +
    `<polyline points="${points}" fill="none" stroke="#0070f3" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>` +
    `</svg>`;

  return `<div class="s2s-chart">${svg}</div>`;
}
