import type { EnhanceResponse } from '../types';
import { escapeHtml, widgetStyle } from './index';

export function render(data: EnhanceResponse): string {
  const label = escapeHtml(String(data.content['label'] ?? 'Run'));
  return `<div class="s2s-widget">${widgetStyle()}` +
    `<button class="s2s-btn" data-action="run" style="` +
    `padding:8px 18px;background:#0070f3;color:#fff;border:none;border-radius:4px;cursor:pointer;font:14px system-ui,sans-serif;` +
    `">` +
    `${label}` +
    `</button></div>`;
}
