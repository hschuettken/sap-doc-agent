"""Stage 4: Jinja render of prompt_template with gathered context."""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined

from ..config import Enhancement
from .gather import GatheredContext

_env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)


def compose(enh: Enhancement, ctx: GatheredContext, user_id: str | None) -> str:
    tpl = _env.from_string(enh.config.prompt_template)
    return tpl.render(
        dsp_data=ctx.dsp_data,
        brain_nodes=ctx.brain_nodes,
        external_info=ctx.external_info,
        user_state=ctx.user_state,
        user_id=user_id,
        render_hint=enh.config.render_hint.value,
    )
