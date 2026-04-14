import pytest
import bcrypt

from sap_doc_agent.web.auth_provider import OIDCAuthProvider, PasswordAuthProvider


@pytest.fixture
def provider():
    password = b"testpassword"
    hashed = bcrypt.hashpw(password, bcrypt.gensalt()).decode()
    return PasswordAuthProvider(password_hash=hashed, secret_key="test-secret-key")


def test_password_provider_verify_correct(provider):
    assert provider.verify_password("testpassword") is True


def test_password_provider_verify_wrong(provider):
    assert provider.verify_password("wrongpassword") is False


def test_password_provider_login_url(provider):
    assert provider.get_login_url() == "/login"


@pytest.mark.asyncio
async def test_password_provider_authenticate_no_cookie(provider):
    from unittest.mock import MagicMock

    request = MagicMock()
    request.cookies = {}
    result = await provider.authenticate(request)
    assert result is None


@pytest.mark.asyncio
async def test_password_provider_authenticate_valid_cookie(provider):
    from itsdangerous import URLSafeTimedSerializer
    from unittest.mock import MagicMock

    signer = URLSafeTimedSerializer("test-secret-key")
    cookie = signer.dumps({"authenticated": True, "user": "admin"})
    request = MagicMock()
    request.cookies = {"session": cookie}
    result = await provider.authenticate(request)
    assert result == "admin"


def test_oidc_provider_raises_not_implemented():
    provider = OIDCAuthProvider()
    with pytest.raises(NotImplementedError):
        import asyncio
        asyncio.run(provider.authenticate(None))
