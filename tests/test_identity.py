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
    assert r.json() == {"email": "alice@example.com", "roles": ["reservoir"]}


def test_tampered_signature_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    hdrs = _hdrs("alice@example.com", ["reservoir"])
    hdrs["X-Woodard-Signature"] = "0" * 64
    r = client.get("/me", headers=hdrs)
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": []}


def test_missing_secret_returns_anonymous(monkeypatch):
    # No secret set → ANONYMOUS_DEV with wildcard (local dev mode).
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": ["*"]}


def test_missing_headers_returns_anonymous(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    client = TestClient(_build_app())
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {"email": "anonymous", "roles": []}


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
