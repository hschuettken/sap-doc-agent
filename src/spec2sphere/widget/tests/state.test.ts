import { describe, it, expect } from 'vitest';
import { renderByHint } from '../src/renderers/index';

describe('wrapState', () => {
  it('shows cost_cap banner when error_kind=cost_cap', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative', content: null,
      error_kind: 'cost_cap',
    } as any);
    expect(html).toContain('monthly cap');
    expect(html).toContain('s2s-error-banner');
  });

  it('shows LLM warning banner on llm_timeout', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'partial' }, error_kind: 'llm_timeout',
    } as any);
    expect(html).toContain('LLM unavailable');
    expect(html).toContain('partial');
  });

  it('shows LLM warning banner on llm_error', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'cached' }, error_kind: 'llm_error',
    } as any);
    expect(html).toContain('LLM unavailable');
    expect(html).toContain('cached');
  });

  it('shows LLM warning banner on llm_http_error', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'cached' }, error_kind: 'llm_http_error',
    } as any);
    expect(html).toContain('LLM unavailable');
  });

  it('shows LLM warning banner on llm_bad_response', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'cached' }, error_kind: 'llm_bad_response',
    } as any);
    expect(html).toContain('LLM unavailable');
  });

  it('shows data_stale banner', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' }, data_stale: true,
    } as any);
    expect(html).toContain('Data may be stale');
    expect(html).toContain('s2s-warn-banner');
  });

  it('applies stale opacity class', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' }, stale: true,
    } as any);
    expect(html).toContain('s2s-stale');
    expect(html).toContain('Refreshing');
  });

  it('shows quality_warnings pill with count', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' },
      quality_warnings: ['partial_context', 'external_missing'],
    } as any);
    expect(html).toContain('2 quality notes');
    expect(html).toContain('s2s-quality-pill');
  });

  it('shows singular quality note text for one warning', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' },
      quality_warnings: ['partial_context'],
    } as any);
    expect(html).toContain('1 quality note');
    expect(html).not.toContain('1 quality notes');
  });

  it('normal render has no banners', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' },
    } as any);
    expect(html).not.toContain('class="s2s-error-banner"');
    expect(html).not.toContain('class="s2s-warn-banner"');
    expect(html).not.toContain('class="s2s-quality-pill"');
  });

  it('cost_cap with null content renders only banner', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: null, error_kind: 'cost_cap',
    } as any);
    expect(html).toContain('s2s-widget');
    expect(html).toContain('monthly cap');
    // no narrative content div
    expect(html).not.toContain('class="s2s-narrative"');
  });

  it('quality_warnings tooltip contains escaped warning text', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' },
      quality_warnings: ['has <special> chars'],
    } as any);
    expect(html).toContain('&lt;special&gt;');
  });

  it('data_stale and stale can combine', () => {
    const html = renderByHint({
      enhancement_id: 'x', render_hint: 'narrative',
      content: { narrative_text: 'body' },
      data_stale: true, stale: true,
    } as any);
    expect(html).toContain('Data may be stale');
    expect(html).toContain('s2s-stale');
    expect(html).toContain('Refreshing');
  });
});
