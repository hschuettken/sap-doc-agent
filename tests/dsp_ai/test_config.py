"""Unit tests for Enhancement Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spec2sphere.dsp_ai.config import (
    AdaptiveRules,
    DataBinding,
    Enhancement,
    EnhancementBindings,
    EnhancementConfig,
    EnhancementKind,
    EnhancementMode,
    ExternalBinding,
    RenderHint,
    SemanticBinding,
)


def _minimal_config(**overrides) -> EnhancementConfig:
    base = dict(
        name="test",
        kind=EnhancementKind.NARRATIVE,
        bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
        prompt_template="hi",
        render_hint=RenderHint.NARRATIVE_TEXT,
    )
    base.update(overrides)
    return EnhancementConfig(**base)


def test_enhancement_config_minimal_valid() -> None:
    cfg = _minimal_config()
    assert cfg.mode == EnhancementMode.BATCH
    assert cfg.ttl_seconds == 600
    assert cfg.adaptive_rules.per_user is False
    assert cfg.bindings.semantic is None
    assert cfg.bindings.external is None


def test_enhancement_config_rejects_bad_kind() -> None:
    with pytest.raises(ValidationError):
        EnhancementConfig(
            name="test",
            kind="nonsense",  # type: ignore[arg-type]
            bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
            prompt_template="hi",
            render_hint=RenderHint.NARRATIVE_TEXT,
        )


def test_enhancement_config_full_shape() -> None:
    cfg = _minimal_config(
        mode=EnhancementMode.BOTH,
        bindings=EnhancementBindings(
            data=DataBinding(dsp_query="SELECT * FROM sales", parameters={"region": "FR"}),
            semantic=SemanticBinding(cypher="MATCH (o:DspObject) RETURN o LIMIT 5"),
            external=ExternalBinding(searxng_query="revenue news", max_results=3),
        ),
        adaptive_rules=AdaptiveRules(per_user=True, per_time=True, per_delta=True),
        output_schema={"type": "object"},
        ttl_seconds=1800,
    )
    dumped = cfg.model_dump()
    assert dumped["bindings"]["external"]["max_results"] == 3
    assert dumped["adaptive_rules"]["per_delta"] is True
    # Round-trip through JSON-like dict preserves shape
    assert EnhancementConfig.model_validate(dumped).model_dump() == dumped


def test_enhancement_envelope_requires_known_status() -> None:
    with pytest.raises(ValidationError):
        Enhancement(
            id="1",
            version=1,
            status="on_fire",  # type: ignore[arg-type]
            config=_minimal_config(),
        )


def test_enhancement_envelope_happy_path() -> None:
    e = Enhancement(
        id="abc",
        version=2,
        status="published",
        author="h@example.com",
        config=_minimal_config(),
    )
    assert e.status == "published"
    assert e.config.kind == EnhancementKind.NARRATIVE
