import type { EnhanceResponse } from '../types';
import { escapeHtml, widgetStyle } from './index';

const SEVERITY_COLORS: Record<string, string> = {
  info: '#0070f3',
  warn: '#f59e0b',
  critical: '#ef4444',
};

export function render(data: EnhanceResponse): string {
  const severity = String(data.content['severity'] ?? 'info');
  const color = SEVERITY_COLORS[severity] ?? SEVERITY_COLORS['info'];
  const headline = escapeHtml(String(data.content['headline'] ?? ''));
  const body = escapeHtml(String(data.content['body'] ?? ''));

  return `<div class="s2s-widget">${widgetStyle()}` +
    `<div class="s2s-callout" style="border-left:4px solid ${color};padding:10px 14px;background:#f9fafb;border-radius:4px;">` +
    `<div class="s2s-callout-headline" style="font-weight:600;color:${color};">${headline}</div>` +
    `<div class="s2s-callout-body">${body}</div>` +
    `</div></div>`;
}
