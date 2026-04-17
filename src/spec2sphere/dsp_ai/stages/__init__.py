"""Seven-stage DSP-AI engine stages.

Stage execution order:
  1. resolve   — load Enhancement config from Postgres
  2. gather    — parallel DSP/Brain/External/UserState fetch
  3. adaptive_rules — pure-Python filter/weight (no LLM)
  4. compose_prompt — Jinja render
  5. run_llm   — quality_router delegate
  6. shape_output — provenance envelope
  7. dispatch  — write to dsp_ai.* or return JSON
"""
