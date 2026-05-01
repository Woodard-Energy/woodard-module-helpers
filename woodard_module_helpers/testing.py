import os
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI

from woodard_module_helpers.identity import compute_signature


def signed_identity_headers(
    email: str,
    roles: list[str],
    secret: str | None = None,
    *,
    user_id: int | None = None,
    display_name: str | None = None,
) -> dict[str, str]:
    """Build X-Woodard-* headers with a valid HMAC for testing.

    If `secret` omitted, reads from WOODARD_SIGNING_SECRET env var. Used in
    module test suites to simulate an authenticated request from the shell.

    Default behavior (no user_id/display_name) emits the legacy 3-header set
    (X-Woodard-User, -Roles, -Signature) so pre-existing tests keep their
    wire format. Pass user_id AND display_name to emit the new 5-header set
    (adds -User-Id, -Display-Name) used by the post-Entra shell.

    Roles are passed unsorted to the legacy path (preserving caller order)
    and sorted ascending to the 5-header path (matching what
    SessionMiddleware emits in production).
    """
    if secret is None:
        secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not secret:
        raise ValueError(
            "signed_identity_headers needs a secret "
            "(pass explicitly or set WOODARD_SIGNING_SECRET)"
        )
    sig = compute_signature(
        email=email,
        roles=roles,
        secret=secret,
        user_id=user_id,
        display_name=display_name,
    )
    if user_id is not None and display_name is not None:
        return {
            "X-Woodard-User": email,
            "X-Woodard-User-Id": str(user_id),
            "X-Woodard-Display-Name": display_name,
            "X-Woodard-Roles": ",".join(sorted(roles)),
            "X-Woodard-Signature": sig,
        }
    return {
        "X-Woodard-User": email,
        "X-Woodard-Roles": ",".join(roles),
        "X-Woodard-Signature": sig,
    }


@pytest.fixture
def woodard_test_client() -> Callable[..., httpx.AsyncClient]:
    """Return a factory that builds an httpx.AsyncClient over the given ASGI app.

    The factory accepts the user's FastAPI app plus optional identity kwargs
    (email, roles, secret). Returned client has valid signed identity headers
    preconfigured so module tests don't have to think about HMAC.

    Today, this fixture always emits the legacy 3-header identity set
    (X-Woodard-User, -Roles, -Signature); once auth-layer Task 3 extends
    ``current_user`` to verify both formats, this can be extended to accept
    ``user_id`` / ``display_name`` for 5-header round-trip tests.

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
