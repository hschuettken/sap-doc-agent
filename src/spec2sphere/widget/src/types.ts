export type RenderHint =
  | 'narrative'
  | 'ranked_list'
  | 'callout'
  | 'button'
  | 'brief'
  | 'chart';

export interface Provenance {
  rule_id?: string;
  model?: string;
  cached?: boolean;
  generated_at?: string;
  latency_ms?: number;
}

export interface EnhanceResponse {
  enhancement_id: string;
  render_hint: RenderHint;
  content: Record<string, unknown>;
  provenance?: Provenance;
  generation_id?: string;
  quality_warnings?: string[];
  _cached?: boolean;
  error_kind?: string;
}
