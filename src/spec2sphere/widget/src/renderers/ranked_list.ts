import type { EnhanceResponse } from '../types';
import { escapeHtml, widgetStyle } from './index';

interface RankedItem {
  rank?: number;
  label?: string;
  name?: string;
  score?: number;
  reason?: string;
}

export function render(data: EnhanceResponse): string {
  const items: RankedItem[] = Array.isArray(data.content['items'])
    ? (data.content['items'] as RankedItem[])
    : [];

  const listItems = items
    .map((item, idx) => {
      const rank = item.rank ?? idx + 1;
      const label = escapeHtml(String(item.label ?? item.name ?? ''));
      const score = item.score != null ? ` <span class="s2s-score">(${item.score})</span>` : '';
      const reason = item.reason
        ? `<div class="s2s-reason">${escapeHtml(String(item.reason))}</div>`
        : '';
      return `<li class="s2s-item"><span class="s2s-rank">${rank}.</span> ${label}${score}${reason}</li>`;
    })
    .join('');

  return `<div class="s2s-widget">${widgetStyle()}<ol class="s2s-ranked-list">${listItems}</ol></div>`;
}
