import type { EnhanceResponse } from '../types';
import { escapeHtml, applyMarkdown, widgetStyle } from './index';

export function render(data: EnhanceResponse): string {
  const text = String(data.content['narrative_text'] ?? '');
  const html = applyMarkdown(escapeHtml(text));
  return `<div class="s2s-widget">${widgetStyle()}<div class="s2s-narrative">${html}</div></div>`;
}
