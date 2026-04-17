import type { EnhanceResponse } from '../types';
import { escapeHtml, applyMarkdown, widgetStyle } from './index';

export function render(data: EnhanceResponse): string {
  const narrativeText = String(data.content['narrative_text'] ?? '');
  const keyPoints: unknown[] = Array.isArray(data.content['key_points'])
    ? (data.content['key_points'] as unknown[])
    : [];
  const calloutHeadline = data.content['callout_headline'];
  const calloutBody = data.content['callout_body'];

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

  return `<div class="s2s-widget">${widgetStyle()}${narrative}${points}${callout}</div>`;
}
