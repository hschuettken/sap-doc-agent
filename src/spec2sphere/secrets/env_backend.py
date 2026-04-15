import os
from typing import Optional


class EnvBackend:
    def get(self, key: str) -> Optional[str]:
        return os.environ.get(key)
