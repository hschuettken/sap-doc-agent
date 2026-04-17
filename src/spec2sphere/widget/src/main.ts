import { fetchEnhancement, runAction, openStream } from './api';
import type { WidgetContext } from './api';
import { postTelemetry } from './telemetry';
import { resolveContext } from './sac_context';
import { renderByHint } from './renderers/index';
import { isAuthor } from './auth';
import type { EnhanceResponse } from './types';

class Spec2SphereAiWidget extends HTMLElement {
  private _source: EventSource | null = null;
  private _mountedAt = 0;
  private _ctx: WidgetContext | null = null;

  static get observedAttributes(): string[] {
    return ['enhancementid', 'apibase', 'authmode', 'bearer-token'];
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

  private _bearerToken(): string | null {
    return this.getAttribute('bearer-token');
  }

  private _authHeaders(): Record<string, string> {
    const token = this._bearerToken();
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
  }

  private async _init(): Promise<void> {
    const id = this.getAttribute('enhancementid') ?? '';
    const apiBase = this.getAttribute('apibase') ?? '';
    const fallbackUser = this.getAttribute('fallbackuser') ?? undefined;
    const token = this._bearerToken();

    this._ctx = await resolveContext(fallbackUser ? { user: fallbackUser } : undefined);

    try {
      const data = await fetchEnhancement(apiBase, id, this._ctx, token);
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
    const token = this._bearerToken();
    this.shadowRoot.innerHTML = renderByHint(data);

    // Admin chip — only for author-role tokens
    if (isAuthor(token)) {
      const chip = document.createElement('span');
      chip.setAttribute(
        'style',
        'display:inline-block;background:#1d4ed8;color:#fff;font:11px system-ui,sans-serif;' +
        'padding:2px 8px;border-radius:4px;margin:4px 0;',
      );
      chip.textContent = 'Author';
      chip.className = 'admin-chip';
      this.shadowRoot.appendChild(chip);
    }

    // Wire button action handler
    const btn = this.shadowRoot.querySelector<HTMLButtonElement>('[data-action="run"]');
    if (btn && this._ctx) {
      const apiBase = this.getAttribute('apibase') ?? '';
      const id = this.getAttribute('enhancementid') ?? '';
      const ctx = this._ctx;
      const authHeaders = this._authHeaders();
      btn.addEventListener('click', () => {
        void runAction(apiBase, id, ctx, token).then((result) => {
          this._render(result);
          this.dispatchEvent(
            new CustomEvent('onInteraction', { detail: result, bubbles: true, composed: true }),
          );
        });
      });
      // Keep authHeaders in scope (satisfies TS unused-var check)
      void authHeaders;
    }
  }
}

customElements.define('spec2sphere-ai-widget', Spec2SphereAiWidget);
