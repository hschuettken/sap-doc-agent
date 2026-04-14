"""Secrets backend dispatcher."""
import os
from typing import Optional

_backend = None


def get_secret(key: str) -> Optional[str]:
    """Get a secret value. Reads from the configured backend (default: env)."""
    backend = _get_backend()
    return backend.get(key)


def _get_backend():
    global _backend
    if _backend is None:
        backend_name = os.environ.get("SECRETS_BACKEND", "env").lower()
        if backend_name == "env":
            from sap_doc_agent.secrets.env_backend import EnvBackend
            _backend = EnvBackend()
        elif backend_name == "vault":
            from sap_doc_agent.secrets.vault_backend import VaultBackend
            _backend = VaultBackend()
        elif backend_name == "azure-kv":
            from sap_doc_agent.secrets.azure_kv_backend import AzureKVBackend
            _backend = AzureKVBackend()
        elif backend_name == "aws-sm":
            from sap_doc_agent.secrets.aws_sm_backend import AWSSecretsManagerBackend
            _backend = AWSSecretsManagerBackend()
        elif backend_name == "envctl":
            from sap_doc_agent.secrets.envctl_loader import EnvctlBackend
            _backend = EnvctlBackend()
        else:
            from sap_doc_agent.secrets.env_backend import EnvBackend
            _backend = EnvBackend()
    return _backend
