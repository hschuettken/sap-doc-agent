"""Direct LLM provider — backward compat shim.

Do not delete until all config references are updated to use the new provider names.
"""

from __future__ import annotations

from spec2sphere.llm.base import OpenAICompatibleAdapter

# Alias for backward compatibility
DirectLLMProvider = OpenAICompatibleAdapter
