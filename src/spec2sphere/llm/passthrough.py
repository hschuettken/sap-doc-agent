"""Copilot passthrough LLM provider — writes structured prompts to files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spec2sphere.llm.base import LLMProvider


class CopilotPassthroughProvider(LLMProvider):
    def __init__(self, output_dir: Path):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        tier: str = "large",
        data_in_context: bool = False,
        caller: str | None = None,
    ) -> Optional[str]:
        self._write_prompt(prompt, system=system)
        return None

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = "large",
        data_in_context: bool = False,
        caller: str | None = None,
    ) -> Optional[dict]:
        full_prompt = (
            f"{prompt}\n\nRespond with JSON matching this schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        )
        self._write_prompt(full_prompt, system=system)
        return None

    def is_available(self) -> bool:
        return False

    def _write_prompt(self, prompt: str, system: str = "") -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = self._output_dir / f"prompt_{ts}.md"
        parts = ["# Copilot Prompt\n"]
        parts.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        if system:
            parts.append(f"## System Context\n\n{system}\n")
        parts.append(f"## Prompt\n\n{prompt}\n")
        parts.append("## Instructions\n\nPaste the above into M365 Copilot and save the response.\n")
        path.write_text("\n".join(parts))
        return path
