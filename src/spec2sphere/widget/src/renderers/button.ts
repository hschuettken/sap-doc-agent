import type { EnhanceResponse } from '../types';
import { escapeHtml } from './index';

export function render(data: EnhanceResponse): string {
  const content = data.content as Record<string, unknown>;
  const label = escapeHtml(String(content['label'] ?? 'Run'));
  return (
    `<button class="s2s-btn" data-action="run" style="` +
    `padding:8px 18px;background:#0070f3;color:#fff;border:none;border-radius:4px;cursor:pointer;font:14px system-ui,sans-serif;` +
    `">` +
    `${label}` +
    `</button>`
  );
}
