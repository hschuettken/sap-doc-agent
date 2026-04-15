import os  # noqa: F401 — used in monkeypatch tests

from fastapi import FastAPI
from fastapi.testclient import TestClient
from spec2sphere.web.auth import AuthMiddleware, verify_password, hash_password, _build_login_html


def test_hash_and_verify():
    hashed = hash_password("test123")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong", hashed)


def test_login_page_accessible_without_auth():
    app = FastAPI()
    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    app = mw
    client = TestClient(app)
    resp = client.get("/ui/login", follow_redirects=False)
    assert resp.status_code == 200 or resp.status_code == 307


def test_ui_redirects_to_login_without_cookie():
    app = FastAPI()

    @app.get("/ui/dashboard")
    async def dashboard():
        return {"page": "dashboard"}

    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.get("/ui/dashboard", follow_redirects=False)
    assert resp.status_code == 307
    assert "/ui/login" in resp.headers.get("location", "")


def test_api_routes_bypass_auth():
    app = FastAPI()

    @app.get("/api/objects")
    async def objects():
        return {"objects": []}

    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.get("/api/objects")
    assert resp.status_code == 200


def test_static_routes_bypass_auth():
    app = FastAPI()

    @app.get("/static/style.css")
    async def css():
        return "body{}"

    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200


def test_login_sets_cookie():
    app = FastAPI()
    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.post("/ui/login", data={"password": "secret"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "session" in resp.cookies


def test_login_wrong_password():
    app = FastAPI()
    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.post("/ui/login", data={"password": "wrong"}, follow_redirects=False)
    assert resp.status_code == 200  # re-renders login page
    assert "session" not in resp.cookies


# ---------------------------------------------------------------------------
# Multi-tenant login form tests
# ---------------------------------------------------------------------------


def test_single_tenant_login_form_has_password_only():
    """Single-tenant mode: login page shows password-only form, no email field."""
    html = _build_login_html(multi_tenant=False)
    assert 'type="password"' in html
    assert 'type="email"' not in html
    assert "Spec2Sphere" in html


def test_multi_tenant_login_form_has_email_field():
    """Multi-tenant mode: login page shows email + password fields."""
    html = _build_login_html(multi_tenant=True)
    assert 'type="email"' in html
    assert 'type="password"' in html
    assert "Spec2Sphere" in html


def test_multi_tenant_login_form_rendered_by_middleware(monkeypatch):
    """When MULTI_TENANT=true the middleware serves the email form on GET /ui/login."""
    monkeypatch.setenv("MULTI_TENANT", "true")
    app = FastAPI()
    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.get("/ui/login", follow_redirects=False)
    assert resp.status_code == 200
    assert 'type="email"' in resp.text


def test_single_tenant_login_form_rendered_by_middleware(monkeypatch):
    """When MULTI_TENANT is not set the middleware serves the password-only form."""
    monkeypatch.delenv("MULTI_TENANT", raising=False)
    app = FastAPI()
    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)
    resp = client.get("/ui/login", follow_redirects=False)
    assert resp.status_code == 200
    assert 'type="email"' not in resp.text
    assert 'type="password"' in resp.text


def test_admin_route_exists():
    """The /ui/admin route should be registered in the UI router."""
    from pathlib import Path
    from spec2sphere.web.ui import create_ui_router

    app = FastAPI()
    router = create_ui_router(Path("/tmp"), config_path=None)
    app.include_router(router)

    paths = [r.path for r in app.routes]
    assert "/ui/admin" in paths


def test_session_sets_state_dict():
    """After successful single-tenant login, state.session is a dict with role key."""
    captured_state = {}

    app = FastAPI()

    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse

    @app.get("/ui/test")
    async def probe(request: _Request):
        captured_state["session"] = getattr(request.state, "session", None)
        captured_state["role"] = getattr(request.state, "user_role", None)
        return JSONResponse({"ok": True})

    mw = AuthMiddleware(app, password_hash=hash_password("secret"), secret_key="test-key")
    client = TestClient(mw)

    # Login to get session cookie
    login_resp = client.post("/ui/login", data={"password": "secret"}, follow_redirects=False)
    assert login_resp.status_code == 303
    cookie = login_resp.cookies.get("session")
    assert cookie

    # Access protected route
    resp = client.get("/ui/test", cookies={"session": cookie}, follow_redirects=False)
    assert resp.status_code == 200
    assert captured_state.get("role") == "admin"
    assert isinstance(captured_state.get("session"), dict)
    assert captured_state["session"].get("role") == "admin"
