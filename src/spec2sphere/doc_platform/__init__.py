"""Doc platform adapter factory."""

from __future__ import annotations
import os
from spec2sphere.config import DocPlatformConfig
from spec2sphere.doc_platform.base import DocPlatformAdapter


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_doc_adapter(cfg: DocPlatformConfig) -> DocPlatformAdapter:
    if cfg.type == "bookstack":
        from spec2sphere.doc_platform.bookstack import BookStackAdapter

        token = _resolve_env(cfg.auth.token_env)
        parts = token.split(":", 1)
        return BookStackAdapter(
            base_url=cfg.url, token_id=parts[0], token_secret=parts[1] if len(parts) > 1 else parts[0]
        )

    if cfg.type == "outline":
        from spec2sphere.doc_platform.outline import OutlineAdapter

        return OutlineAdapter(base_url=cfg.url, api_key=_resolve_env(cfg.auth.token_env))

    if cfg.type == "confluence":
        from spec2sphere.doc_platform.confluence import ConfluenceAdapter

        if cfg.auth.type == "api_token":
            return ConfluenceAdapter(url=cfg.url, token=_resolve_env(cfg.auth.token_env))
        elif cfg.auth.type == "basic":
            return ConfluenceAdapter(
                url=cfg.url, username=_resolve_env(cfg.auth.username_env), password=_resolve_env(cfg.auth.password_env)
            )

    raise ValueError(f"Unknown doc platform type: {cfg.type}")
