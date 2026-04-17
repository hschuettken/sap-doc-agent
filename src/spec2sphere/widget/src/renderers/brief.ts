import type { EnhanceResponse } from '../types';
import { escapeHtml, applyMarkdown } from './index';

export function render(data: EnhanceResponse): string {
  const content = data.content as Record<string, unknown>;
  const narrativeText = String(content['narrative_text'] ?? '');
  const keyPoints: unknown[] = Array.isArray(content['key_points'])
    ? (content['key_points'] as unknown[])
    : [];
  const calloutHeadline = content['callout_headline'];
  const calloutBody = content['callout_body'];

  const narrative = narrativeText
    ? `<div class="s2s-brief-narrative">${applyMarkdown(escapeHtml(narrativeText))}</div>`
    : '';

  const points = keyPoints.length
    ? `<ul class="s2s-brief-points">${keyPoints.map(p => `<li>${escapeHtml(String(p))}</li>`).join('')}</ul>`
    : '';

  const callout = calloutHeadline
    ? `<div class="s2s-brief-callout" style="border-left:4px solid #0070f3;padding:8px 12px;background:#f0f7ff;border-radius:4px;margin-top:10px;">` +
      `<strong>${escapeHtml(String(calloutHeadline))}</strong>` +
      (calloutBody ? `<div>${escapeHtml(String(calloutBody))}</div>` : '') +
      `</div>`
    : '';

  return `${narrative}${points}${callout}`;
}
