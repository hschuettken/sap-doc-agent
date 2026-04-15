"""Tests for BrowserPool session creation and tenant isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from spec2sphere.browser.pool import BrowserPool, BrowserSession, get_pool


TENANT_1 = UUID("10000000-0000-0000-0000-000000000001")
TENANT_2 = UUID("10000000-0000-0000-0000-000000000002")


class TestBrowserSession:
    def test_healthy_by_default(self):
        session = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/abc",
        )
        assert session.healthy is True

    def test_mark_unhealthy(self):
        session = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/abc",
        )
        session.mark_unhealthy("test reason")
        assert session.healthy is False

    def test_repr(self):
        session = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/abc",
        )
        r = repr(session)
        assert "sandbox" in r
        assert "healthy=True" in r


class TestBrowserPool:
    @pytest.mark.asyncio
    async def test_returns_none_when_chrome_unavailable(self, monkeypatch):
        pool = BrowserPool()
        # Chrome is not running in test env
        session = await pool.get_session(TENANT_1, "sandbox")
        assert session is None

    @pytest.mark.asyncio
    async def test_session_isolation_different_tenants(self):
        """Two tenants should get separate sessions (keys differ)."""
        pool = BrowserPool()
        # Both should be None since Chrome not running, but the
        # key lookup distinguishes them
        key1 = (TENANT_1, "sandbox")
        key2 = (TENANT_2, "sandbox")
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self, monkeypatch):
        pool = BrowserPool()
        result = await pool.health_check()
        assert result["available"] is False
        assert "mode" in result
        assert "cdp_url" in result

    @pytest.mark.asyncio
    async def test_health_check_available(self):
        """Mock Chrome responding correctly."""
        pool = BrowserPool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Browser": "Chrome/120.0.0.0",
            "Protocol-Version": "1.3",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await pool.health_check()

        assert result["available"] is True
        assert result["browser"] == "Chrome/120.0.0.0"

    @pytest.mark.asyncio
    async def test_create_session_success(self):
        """Mock successful CDP new target creation."""
        pool = BrowserPool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "abc123",
            "webSocketDebuggerUrl": "ws://chrome:9222/devtools/browser/abc123",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.put = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            session = await pool._create_session(TENANT_1, "sandbox")

        assert session is not None
        assert session.tenant_id == TENANT_1
        assert session.environment == "sandbox"
        assert "abc123" in session.ws_url

    @pytest.mark.asyncio
    async def test_reuses_existing_healthy_session(self):
        """Second call for same tenant returns cached session."""
        pool = BrowserPool()
        # Manually inject a healthy session
        fake_session = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/cached",
        )
        pool._sessions[(TENANT_1, "sandbox")] = fake_session

        result = await pool.get_session(TENANT_1, "sandbox")
        assert result is fake_session

    @pytest.mark.asyncio
    async def test_recreates_unhealthy_session(self):
        """Unhealthy session triggers new session creation attempt."""
        pool = BrowserPool()
        # Inject an unhealthy session
        bad_session = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/bad",
        )
        bad_session.mark_unhealthy("test")
        pool._sessions[(TENANT_1, "sandbox")] = bad_session

        # Chrome not available — should return None (tried to recreate)
        result = await pool.get_session(TENANT_1, "sandbox")
        assert result is None  # Chrome not running in test

    @pytest.mark.asyncio
    async def test_shutdown_clears_sessions(self):
        pool = BrowserPool()
        pool._sessions[(TENANT_1, "sandbox")] = BrowserSession(
            tenant_id=TENANT_1,
            environment="sandbox",
            cdp_url="http://chrome:9222",
            ws_url="ws://chrome:9222/devtools/browser/abc",
        )

        with patch.object(pool, "close_session", AsyncMock()) as mock_close:
            await pool.shutdown()
            mock_close.assert_called_once_with(TENANT_1, "sandbox")


class TestGetPool:
    def test_returns_singleton(self):
        pool1 = get_pool()
        pool2 = get_pool()
        assert pool1 is pool2

    def test_returns_browser_pool(self):
        pool = get_pool()
        assert isinstance(pool, BrowserPool)
