import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from woodard_module_helpers.identity import compute_signature, current_user
from woodard_module_helpers.testing import signed_identity_headers


def test_signed_identity_headers_produces_valid_signature(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "test-secret")

    app = FastAPI()

    @app.get("/me")
    def me(u=Depends(current_user)):  # noqa: B008
        return u

    client = TestClient(app)
    hdrs = signed_identity_headers(
        "bob@example.com", ["drilling"], secret="test-secret"
    )
    r = client.get("/me", headers=hdrs)
    assert r.status_code == 200
    assert r.json() == {"email": "bob@example.com", "roles": ["drilling"]}


def test_signed_identity_headers_picks_up_env_secret(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "env-secret")

    app = FastAPI()

    @app.get("/me")
    def me(u=Depends(current_user)):  # noqa: B008
        return u

    client = TestClient(app)
    # secret omitted — should read from env.
    hdrs = signed_identity_headers("carol@example.com", ["land"])
    r = client.get("/me", headers=hdrs)
    assert r.status_code == 200
    assert r.json()["email"] == "carol@example.com"


@pytest.mark.asyncio
async def test_woodard_test_client_fixture_sends_signed_headers(
    monkeypatch, woodard_test_client
):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "s3cret")

    app = FastAPI()

    @app.get("/me")
    def me(u=Depends(current_user)):  # noqa: B008
        return u

    async with woodard_test_client(
        app, email="dave@example.com", roles=["midstream"], secret="s3cret"
    ) as c:
        r = await c.get("/me")
        assert r.status_code == 200
        assert r.json() == {"email": "dave@example.com", "roles": ["midstream"]}


def test_signed_identity_headers_raises_without_secret(monkeypatch):
    """Neither explicit secret nor env var set → clear ValueError."""
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    with pytest.raises(ValueError, match="WOODARD_SIGNING_SECRET"):
        signed_identity_headers("x@example.com", ["reservoir"])


def test_signed_identity_headers_legacy_3_header() -> None:
    """No user_id/display_name -> emits the original 3 headers."""
    h = signed_identity_headers(
        email="jesse@woodardenergy.com",
        roles=["admin"],
        secret="test-secret",
    )
    assert set(h.keys()) == {
        "X-Woodard-User",
        "X-Woodard-Roles",
        "X-Woodard-Signature",
    }
    assert h["X-Woodard-User"] == "jesse@woodardenergy.com"
    assert h["X-Woodard-Roles"] == "admin"


def test_signed_identity_headers_5_header_with_user_id_and_display_name() -> None:
    """Explicit user_id/display_name -> emits all 5 headers with correct signature."""
    h = signed_identity_headers(
        email="jesse@woodardenergy.com",
        roles=["operator", "admin"],
        secret="test-secret",
        user_id=42,
        display_name="Jesse Hopper",
    )
    assert set(h.keys()) == {
        "X-Woodard-User",
        "X-Woodard-User-Id",
        "X-Woodard-Display-Name",
        "X-Woodard-Roles",
        "X-Woodard-Signature",
    }
    assert h["X-Woodard-User"] == "jesse@woodardenergy.com"
    assert h["X-Woodard-User-Id"] == "42"
    assert h["X-Woodard-Display-Name"] == "Jesse Hopper"
    assert h["X-Woodard-Roles"] == "admin,operator"  # sorted

    # Signature must match what compute_signature produces for the 5-field
    # canonical (email|user_id|display_name|roles_sorted).
    expected_sig = compute_signature(
        email="jesse@woodardenergy.com",
        roles=["operator", "admin"],
        secret="test-secret",
        user_id=42,
        display_name="Jesse Hopper",
    )
    assert h["X-Woodard-Signature"] == expected_sig


def test_signed_identity_headers_auto_user_id_and_display_name_default_none() -> None:
    """Backward compat: existing tests calling without kwargs get 3-header set.

    The auto-derive defaults from the spec are ONLY applied on the consumer
    side (current_user); the test helper preserves the legacy default
    behavior so existing tests don't silently get 5-header output.
    """
    h = signed_identity_headers(
        email="x@y.z", roles=["a"], secret="s",
    )
    assert "X-Woodard-User-Id" not in h
    assert "X-Woodard-Display-Name" not in h
