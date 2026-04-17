"""Wraps any LLMProvider and logs every call into dsp_ai.generations.

Applied in create_llm_provider() so every Spec2Sphere caller benefits
without code changes. The wrapper is best-effort — logging failures
NEVER break the underlying LLM call.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any, Optional

from .base import DEFAULT_TIER, LLMProvider

logger = logging.getLogger(__name__)

# tier → quality_level mapping — matches the Q1..Q5 ladder in dsp_ai.generations.
_TIER_TO_Q = {"small": "Q1", "medium": "Q2", "large": "Q3", "reasoning": "Q5"}


class ObservedLLMProvider(LLMProvider):
    """Transparent observability wrapper.

    Forwards every call to the inner provider. After (or on exception
    during) the call, attempts to insert a row into ``dsp_ai.generations``.
    ``caller`` is an optional hint supplied by instrumented call sites
    (e.g. ``caller="agents.doc_review"``). Unknown callers land as
    ``"unknown"``.
    """

    def __init__(self, inner: LLMProvider):
        self._inner = inner
        self._model_hint = getattr(inner, "_model", None) or getattr(inner, "model", None) or inner.__class__.__name__

    # LLMProvider API -----------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
        caller: str | None = None,
    ) -> Optional[str]:
        t0 = time.time()
        err: str | None = None
        try:
            result = await self._inner.generate(
                prompt,
                system,
                tier=tier,
                data_in_context=data_in_context,
            )
            return result
        except Exception:
            err = "exception"
            raise
        finally:
            await self._log(prompt, tier, caller, t0, error=err)

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
        caller: str | None = None,
    ) -> Optional[dict]:
        t0 = time.time()
        err: str | None = None
        try:
            result = await self._inner.generate_json(
                prompt,
                schema,
                system,
                tier=tier,
                data_in_context=data_in_context,
            )
            return result
        except Exception:
            err = "exception"
            raise
        finally:
            await self._log(prompt, tier, caller, t0, error=err)

    def is_available(self) -> bool:
        return self._inner.is_available()

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        # Pass through embeddings without logging — they're not LLM calls.
        return await self._inner.embed(texts)

    # Transparent passthrough for provider-specific attributes that callers
    # may rely on (e.g. ``_resolve_model`` on TieredProvider).
    def __getattr__(self, name: str) -> Any:
        # __getattr__ only fires for attributes we don't define ourselves.
        # Guard against recursion during init.
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    # Internal -------------------------------------------------------------------------

    async def _log(
        self,
        prompt: str,
        tier: str,
        caller: str | None,
        t0: float,
        *,
        error: str | None = None,
    ) -> None:
        latency_ms = int((time.time() - t0) * 1000)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        try:
            from spec2sphere.dsp_ai.db import current_customer, get_conn  # noqa: PLC0415

            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO dsp_ai.generations
                        (id, enhancement_id, user_id, context_key, prompt_hash, input_ids,
                         model, quality_level, latency_ms, tokens_in, tokens_out, cost_usd,
                         cached, quality_warnings, error_kind, preview, caller, customer)
                    VALUES ($1::uuid, NULL, NULL, NULL, $2, '[]'::jsonb,
                            $3, $4, $5, NULL, NULL, NULL,
                            FALSE, NULL, $6, FALSE, $7, $8)
                    """,
                    str(uuid.uuid4()),
                    prompt_hash,
                    str(self._model_hint),
                    _TIER_TO_Q.get(tier, "Q3"),
                    latency_ms,
                    error,
                    caller or "unknown",
                    current_customer(),
                )
        except Exception:
            logger.debug("observed_llm: insert failed (non-fatal)", exc_info=True)
