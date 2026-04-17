import type { EnhanceResponse, RenderHint } from '../types';

// ---------------------------------------------------------------------------
// Shared utilities (used by sibling renderers)
// ---------------------------------------------------------------------------

export function escapeHtml(str: string): string {
  return str.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return c;
    }
  });
}

/** Tiny inline markdown: **bold**, *italic*, \n\n → paragraph breaks */
export function applyMarkdown(safe: string): string {
  // safe is already HTML-escaped; apply markdown patterns over safe text
  let out = safe;
  // **bold** (greedy-safe because we already escaped)
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // *italic*
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // paragraph breaks
  out = out.replace(/\n\n+/g, '</p><p>');
  return `<p>${out}</p>`;
}

export function widgetStyle(): string {
  return `<style>
    :host { all: initial; }
    .s2s-widget { font: 14px system-ui, sans-serif; color: #1a1a1a; padding: 8px; box-sizing: border-box; }
    .s2s-narrative p { margin: 0 0 8px; line-height: 1.5; }
    .s2s-ranked-list { margin: 0; padding-left: 20px; }
    .s2s-item { margin-bottom: 6px; }
    .s2s-rank { font-weight: 600; }
    .s2s-score { color: #6b7280; font-size: 12px; }
    .s2s-reason { color: #6b7280; font-size: 12px; margin-top: 2px; }
    .s2s-brief-narrative p { margin: 0 0 8px; line-height: 1.5; }
    .s2s-brief-points { margin: 8px 0; padding-left: 20px; }
    .s2s-brief-points li { margin-bottom: 4px; }
    .s2s-chart { overflow: hidden; }
    .s2s-chart-empty { color: #9ca3af; font-size: 12px; }
    .s2s-btn:hover { opacity: 0.85; }
  </style>`;
}

// ---------------------------------------------------------------------------
// Dispatcher
// ---------------------------------------------------------------------------

type Renderer = { render: (data: EnhanceResponse) => string };

const RENDERERS: Partial<Record<RenderHint, () => Promise<Renderer>>> = {
  narrative:    () => import('./narrative'),
  ranked_list:  () => import('./ranked_list'),
  callout:      () => import('./callout'),
  button:       () => import('./button'),
  brief:        () => import('./brief'),
  chart:        () => import('./chart'),
};

// Synchronous variants (pre-imported for IIFE bundle) — populated below
import * as narrativeR   from './narrative';
import * as rankedListR  from './ranked_list';
import * as calloutR     from './callout';
import * as buttonR      from './button';
import * as briefR       from './brief';
import * as chartR       from './chart';

const SYNC_RENDERERS: Record<RenderHint, Renderer> = {
  narrative:   narrativeR,
  ranked_list: rankedListR,
  callout:     calloutR,
  button:      buttonR,
  brief:       briefR,
  chart:       chartR,
};

export function renderByHint(data: EnhanceResponse): string {
  const hint = data.render_hint as RenderHint;
  const renderer = SYNC_RENDERERS[hint];
  if (!renderer) {
    return `<div class="s2s-widget">${widgetStyle()}<p>Unknown render hint: ${escapeHtml(hint)}</p></div>`;
  }
  return renderer.render(data);
}

// Keep async variant for tree-shaking if needed later
export async function renderByHintAsync(data: EnhanceResponse): Promise<string> {
  const hint = data.render_hint as RenderHint;
  const loader = RENDERERS[hint];
  if (!loader) {
    return `<div class="s2s-widget">${widgetStyle()}<p>Unknown render hint: ${escapeHtml(hint)}</p></div>`;
  }
  const mod = await loader();
  return mod.render(data);
}
