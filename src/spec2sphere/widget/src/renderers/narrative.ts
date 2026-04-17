import type { EnhanceResponse } from '../types';
import { escapeHtml, applyMarkdown } from './index';

export function render(data: EnhanceResponse): string {
  const text = String((data.content as Record<string, unknown>)?.['narrative_text'] ?? '');
  const html = applyMarkdown(escapeHtml(text));
  return `<div class="s2s-narrative">${html}</div>`;
}
