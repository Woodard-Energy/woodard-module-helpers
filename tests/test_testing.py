import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from woodard_module_helpers.identity import current_user
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
