import pytest
import os
from spec2sphere.secrets.env_backend import EnvBackend
from spec2sphere.secrets.vault_backend import VaultBackend


def test_env_backend_reads_env(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "super-secret")
    backend = EnvBackend()
    assert backend.get("MY_SECRET") == "super-secret"


def test_env_backend_returns_none_for_missing():
    backend = EnvBackend()
    assert backend.get("NONEXISTENT_KEY_XYZ_123") is None


def test_vault_backend_raises_not_implemented():
    backend = VaultBackend()
    with pytest.raises(NotImplementedError):
        backend.get("some_key")


def test_get_secret_dispatches_to_env(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "env")
    monkeypatch.setenv("TEST_SECRET_VAL", "hello")
    # Reset the global backend
    import spec2sphere.secrets as secrets_mod
    secrets_mod._backend = None
    result = secrets_mod.get_secret("TEST_SECRET_VAL")
    assert result == "hello"
