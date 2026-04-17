import type { EnhanceResponse } from './types';

export interface WidgetContext {
  user: string;
  hints: Record<string, unknown>;
}

export async function fetchEnhancement(
  apiBase: string,
  id: string,
  ctx: WidgetContext,
): Promise<EnhanceResponse> {
  const res = await fetch(`${apiBase}/v1/enhance/${id}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ user: ctx.user, context_hints: ctx.hints }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`enhance ${id} failed ${res.status}: ${text}`);
  }
  return res.json() as Promise<EnhanceResponse>;
}

export async function runAction(
  apiBase: string,
  id: string,
  ctx: WidgetContext,
): Promise<EnhanceResponse> {
  const res = await fetch(`${apiBase}/v1/actions/${id}/run`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ user: ctx.user, context_hints: ctx.hints }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`action ${id} failed ${res.status}: ${text}`);
  }
  return res.json() as Promise<EnhanceResponse>;
}

export function openStream(
  apiBase: string,
  id: string,
  user: string,
  onEvent: (data: string) => void,
): EventSource {
  const src = new EventSource(
    `${apiBase}/v1/stream/${id}/${encodeURIComponent(user)}`,
  );
  src.addEventListener('briefing_generated', (ev: Event) => {
    onEvent((ev as MessageEvent).data);
  });
  return src;
}
