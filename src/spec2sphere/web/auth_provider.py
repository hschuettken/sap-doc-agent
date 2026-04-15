"""Auth provider abstraction for future SSO swap."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, request) -> Optional[str]:
        """Returns user identifier (e.g. username/email) or None if not authenticated."""

    @abstractmethod
    def get_login_url(self) -> str:
        """Returns the URL to redirect unauthenticated users to."""


class PasswordAuthProvider(AuthProvider):
    """Current bcrypt + session cookie auth. Default for all installs."""

    def __init__(self, password_hash: str, secret_key: str):
        self._hash = password_hash
        self._secret = secret_key

    async def authenticate(self, request) -> Optional[str]:
        """Check session cookie. Returns 'admin' if valid, None otherwise."""
        try:
            from itsdangerous import URLSafeTimedSerializer

            signer = URLSafeTimedSerializer(self._secret)
            session_cookie = request.cookies.get("session")
            if not session_cookie:
                return None
            data = signer.loads(session_cookie, max_age=86400 * 30)
            if data.get("authenticated"):
                return data.get("user", "admin")
            return None
        except Exception:
            return None

    def get_login_url(self) -> str:
        return "/login"

    def verify_password(self, password: str) -> bool:
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode(), self._hash.encode())
        except Exception:
            return False


class OIDCAuthProvider(AuthProvider):
    """Stub — implement with Authlib when SSO is required."""

    async def authenticate(self, request) -> Optional[str]:
        raise NotImplementedError(
            "OIDC auth not implemented. Install authlib and configure OIDC settings. "
            "See docs/INSTALL.md for SSO configuration."
        )

    def get_login_url(self) -> str:
        return "/auth/oidc/login"
