from fastapi import FastAPI
from fastapi.testclient import TestClient
from spec2sphere.web.auth import AuthMiddleware, verify_password, hash_password


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
