import hashlib
import hmac

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from woodard_module_helpers.identity import (
    compute_capability_signature,
    compute_signature,
    current_user,
    has_any_capability,
    has_capability,
    require_any_capability,
    require_any_role,
    require_capability,
    require_role,
)

SECRET = "test-secret"
MODULE_SLUG = "operations-cost-tracker"  # this module's own WOODARD_SLUG, for tests


def _hdrs(email: str, roles: list[str], secret: str = SECRET) -> dict[str, str]:
    sig = compute_signature(email, roles, secret)
    return {
        "X-Woodard-User": email,
        "X-Woodard-Roles": ",".join(roles),
        "X-Woodard-Signature": sig,
    }


def _hdrs5(
    email: str,
    roles: list[str],
    *,
    user_id: int,
    display_name: str,
    secret: str = SECRET,
) -> dict[str, str]:
    """Build the 5-header identity set (post-Entra shell shape)."""
    sig = compute_signature(email, roles, secret, user_id=user_id, display_name=display_name)
    return {
        "X-Woodard-User": email,
        "X-Woodard-User-Id": str(user_id),
        "X-Woodard-Display-Name": display_name,
        "X-Woodard-Roles": ",".join(sorted(roles)),
        "X-Woodard-Signature": sig,
    }


def _cap_hdrs(
    email: str,
    user_id: int,
    capabilities: list[str],
    module_slug: str = MODULE_SLUG,
    secret: str = SECRET,
) -> dict[str, str]:
    sig = compute_capability_signature(email, user_id, module_slug, capabilities, secret)
    return {
        "X-Woodard-Capabilities": ",".join(sorted(capabilities)),
        "X-Woodard-Capabilities-Signature": sig,
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

    @app.get("/truman-enter")
    def truman_enter(request: Request):
        require_capability(request, "truman:enter")
        return {"ok": True}

    @app.get("/truman-any")
    def truman_any(request: Request):
        require_any_capability(request, "truman:enter", "truman:manage")
        return {"ok": True}

    @app.get("/empty-capability")
    def empty_capability(request: Request):
        require_capability(request, "")
        return {"ok": True}

    @app.get("/empty-any-capability")
    def empty_any_capability(request: Request):
        require_any_capability(request)
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
        "capabilities": [],
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
        "capabilities": [],
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
        "capabilities": ["*"],
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
        "capabilities": [],
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
        email="x@y.z",
        roles=["a"],
        secret="s",
        user_id=None,
        display_name=None,
    )
    sig_b = compute_signature(email="x@y.z", roles=["a"], secret="s")
    assert sig_a == sig_b


def test_compute_signature_falls_back_to_legacy_when_only_user_id_given() -> None:
    """Half-given (only user_id, no display_name) -> legacy 3-header path."""
    sig = compute_signature(
        email="x@y.z",
        roles=["a"],
        secret="s",
        user_id=42,
    )
    legacy = compute_signature(email="x@y.z", roles=["a"], secret="s")
    assert sig == legacy


def test_compute_signature_falls_back_to_legacy_when_only_display_name_given() -> None:
    """Half-given (only display_name, no user_id) -> legacy 3-header path."""
    sig = compute_signature(
        email="x@y.z",
        roles=["a"],
        secret="s",
        display_name="X Y",
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
        "capabilities": [],
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
    assert body["user_id"] == 0  # sentinel for "no shell user_id provided"
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
        email="x@y.z",
        roles=["a"],
        secret="test-secret",
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


# --- Capabilities -----------------------------------------------------------


def test_capabilities_header_round_trips(monkeypatch):
    """A validly signed capabilities header round-trips into current_user()."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:enter", "truman:manage"])
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200
    body = r.json()
    assert sorted(body["capabilities"]) == ["truman:enter", "truman:manage"]
    # Identity fields are untouched by the presence of capability headers.
    assert body["email"] == "alice@example.com"
    assert body["user_id"] == 1
    assert body["roles"] == ["reservoir"]


def test_capabilities_signed_for_one_user_rejected_with_different_identity(monkeypatch):
    """The replay case: a capabilities header signed for user A, presented
    alongside user B's (independently, validly signed) identity headers, must
    be rejected. This is the test that justifies binding the capability
    signature to email/user_id — without it this would verify and B would
    inherit A's capabilities."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    # Capabilities signed for alice (user_id=1).
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:manage"])
    # Presented with bob's (user_id=2) validly signed identity headers.
    identity_hdrs = _hdrs5("bob@example.com", ["reservoir"], user_id=2, display_name="Bob")
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "bob@example.com"  # identity itself still verifies
    assert body["capabilities"] == []


def test_capabilities_rejected_when_signed_for_a_different_module(monkeypatch):
    """The cross-module replay case: a capabilities header correctly signed
    (right email, right user_id) for module `drilling-well-card`, presented
    to a module whose own WOODARD_SLUG is `operations-cost-tracker`, must be
    rejected. This is the test that justifies binding the capability
    signature to module_slug — without it, a header captured from one
    module's request would verify at any other module."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)  # this module is operations-cost-tracker
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs(
        "alice@example.com", 1, ["truman:manage"], module_slug="drilling-well-card"
    )
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"  # identity itself still verifies
    assert body["capabilities"] == []


def test_capabilities_rejected_when_module_slug_unset(monkeypatch):
    """Edge case: WOODARD_SLUG unset (bare local dev without the platform).
    A correctly-signed capabilities header must NOT be trusted just because
    there's nothing to compare it against — that would be an accidental
    bypass. Distinct from the dev-wildcard path, which is gated on
    WOODARD_SIGNING_SECRET, not WOODARD_SLUG; the secret IS set here."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.delenv("WOODARD_SLUG", raising=False)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    # Signed with an empty module_slug too — even a header that "matches" the
    # unset slug must not be trusted.
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:manage"], module_slug="")
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["capabilities"] == []


def test_capabilities_tampered_signature_yields_empty_list(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:manage"])
    cap_hdrs["X-Woodard-Capabilities-Signature"] = "0" * 64
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200
    body = r.json()
    assert body["capabilities"] == []
    assert body["email"] == "alice@example.com"  # request still proceeds, not a 500


def test_capabilities_header_without_signature_yields_empty_list(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    r = client.get("/me", headers={**identity_hdrs, "X-Woodard-Capabilities": "truman:enter"})
    assert r.status_code == 200
    assert r.json()["capabilities"] == []


def test_capabilities_signature_without_header_yields_empty_list(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    sig = compute_capability_signature(
        "alice@example.com", 1, MODULE_SLUG, ["truman:enter"], SECRET
    )
    r = client.get("/me", headers={**identity_hdrs, "X-Woodard-Capabilities-Signature": sig})
    assert r.status_code == 200
    assert r.json()["capabilities"] == []


def test_capabilities_absent_headers_yield_empty_list_identity_unaffected(monkeypatch):
    """Absent capability headers → capabilities: [] and every other field is
    byte-identical to what 1.5.0 returned."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200
    assert r.json() == {
        "email": "alice@example.com",
        "user_id": 0,
        "display_name": "alice@example.com",
        "roles": ["reservoir"],
        "capabilities": [],
    }


def test_capabilities_dev_wildcard(monkeypatch):
    """No signing secret (local dev) → capabilities: ["*"], matching roles."""
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/me", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200
    assert r.json()["capabilities"] == ["*"]


def test_compute_capability_signature_binds_email_and_user_id():
    """Same capabilities, different user_id → different signature."""
    sig_a = compute_capability_signature(
        "alice@example.com", 1, MODULE_SLUG, ["truman:enter"], SECRET
    )
    sig_b = compute_capability_signature(
        "alice@example.com", 2, MODULE_SLUG, ["truman:enter"], SECRET
    )
    assert sig_a != sig_b


def test_compute_capability_signature_binds_module_slug():
    """Same email/user_id/capabilities, different module_slug → different signature."""
    sig_a = compute_capability_signature(
        "alice@example.com", 1, "drilling-well-card", ["truman:enter"], SECRET
    )
    sig_b = compute_capability_signature(
        "alice@example.com", 1, "operations-cost-tracker", ["truman:enter"], SECRET
    )
    assert sig_a != sig_b


def test_compute_capability_signature_order_independent():
    """Capability list order doesn't affect the signature (canonical = sorted)."""
    sig_a = compute_capability_signature("a@b.c", 1, MODULE_SLUG, ["z:z", "a:a"], SECRET)
    sig_b = compute_capability_signature("a@b.c", 1, MODULE_SLUG, ["a:a", "z:z"], SECRET)
    assert sig_a == sig_b


# --- require_capability / require_any_capability ----------------------------


def test_require_capability_allows_matching(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:enter"])
    r = client.get("/truman-enter", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200


def test_require_capability_denies_missing(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:manage"])
    r = client.get("/truman-enter", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 403


def test_require_capability_denies_when_none_held(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    r = client.get("/truman-enter", headers=identity_hdrs)
    assert r.status_code == 403


def test_require_capability_allows_admin_role_without_capability(monkeypatch):
    """The `admin` role bypasses capability checks even with zero capabilities."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice")
    r = client.get("/truman-enter", headers=identity_hdrs)
    assert r.status_code == 200


def test_require_capability_allows_dev_wildcard(monkeypatch):
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/truman-enter", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 200


def test_require_capability_denies_empty_argument_even_for_admin(monkeypatch):
    """Deny by default: a falsy capability argument denies regardless of role."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice")
    r = client.get("/empty-capability", headers=identity_hdrs)
    assert r.status_code == 403


def test_require_capability_denies_empty_argument_for_wildcard(monkeypatch):
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    r = client.get("/empty-capability", headers=_hdrs("alice@example.com", ["reservoir"]))
    assert r.status_code == 403


def test_require_any_capability_allows_either(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:manage"])
    r = client.get("/truman-any", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200


def test_require_any_capability_denies_missing(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["other:thing"])
    r = client.get("/truman-any", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 403


def test_require_any_capability_denies_empty_args_even_for_admin(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice")
    r = client.get("/empty-any-capability", headers=identity_hdrs)
    assert r.status_code == 403


# --- has_capability / has_any_capability (pure predicates) ------------------


def test_has_capability_allows_matching():
    user = {"roles": ["reservoir"], "capabilities": ["truman:enter"]}
    assert has_capability(user, "truman:enter") is True


def test_has_capability_denies_missing():
    user = {"roles": ["reservoir"], "capabilities": ["truman:manage"]}
    assert has_capability(user, "truman:enter") is False


def test_has_capability_denies_when_none_held():
    user = {"roles": ["reservoir"], "capabilities": []}
    assert has_capability(user, "truman:enter") is False


def test_has_capability_allows_admin_role_without_capability():
    """The `admin` role bypasses capability checks even with zero capabilities."""
    user = {"roles": ["admin"], "capabilities": []}
    assert has_capability(user, "truman:enter") is True


def test_has_capability_allows_wildcard_capability():
    user = {"roles": ["reservoir"], "capabilities": ["*"]}
    assert has_capability(user, "truman:enter") is True


def test_has_capability_denies_empty_argument_even_for_admin():
    """Deny by default: a falsy capability argument denies regardless of role."""
    user = {"roles": ["admin"], "capabilities": ["*"]}
    assert has_capability(user, "") is False


def test_has_capability_missing_capabilities_key_treated_as_none_held():
    """A `user` dict built by older code with no `capabilities` key at all
    must not raise KeyError — it's treated as holding no capabilities."""
    assert has_capability({"roles": ["reservoir"]}, "truman:enter") is False


def test_has_capability_missing_capabilities_key_still_allows_admin():
    assert has_capability({"roles": ["admin"]}, "truman:enter") is True


def test_has_any_capability_allows_either():
    user = {"roles": ["reservoir"], "capabilities": ["truman:manage"]}
    assert has_any_capability(user, "truman:enter", "truman:manage") is True


def test_has_any_capability_denies_missing():
    user = {"roles": ["reservoir"], "capabilities": ["other:thing"]}
    assert has_any_capability(user, "truman:enter", "truman:manage") is False


def test_has_any_capability_denies_empty_args_even_for_admin():
    user = {"roles": ["admin"], "capabilities": ["*"]}
    assert has_any_capability(user) is False


def test_has_any_capability_missing_capabilities_key_treated_as_none_held():
    assert has_any_capability({"roles": ["reservoir"]}, "truman:enter") is False


def test_has_any_capability_missing_capabilities_key_still_allows_admin():
    assert has_any_capability({"roles": ["admin"]}, "truman:enter") is True


# --- predicate/raiser agreement (discriminating) -----------------------------
#
# These assert has_capability/has_any_capability and require_capability/
# require_any_capability answer the SAME question for the same inputs. They
# are written against independently-observed outcomes (an HTTP status code
# for the raiser, a direct boolean call for the predicate) rather than one
# calling the other, so a future edit that changes one surface's rules
# without changing the other's will break one of these assertions.


def test_has_capability_and_require_capability_agree_across_scenarios(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())

    scenarios = [
        # holds the capability directly
        {
            **_hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
            **_cap_hdrs("alice@example.com", 1, ["truman:enter"]),
        },
        # holds a different capability only
        {
            **_hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
            **_cap_hdrs("alice@example.com", 1, ["truman:manage"]),
        },
        # no capability headers at all
        _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
        # admin role, zero capabilities -> bypass
        _hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice"),
        # admin role AND the capability -> still allowed
        {
            **_hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice"),
            **_cap_hdrs("alice@example.com", 1, ["truman:enter"]),
        },
        # tampered identity signature -> anonymous, deny
        {
            **_hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
            "X-Woodard-Signature": "0" * 64,
        },
    ]

    for headers in scenarios:
        user = client.get("/me", headers=headers).json()
        predicate_says = has_capability(user, "truman:enter")
        raiser_status = client.get("/truman-enter", headers=headers).status_code
        assert predicate_says == (raiser_status == 200), (
            f"has_capability disagreed with require_capability for user={user}: "
            f"predicate={predicate_says}, raiser_status={raiser_status}"
        )


def test_has_capability_and_require_capability_agree_for_dev_wildcard(monkeypatch):
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    client = TestClient(_build_app())
    headers = _hdrs("alice@example.com", ["reservoir"])
    user = client.get("/me", headers=headers).json()
    assert has_capability(user, "truman:enter") is True
    assert client.get("/truman-enter", headers=headers).status_code == 200


def test_has_any_capability_and_require_any_capability_agree_across_scenarios(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())

    scenarios = [
        {
            **_hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
            **_cap_hdrs("alice@example.com", 1, ["truman:manage"]),
        },
        {
            **_hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
            **_cap_hdrs("alice@example.com", 1, ["other:thing"]),
        },
        _hdrs5("alice@example.com", ["admin"], user_id=1, display_name="Alice"),
        _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice"),
    ]

    for headers in scenarios:
        user = client.get("/me", headers=headers).json()
        predicate_says = has_any_capability(user, "truman:enter", "truman:manage")
        raiser_status = client.get("/truman-any", headers=headers).status_code
        assert predicate_says == (raiser_status == 200), (
            f"has_any_capability disagreed with require_any_capability for user={user}: "
            f"predicate={predicate_says}, raiser_status={raiser_status}"
        )


def test_require_role_unaffected_by_capability_headers(monkeypatch):
    """An existing require_role caller is unaffected by capability headers
    riding along on the same request."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:enter"])
    r = client.get("/reservoir-only", headers={**identity_hdrs, **cap_hdrs})
    assert r.status_code == 200


def test_require_capability_is_imperative_not_a_dependency_factory():
    """require_capability(request, capability) is a plain function, not a
    Depends(...) factory like require_role. Calling it with only a
    capability string (no request) raises TypeError — this pins the
    documented call shape (auth-and-deploy.md) and would fail if someone
    reverted to the v1.6.0 factory shape `require_capability(cap)`."""
    with pytest.raises(TypeError):
        require_capability("truman:enter")  # missing required `request` arg


def test_require_any_capability_is_imperative_not_a_dependency_factory():
    with pytest.raises(TypeError):
        require_any_capability()  # missing required `request` arg


def test_current_user_unaffected_by_capability_headers_when_role_only_consumed(monkeypatch):
    """An existing current_user caller that never reads `capabilities` still
    gets everything it read before, unchanged."""
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", MODULE_SLUG)
    client = TestClient(_build_app())
    identity_hdrs = _hdrs5("alice@example.com", ["reservoir"], user_id=1, display_name="Alice")
    cap_hdrs = _cap_hdrs("alice@example.com", 1, ["truman:enter"])
    r = client.get("/me", headers={**identity_hdrs, **cap_hdrs})
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["user_id"] == 1
    assert body["display_name"] == "Alice"
    assert body["roles"] == ["reservoir"]
