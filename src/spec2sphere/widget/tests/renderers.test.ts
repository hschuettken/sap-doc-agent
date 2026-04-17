import { describe, it, expect } from 'vitest';
import { renderByHint, escapeHtml, applyMarkdown } from '../src/renderers/index';
import type { EnhanceResponse } from '../src/types';

function make(hint: string, content: Record<string, unknown>): EnhanceResponse {
  return {
    enhancement_id: 'test-1',
    render_hint: hint as EnhanceResponse['render_hint'],
    content,
  };
}

describe('escapeHtml', () => {
  it('escapes <script>', () => {
    expect(escapeHtml('<script>alert(1)</script>')).toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
  });

  it('escapes & < > " \'', () => {
    expect(escapeHtml('&<>"\'')).toBe('&amp;&lt;&gt;&quot;&#39;');
  });
});

describe('applyMarkdown', () => {
  it('wraps text in paragraph', () => {
    const out = applyMarkdown('hello');
    expect(out).toContain('<p>');
    expect(out).toContain('hello');
  });

  it('bolds **text**', () => {
    expect(applyMarkdown('**bold**')).toContain('<strong>bold</strong>');
  });

  it('italics *text*', () => {
    expect(applyMarkdown('*ital*')).toContain('<em>ital</em>');
  });

  it('handles paragraph breaks', () => {
    const out = applyMarkdown('a\n\nb');
    expect(out).toContain('</p><p>');
  });
});

describe('narrative renderer', () => {
  it('renders narrative_text', () => {
    const out = renderByHint(make('narrative', { narrative_text: 'Hello world' }));
    expect(out).toContain('Hello world');
    expect(out).toContain('s2s-widget');
    expect(out).toContain('s2s-narrative');
  });

  it('escapes XSS in narrative', () => {
    const out = renderByHint(make('narrative', { narrative_text: '<script>evil()</script>' }));
    expect(out).toContain('&lt;script&gt;');
    expect(out).not.toContain('<script>');
  });
});

describe('ranked_list renderer', () => {
  it('renders items with rank and score', () => {
    const out = renderByHint(make('ranked_list', {
      items: [
        { rank: 1, label: 'Alpha', score: 0.9, reason: 'Best choice' },
        { rank: 2, label: 'Beta', score: 0.7 },
      ],
    }));
    expect(out).toContain('Alpha');
    expect(out).toContain('0.9');
    expect(out).toContain('Best choice');
    expect(out).toContain('Beta');
    expect(out).toContain('s2s-ranked-list');
  });

  it('escapes HTML in labels', () => {
    const out = renderByHint(make('ranked_list', {
      items: [{ rank: 1, label: '<b>inject</b>' }],
    }));
    expect(out).toContain('&lt;b&gt;');
    expect(out).not.toContain('<b>inject</b>');
  });

  it('handles empty items', () => {
    const out = renderByHint(make('ranked_list', { items: [] }));
    expect(out).toContain('s2s-ranked-list');
  });
});

describe('callout renderer', () => {
  it('renders info callout', () => {
    const out = renderByHint(make('callout', {
      severity: 'info',
      headline: 'Note',
      body: 'Something notable',
    }));
    expect(out).toContain('Note');
    expect(out).toContain('Something notable');
    expect(out).toContain('#0070f3');
  });

  it('renders warn callout with correct color', () => {
    const out = renderByHint(make('callout', { severity: 'warn', headline: 'Warning', body: '' }));
    expect(out).toContain('#f59e0b');
  });

  it('renders critical callout with correct color', () => {
    const out = renderByHint(make('callout', { severity: 'critical', headline: 'Alert', body: '' }));
    expect(out).toContain('#ef4444');
  });

  it('defaults to info when severity missing', () => {
    const out = renderByHint(make('callout', { headline: 'Default', body: '' }));
    expect(out).toContain('#0070f3');
  });

  it('escapes HTML in headline and body', () => {
    const out = renderByHint(make('callout', {
      headline: '<img onerror="">',
      body: '<script>x</script>',
    }));
    expect(out).toContain('&lt;img');
    expect(out).toContain('&lt;script&gt;');
  });
});

describe('button renderer', () => {
  it('renders button with default label', () => {
    const out = renderByHint(make('button', {}));
    expect(out).toContain('Run');
    expect(out).toContain('data-action="run"');
  });

  it('renders custom label', () => {
    const out = renderByHint(make('button', { label: 'Execute' }));
    expect(out).toContain('Execute');
  });

  it('escapes HTML in label', () => {
    const out = renderByHint(make('button', { label: '<script>' }));
    expect(out).toContain('&lt;script&gt;');
    expect(out).not.toContain('<script>');
  });
});

describe('brief renderer', () => {
  it('renders narrative + key_points + callout', () => {
    const out = renderByHint(make('brief', {
      narrative_text: 'Summary here',
      key_points: ['Point A', 'Point B'],
      callout_headline: 'Heads up',
      callout_body: 'Detail text',
    }));
    expect(out).toContain('Summary here');
    expect(out).toContain('Point A');
    expect(out).toContain('Point B');
    expect(out).toContain('Heads up');
    expect(out).toContain('Detail text');
  });

  it('escapes XSS in key_points', () => {
    const out = renderByHint(make('brief', {
      key_points: ['<script>evil</script>'],
    }));
    expect(out).toContain('&lt;script&gt;');
  });
});

describe('chart renderer', () => {
  it('renders SVG polyline from values', () => {
    const out = renderByHint(make('chart', { values: [10, 20, 15, 30] }));
    expect(out).toContain('<svg');
    expect(out).toContain('<polyline');
    expect(out).toContain('s2s-chart');
  });

  it('falls back to series key', () => {
    const out = renderByHint(make('chart', { series: [1, 2, 3] }));
    expect(out).toContain('<polyline');
  });

  it('shows empty message with no data', () => {
    const out = renderByHint(make('chart', {}));
    expect(out).toContain('No chart data');
  });

  it('handles single-value series', () => {
    const out = renderByHint(make('chart', { values: [42] }));
    expect(out).toContain('<polyline');
  });
});

describe('unknown hint', () => {
  it('returns error message for unknown hint', () => {
    const out = renderByHint(make('unknown_type', {}));
    expect(out).toContain('Unknown render hint');
  });
});
