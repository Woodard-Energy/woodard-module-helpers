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
    sig = compute_signature("alice@example.com", ["reservoir", "land"], SECRET)
    expected = hmac.new(
        SECRET.encode(),
        b"alice@example.com:reservoir,land",
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected


def _build_app():
    app = FastAPI()

    @app.get("/me")
    def me(user=Depends(current_user)):  # noqa: B008
        return user

    @app.get("/reservoir-only", dependencies=[Depends(require_role("reservoir"))])  # noqa: B008
    def reservoir_only():
        return {"ok": True}

    @app.get("/reservoir-or-land", dependencies=[Depends(require_any_role("reservoir", "land"))])  # noqa: B008
    def reservoir_or_land():
        return {"ok": True}

    return app


def test_valid_signature_returns_user(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200
    assert r.json() == {
        "email": "alice@example.com",
        "user_id": 0,
        "display_name": "alice@example.com",
        "roles": ["reservoir"],
    }


def test_tampered_signature_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    hdrs = _hdrs("alice@example.com", ["reservoir"])
    hdrs["X-Woodard-Signature"] = "0" * 64
    r = client.get("/me", headers=hdrs)
    assert r.status_code == 200
    assert r.json() == {
        "email": "anonymous",
        "user_id": 0,
        "display_name": "anonymous",
        "roles": [],
    }


def test_missing_secret_returns_anonymous(monkeypatch):
    # No secret set → ANONYMOUS_DEV with wildcard (local dev mode).
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200
    assert r.json() == {
        "email": "anonymous",
        "user_id": 0,
        "display_name": "anonymous",
        "roles": ["*"],
    }


def test_missing_headers_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {
        "email": "anonymous",
        "user_id": 0,
        "display_name": "anonymous",
        "roles": [],
    }


def test_require_role_allows_matching(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reservoir-only", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200


def test_require_role_denies_missing(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reservoir-only", headers=_hdrs("alice@example.com", ["land"]))
    assert r.status_code == 403


def test_require_role_allows_wildcard(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reservoir-only", headers=_hdrs("alice@example.com", ["*"]))
    assert r.status_code == 200


def test_require_any_role_allows_either(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/reservoir-or-land", headers=_hdrs("alice@example.com", ["land"]))
    assert r.status_code == 200


def test_tampered_signature_denied_by_role_gate(monkeypatch):
    """Tampered sig → ANONYMOUS_DENY → role gate returns 403 (not 200)."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    hdrs = _hdrs("alice@example.com", ["reservoir"])
    hdrs["X-Woodard-Signature"] = "0" * 64
    r = client.get("/reservoir-only", headers=hdrs)
    assert r.status_code == 403


def test_require_any_role_denies_missing(monkeypatch):
    """User with no matching roles hits require_any_role → 403."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get(
        "/reservoir-or-land",
        headers=_hdrs("alice@example.com", ["drilling"]),
    )
    assert r.status_code == 403


def test_compute_signature_3_field_legacy() -> None:
    """3-header canonical (legacy): "email:roles_csv" — matches today's shell."""
    sig = compute_signature(
        email="jesse@woodardenergy.com",
        roles=["admin", "operator"],
        secret="test-secret",
    )
    expected = hmac.new(
        b"test-secret",
        b"jesse@woodardenergy.com:admin,operator",
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected


def test_compute_signature_5_field_new() -> None:
    """5-header canonical (new): "email|user_id|display_name|roles_csv_sorted"."""
    sig = compute_signature(
        email="jesse@woodardenergy.com",
        roles=["operator", "admin"],  # unsorted on input
        secret="test-secret",
        user_id=42,
        display_name="Jesse Hopper",
    )
    # Roles must be sorted ascending in the canonical string.
    expected = hmac.new(
        b"test-secret",
        b"jesse@woodardenergy.com|42|Jesse Hopper|admin,operator",
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected


def test_compute_signature_3_field_when_extras_none() -> None:
    """Passing user_id=None, display_name=None falls back to legacy 3-field."""
    sig_a = compute_signature(
        email="x@y.z", roles=["a"], secret="s",
        user_id=None, display_name=None,
    )
    sig_b = compute_signature(email="x@y.z", roles=["a"], secret="s")
    assert sig_a == sig_b


def test_compute_signature_falls_back_to_legacy_when_only_user_id_given() -> None:
    """Half-given (only user_id, no display_name) -> legacy 3-header path."""
    sig = compute_signature(
        email="x@y.z", roles=["a"], secret="s", user_id=42,
    )
    legacy = compute_signature(email="x@y.z", roles=["a"], secret="s")
    assert sig == legacy


def test_compute_signature_falls_back_to_legacy_when_only_display_name_given() -> None:
    """Half-given (only display_name, no user_id) -> legacy 3-header path."""
    sig = compute_signature(
        email="x@y.z", roles=["a"], secret="s", display_name="X Y",
    )
    legacy = compute_signature(email="x@y.z", roles=["a"], secret="s")
    assert sig == legacy


def _app_with_me_route() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(user: dict = Depends(current_user)):  # noqa: B008
        return user

    return app


def test_current_user_5_header_returns_full_dict(monkeypatch) -> None:
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")
    app = _app_with_me_route()
    sig = compute_signature(
        email="jesse@woodardenergy.com",
        roles=["operator", "admin"],
        secret="test-secret",
        user_id=42,
        display_name="Jesse Hopper",
    )
    headers = {
        "X-Woodard-User": "jesse@woodardenergy.com",
        "X-Woodard-User-Id": "42",
        "X-Woodard-Display-Name": "Jesse Hopper",
        "X-Woodard-Roles": "admin,operator",
        "X-Woodard-Signature": sig,
    }
    r = TestClient(app).get("/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "email": "jesse@woodardenergy.com",
        "user_id": 42,
        "display_name": "Jesse Hopper",
        "roles": ["admin", "operator"],
    }


def test_current_user_3_header_legacy_still_works(monkeypatch) -> None:
    """Modules running against the old shell still verify successfully."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")
    app = _app_with_me_route()
    sig = compute_signature(
        email="legacy@woodardenergy.com",
        roles=["admin"],
        secret="test-secret",
    )
    headers = {
        "X-Woodard-User": "legacy@woodardenergy.com",
        "X-Woodard-Roles": "admin",
        "X-Woodard-Signature": sig,
    }
    r = TestClient(app).get("/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # Legacy mode: user_id and display_name fall back to safe defaults.
    assert body["email"] == "legacy@woodardenergy.com"
    assert body["roles"] == ["admin"]
    assert body["user_id"] == 0          # sentinel for "no shell user_id provided"
    assert body["display_name"] == "legacy@woodardenergy.com"


def test_current_user_5_header_tampered_signature_returns_anonymous(monkeypatch) -> None:
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")
    app = _app_with_me_route()
    headers = {
        "X-Woodard-User": "attacker@evil.example",
        "X-Woodard-User-Id": "1",
        "X-Woodard-Display-Name": "Mallory",
        "X-Woodard-Roles": "admin",
        "X-Woodard-Signature": "deadbeef" * 8,
    }
    r = TestClient(app).get("/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "anonymous"
    assert body["roles"] == []


def test_current_user_5_header_missing_user_id_falls_back_to_legacy_verify(monkeypatch) -> None:
    """If only display_name is set without user_id, current_user uses legacy verify."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")
    app = _app_with_me_route()
    # Sign with legacy canonical (no user_id/display_name).
    sig = compute_signature(
        email="x@y.z", roles=["a"], secret="test-secret",
    )
    headers = {
        "X-Woodard-User": "x@y.z",
        # X-Woodard-User-Id deliberately omitted to test fallback
        "X-Woodard-Display-Name": "X Y",
        "X-Woodard-Roles": "a",
        "X-Woodard-Signature": sig,
    }
    r = TestClient(app).get("/me", headers=headers)
    body = r.json()
    # Fallback path: display_name is ignored; verifies as legacy 3-header.
    assert body["email"] == "x@y.z"
    assert body["user_id"] == 0
    assert body["display_name"] == "x@y.z"
    assert body["roles"] == ["a"]


def test_current_user_5_header_invalid_user_id_int_returns_anonymous(monkeypatch) -> None:
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")
    app = _app_with_me_route()
    headers = {
        "X-Woodard-User": "x@y.z",
        "X-Woodard-User-Id": "not-an-int",
        "X-Woodard-Display-Name": "X Y",
        "X-Woodard-Roles": "a",
        "X-Woodard-Signature": "ignored",
    }
    r = TestClient(app).get("/me", headers=headers)
    body = r.json()
    assert body["email"] == "anonymous"
    assert body["roles"] == []
