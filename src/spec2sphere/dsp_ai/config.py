"""Enhancement configuration models (Pydantic v2).

The :class:`EnhancementConfig` is the authoring shape — what the AI Studio
editor produces and what gets JSON-serialised into ``dsp_ai.enhancements.config``.
:class:`Enhancement` is the row envelope with id/version/status/author.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EnhancementKind(str, Enum):
    NARRATIVE = "narrative"
    RANKING = "ranking"
    ITEM_ENRICH = "item_enrich"
    ACTION = "action"
    BRIEFING = "briefing"


class RenderHint(str, Enum):
    NARRATIVE_TEXT = "narrative_text"
    RANKED_LIST = "ranked_list"
    CALLOUT = "callout"
    BUTTON = "button"
    BRIEF = "brief"
    CHART = "chart"


class EnhancementMode(str, Enum):
    BATCH = "batch"
    LIVE = "live"
    BOTH = "both"


class DataBinding(BaseModel):
    dsp_query: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class SemanticBinding(BaseModel):
    cypher: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExternalBinding(BaseModel):
    searxng_query: str
    categories: list[str] = Field(default_factory=lambda: ["news"])
    max_results: int = 5


class AdaptiveRules(BaseModel):
    per_user: bool = False
    per_time: bool = False
    per_delta: bool = False
    delta_lookback_seconds: int = 86400


class EnhancementBindings(BaseModel):
    data: DataBinding
    semantic: SemanticBinding | None = None
    external: ExternalBinding | None = None


class EnhancementConfig(BaseModel):
    name: str
    kind: EnhancementKind
    mode: EnhancementMode = EnhancementMode.BATCH
    bindings: EnhancementBindings
    adaptive_rules: AdaptiveRules = Field(default_factory=AdaptiveRules)
    prompt_template: str
    output_schema: dict[str, Any] | None = None
    render_hint: RenderHint
    schedule: str | None = None
    ttl_seconds: int = 600
    cost_cap_usd: float | None = None


class Enhancement(BaseModel):
    id: str
    version: int
    status: Literal["draft", "staging", "published", "archived"]
    author: str | None = None
    config: EnhancementConfig
