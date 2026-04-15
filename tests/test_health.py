from fastapi.testclient import TestClient


def get_test_client():
    try:
        from spec2sphere.web.server import create_app

        return TestClient(create_app())
    except Exception:
        from spec2sphere.web.server import app

        return TestClient(app)


def test_healthz_returns_200():
    client = get_test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_returns_200_when_no_db_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    client = get_test_client()
    resp = client.get("/readyz")
    # When nothing configured, should return 200 (unconfigured is not a failure)
    assert resp.status_code == 200


def test_readyz_checks_structure():
    client = get_test_client()
    resp = client.get("/readyz")
    data = resp.json()
    assert "status" in data
    assert "checks" in data
