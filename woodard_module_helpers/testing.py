import os
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI

from woodard_module_helpers.identity import compute_signature


def signed_identity_headers(
    email: str, roles: list[str], secret: str | None = None
) -> dict[str, str]:
    """Build X-Woodard-* headers with a valid HMAC for testing.

    If `secret` omitted, reads from WOODARD_SIGNING_SECRET env var. Used in
    module test suites to simulate an authenticated request from the shell.
    """
    if secret is None:
        secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not secret:
        raise ValueError(
            "signed_identity_headers needs a secret "
            "(pass explicitly or set WOODARD_SIGNING_SECRET)"
        )
    return {
        "X-Woodard-User": email,
        "X-Woodard-Roles": ",".join(roles),
        "X-Woodard-Signature": compute_signature(email, roles, secret),
    }


@pytest.fixture
def woodard_test_client() -> Callable[..., httpx.AsyncClient]:
    """Return a factory that builds an httpx.AsyncClient over the given ASGI app.

    The factory accepts the user's FastAPI app plus optional identity kwargs
    (email, roles, secret). Returned client has valid signed identity headers
    preconfigured so module tests don't have to think about HMAC.

    Usage in a module's test:
        async def test_list(woodard_test_client, app):
            async with woodard_test_client(app, email="t@x", roles=["reservoir"]) as c:
                r = await c.get("/")
                assert r.status_code == 200
    """

    def _make(
        app: FastAPI,
        email: str = "test@example.com",
        roles: list[str] | None = None,
        secret: str | None = None,
    ) -> httpx.AsyncClient:
        if roles is None:
            roles = ["*"]
        hdrs = signed_identity_headers(email, roles, secret=secret)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=hdrs,
        )

    return _make
