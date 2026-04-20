import hashlib
import hmac

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from woodard_module_helpers.identity import (
    compute_signature,
    current_user,
    require_any_role,
    require_role,
)

SECRET = "test-secret"


def _hdrs(email: str, roles: list[str], secret: str = SECRET) -> dict[str, str]:
    sig = compute_signature(email, roles, secret)
    return {
        "X-Woodard-User": email,
        "X-Woodard-Roles": ",".join(roles),
        "X-Woodard-Signature": sig,
    }


def test_compute_signature_is_hmac_sha256():
    sig = compute_signature("alice@example.com", ["reserves", "land"], SECRET)
    expected = hmac.new(
        SECRET.encode(),
        b"alice@example.com:reserves,land",
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected


def _build_app():
    app = FastAPI()

    @app.get("/me")
    def me(user=Depends(current_user)):  # noqa: B008
        return user

    @app.get("/reserves-only", dependencies=[Depends(require_role("reserves"))])  # noqa: B008
    def reserves_only():
        return {"ok": True}

    @app.get("/reserves-or-land", dependencies=[Depends(require_any_role("reserves", "land"))])  # noqa: B008
    def reserves_or_land():
        return {"ok": True}

    return app


def test_valid_signature_returns_user(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reserves"]))
    assert r.status_code == 200
    assert r.json() == {"email": "alice@example.com", "roles": ["reserves"]}


def test_tampered_signature_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    hdrs = _hdrs("alice@example.com", ["reserves"])
    hdrs["X-Woodard-Signature"] = "0" * 64
    r = client.get("/me", headers=hdrs)
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": ["*"]}


def test_missing_secret_returns_anonymous(monkeypatch):
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reserves"]))
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": ["*"]}


def test_missing_headers_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": ["*"]}


def test_require_role_allows_matching(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reserves-only", headers=_hdrs("alice@example.com", ["reserves"]))
    assert r.status_code == 200


def test_require_role_denies_missing(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reserves-only", headers=_hdrs("alice@example.com", ["land"]))
    assert r.status_code == 403


def test_require_role_allows_wildcard(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reserves-only", headers=_hdrs("alice@example.com", ["*"]))
    assert r.status_code == 200


def test_require_any_role_allows_either(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reserves-or-land", headers=_hdrs("alice@example.com", ["land"]))
    assert r.status_code == 200
