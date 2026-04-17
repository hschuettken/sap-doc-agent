import type { EnhanceResponse } from '../types';
import { escapeHtml } from './index';

interface RankedItem {
  rank?: number;
  label?: string;
  name?: string;
  score?: number;
  reason?: string;
}

export function render(data: EnhanceResponse): string {
  const content = data.content as Record<string, unknown>;
  const items: RankedItem[] = Array.isArray(content['items'])
    ? (content['items'] as RankedItem[])
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

  return `<ol class="s2s-ranked-list">${listItems}</ol>`;
}
