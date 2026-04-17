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
  quality_level?: string;
}

export interface EnhanceResponse {
  enhancement_id: string;
  render_hint: RenderHint;
  content: Record<string, unknown> | null;
  provenance?: Provenance;
  generation_id?: string | null;
  error_kind?: string | null;
  quality_warnings?: string[];
  data_stale?: boolean;
  stale?: boolean;
}
