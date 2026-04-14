"""Optional homelab envctl secret loader. Only active when ENVCTL_URL is set."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EnvctlBackend:
    def __init__(self):
        self._url = os.environ.get("ENVCTL_URL")
        if not self._url:
            raise ValueError("ENVCTL_URL must be set to use the envctl secrets backend")
        self._cache = {}
        self._loaded = False

    def get(self, key: str) -> Optional[str]:
        if not self._loaded:
            self._load()
        return self._cache.get(key) or os.environ.get(key)

    def _load(self):
        """Fetch all vars from envctl and populate cache."""
        try:
            import httpx
            resp = httpx.get(f"{self._url}/api/v1/config", timeout=5.0)
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                self._cache[item["key"]] = item["value"]
                os.environ.setdefault(item["key"], item["value"])
            self._loaded = True
            logger.info("Loaded %d secrets from envctl", len(self._cache))
        except Exception as e:
            logger.warning("envctl load failed: %s — falling back to env vars", e)
            self._loaded = True
