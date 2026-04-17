import { fetchEnhancement, runAction, openStream } from './api';
import type { WidgetContext } from './api';
import { postTelemetry } from './telemetry';
import { resolveContext } from './sac_context';
import { renderByHint } from './renderers/index';
import type { EnhanceResponse } from './types';

class Spec2SphereAiWidget extends HTMLElement {
  private _source: EventSource | null = null;
  private _mountedAt = 0;
  private _ctx: WidgetContext | null = null;

  static get observedAttributes(): string[] {
    return ['enhancementid', 'apibase', 'authmode'];
  }

  connectedCallback(): void {
    this._mountedAt = performance.now();
    this.attachShadow({ mode: 'open' });
    void this._init();
  }

  disconnectedCallback(): void {
    if (this._source) {
      this._source.close();
      this._source = null;
    }
    const duration_s = (performance.now() - this._mountedAt) / 1000;
    const apiBase = this.getAttribute('apibase') ?? '';
    postTelemetry(apiBase, {
      event: 'widget.dwelled',
      enhancement_id: this.getAttribute('enhancementid') ?? undefined,
      user: this._ctx?.user,
      duration_s,
    });
  }

  private async _init(): Promise<void> {
    const id = this.getAttribute('enhancementid') ?? '';
    const apiBase = this.getAttribute('apibase') ?? '';
    const fallbackUser = this.getAttribute('fallbackuser') ?? undefined;

    this._ctx = await resolveContext(fallbackUser ? { user: fallbackUser } : undefined);

    try {
      const data = await fetchEnhancement(apiBase, id, this._ctx);
      this._render(data);
      postTelemetry(apiBase, {
        event: 'widget.rendered',
        enhancement_id: id,
        user: this._ctx.user,
        render_hint: data.render_hint,
      });
      this.dispatchEvent(
        new CustomEvent('onGenerated', { detail: data, bubbles: true, composed: true }),
      );
      this._source = openStream(apiBase, id, this._ctx.user, () => {
        void this._init();
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (this.shadowRoot) {
        this.shadowRoot.innerHTML = `<div style="color:#ef4444;font:14px system-ui,sans-serif;padding:8px">Error: ${msg}</div>`;
      }
      this.dispatchEvent(
        new CustomEvent('onError', { detail: { message: msg }, bubbles: true, composed: true }),
      );
    }
  }

  private _render(data: EnhanceResponse): void {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = renderByHint(data);

    // Wire button action handler
    const btn = this.shadowRoot.querySelector<HTMLButtonElement>('[data-action="run"]');
    if (btn && this._ctx) {
      const apiBase = this.getAttribute('apibase') ?? '';
      const id = this.getAttribute('enhancementid') ?? '';
      const ctx = this._ctx;
      btn.addEventListener('click', () => {
        void runAction(apiBase, id, ctx).then((result) => {
          this._render(result);
          this.dispatchEvent(
            new CustomEvent('onInteraction', { detail: result, bubbles: true, composed: true }),
          );
        });
      });
    }
  }
}

customElements.define('spec2sphere-ai-widget', Spec2SphereAiWidget);
