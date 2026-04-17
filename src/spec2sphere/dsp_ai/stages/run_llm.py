"""Stage 5: delegate to quality_router for model selection and call.

Returns (shaped_output, metadata) — metadata carries model/tokens/latency/cost
used by Stage 6 + 7 for provenance.

Note: resolve_and_call is implemented in Task 10. Tests must patch
spec2sphere.dsp_ai.stages.run_llm.resolve_and_call.
"""

from __future__ import annotations

import time
from typing import Any

from spec2sphere.llm.quality_router import resolve_and_call  # noqa: F401 — added in Task 10

from ..config import Enhancement


async def run(enh: Enhancement, prompt: str, data_in_context: bool = False) -> tuple[Any, dict]:
    t0 = time.time()
    out, meta = await resolve_and_call(
        action=enh.config.name,
        prompt=prompt,
        data_in_context=data_in_context,
        schema=enh.config.output_schema,
    )
    return out, {**meta, "latency_ms": int((time.time() - t0) * 1000)}
