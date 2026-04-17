import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { EnhanceResponse } from '../src/types';

const CANNED_RESPONSE: EnhanceResponse = {
  enhancement_id: 'test-enhance-1',
  render_hint: 'narrative',
  content: { narrative_text: 'Hello from widget lifecycle test' },
};

// EventSource stub
class FakeEventSource {
  url: string;
  listeners: Record<string, ((ev: Event) => void)[]> = {};
  static instances: FakeEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (ev: Event) => void): void {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }

  close(): void {}
}

describe('widget lifecycle', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset EventSource instances
    FakeEventSource.instances = [];
    // Install stubs on globalThis
    (globalThis as unknown as Record<string, unknown>)['EventSource'] = FakeEventSource;

    fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(CANNED_RESPONSE),
      text: () => Promise.resolve(''),
    });
    (globalThis as unknown as Record<string, unknown>)['fetch'] = fetchSpy;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // Clean up any elements
    document.body.innerHTML = '';
  });

  it('renders canned response into shadow DOM', async () => {
    // Import main to register custom element
    await import('../src/main');

    const el = document.createElement('spec2sphere-ai-widget');
    el.setAttribute('enhancementid', 'test-enhance-1');
    el.setAttribute('apibase', 'http://localhost:8260');

    document.body.appendChild(el);

    // Wait for async init
    await new Promise((resolve) => setTimeout(resolve, 50));

    const shadow = el.shadowRoot;
    expect(shadow).not.toBeNull();
    expect(shadow?.innerHTML).toContain('Hello from widget lifecycle test');
  });

  it('posts telemetry twice: rendered + dwelled', async () => {
    // Ensure element class is registered
    if (!customElements.get('spec2sphere-ai-widget')) {
      await import('../src/main');
    }

    const el = document.createElement('spec2sphere-ai-widget');
    el.setAttribute('enhancementid', 'test-enhance-1');
    el.setAttribute('apibase', 'http://localhost:8260');

    document.body.appendChild(el);
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Remove → triggers dwelled telemetry
    document.body.removeChild(el);

    // fetchSpy calls: 1) fetchEnhancement, 2) telemetry rendered, 3) telemetry dwelled
    const calls = fetchSpy.mock.calls;

    const telemetryCalls = calls.filter(
      (c) => String(c[0]).includes('/v1/telemetry'),
    );
    expect(telemetryCalls.length).toBeGreaterThanOrEqual(2);

    const events = telemetryCalls.map(
      (c) => JSON.parse((c[1] as RequestInit).body as string) as { event: string },
    );
    const eventNames = events.map((e) => e.event);
    expect(eventNames).toContain('widget.rendered');
    expect(eventNames).toContain('widget.dwelled');
  });

  it('opens EventSource for the enhancement', async () => {
    if (!customElements.get('spec2sphere-ai-widget')) {
      await import('../src/main');
    }

    const el = document.createElement('spec2sphere-ai-widget');
    el.setAttribute('enhancementid', 'stream-test');
    el.setAttribute('apibase', 'http://localhost:8260');

    document.body.appendChild(el);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(1);
    expect(FakeEventSource.instances[0].url).toContain('/v1/stream/stream-test/');
  });
});
