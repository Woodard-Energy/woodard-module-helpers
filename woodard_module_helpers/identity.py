import hashlib
import hmac
import logging
import os
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

log = logging.getLogger(__name__)

# Returned when WOODARD_SIGNING_SECRET is unset — local dev convenience.
# Wildcard role/capability allows unverified requests through role and
# capability gates. Only safe when the module port isn't exposed (shell
# enforces the network boundary).
ANONYMOUS_DEV = {
    "email": "anonymous",
    "user_id": 0,
    "display_name": "anonymous",
    "roles": ["*"],
    "capabilities": ["*"],
}

# Returned when the secret IS set but a request can't be verified (missing
# headers, tampered signature). Empty roles/capabilities list denies
# role-gated and capability-gated routes.
ANONYMOUS_DENY = {
    "email": "anonymous",
    "user_id": 0,
    "display_name": "anonymous",
    "roles": [],
    "capabilities": [],
}


def compute_signature(
    email: str,
    roles: list[str],
    secret: str,
    *,
    user_id: int | None = None,
    display_name: str | None = None,
) -> str:
    """HMAC-SHA256 signature.

    Two canonical formats during the auth-layer migration:

    - Legacy 3-header (today's shell `IdentityMiddleware`): canonical is
      ``f"{email}:{roles_csv}"`` where ``roles_csv`` preserves the input
      order. Selected when EITHER ``user_id`` OR ``display_name`` is None.
    - New 5-header (post-Entra shell `SessionMiddleware`): canonical is
      ``f"{email}|{user_id}|{display_name}|{roles_csv}"`` where
      ``roles_csv`` is sorted ascending. Selected when BOTH ``user_id``
      AND ``display_name`` are non-None.

    The "3-header" / "5-header" naming refers to the count of X-Woodard-*
    HTTP headers transmitted with the request, NOT the internal canonical
    string field count. This dual-format support lets one helper version
    work against both the pre-Entra and post-Entra shells during the
    transition window.
    """
    if user_id is not None and display_name is not None:
        roles_csv = ",".join(sorted(roles))
        payload = f"{email}|{user_id}|{display_name}|{roles_csv}".encode()
    else:
        # Legacy 3-field — preserves the original separator (':') and order.
        roles_csv = ",".join(roles)
        payload = f"{email}:{roles_csv}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def compute_capability_signature(
    email: str,
    user_id: int,
    module_slug: str,
    capabilities: list[str],
    secret: str,
) -> str:
    """HMAC-SHA256 signature for the capabilities header pair.

    Canonical payload: ``f"{email}:{user_id}:{module_slug}:{capabilities_csv}"``
    where ``capabilities_csv`` is `capabilities` sorted ascending and joined
    with commas. Sorting before hashing makes the signature order-independent,
    so verification re-sorts the header's parsed list the same way rather
    than hashing the raw header string.

    Binding to `email`/`user_id` AND `module_slug` is the security property,
    not bookkeeping:

    - without the email/user_id binding, a capabilities header captured from
      one user's request could be replayed alongside a different (still
      legitimately signed) user's identity headers;
    - without the module_slug binding, a header minted for one module could
      be replayed at another module by hand — isolation would only hold as
      long as nobody moved the header, not cryptographically.

    Always pass the already-verified identity's email/user_id here — never
    values taken from unverified request headers. `module_slug` is this
    module's own identity (`WOODARD_SLUG`), never anything read off the
    request.
    """
    capabilities_csv = ",".join(sorted(capabilities))
    payload = f"{email}:{user_id}:{module_slug}:{capabilities_csv}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _verify_capabilities(request: Request, *, email: str, user_id: int, secret: str) -> list[str]:
    """Verify the X-Woodard-Capabilities(-Signature) header pair.

    Must be called only after identity has already been verified; `email`
    and `user_id` must be the already-verified values (see
    `compute_capability_signature`). Every failure mode — one header without
    the other, a bad signature, headers simply absent, an unset or mismatched
    `WOODARD_SLUG` — degrades to an empty capability list with a logged
    warning. This never raises and never denies the underlying request; the
    caller still gets an identity, just with zero capabilities.
    """
    caps_header = request.headers.get("x-woodard-capabilities")
    sig_header = request.headers.get("x-woodard-capabilities-signature")

    if caps_header is None and sig_header is None:
        return []
    if caps_header is None or sig_header is None:
        log.warning(
            "capabilities header present without its signature (or vice versa) for user=%s",
            email,
        )
        return []

    module_slug = os.environ.get("WOODARD_SLUG", "")
    if not module_slug:
        # No slug to bind against — a signed header can't be verified as
        # belonging to *this* module. Fail closed rather than silently
        # trusting it (this is not the dev-wildcard path; that's gated on
        # WOODARD_SIGNING_SECRET, which is set here).
        log.warning(
            "WOODARD_SLUG not set; cannot verify capability header's module "
            "binding for user=%s — treating capabilities as untrusted",
            email,
        )
        return []

    capabilities = [c.strip() for c in caps_header.split(",") if c.strip()]
    expected = compute_capability_signature(
        email=email,
        user_id=user_id,
        module_slug=module_slug,
        capabilities=capabilities,
        secret=secret,
    )
    if not hmac.compare_digest(sig_header, expected):
        log.warning("capabilities HMAC mismatch for user=%s", email)
        return []
    return capabilities


def current_user(request: Request) -> dict:
    """FastAPI dependency: verify X-Woodard-* identity and return user dict.

    Accepts both the legacy 3-header format (email, roles, signature) and the
    new 5-header format (email, user_id, display_name, roles, signature). The
    format is selected by presence of X-Woodard-User-Id AND X-Woodard-Display-Name.

    Returns a dict with keys: email, user_id, display_name, roles,
    capabilities. In legacy mode the extra fields fall back to sentinels
    (user_id=0, display_name=email). `capabilities` is verified separately
    (its own header pair, its own signature — see
    `compute_capability_signature`) and always degrades to `[]` rather than
    denying the request when it can't be verified; only role/capability
    *gates* (`require_role`, `require_capability`, ...) turn that into a 403.
    """
    secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not secret:
        log.warning(
            "WOODARD_SIGNING_SECRET not set; returning anonymous with "
            "wildcard role (local dev mode — do not deploy like this)"
        )
        return dict(ANONYMOUS_DEV)

    email = request.headers.get("x-woodard-user", "")
    sig = request.headers.get("x-woodard-signature", "")
    if not email or not sig:
        return dict(ANONYMOUS_DENY)

    user_id_str = request.headers.get("x-woodard-user-id", "")
    display_name = request.headers.get("x-woodard-display-name", "")
    roles_header = request.headers.get("x-woodard-roles", "")
    roles = [r.strip() for r in roles_header.split(",") if r.strip()]

    if user_id_str and display_name:
        # 5-header path. user_id must parse as int.
        try:
            user_id = int(user_id_str)
        except ValueError:
            log.warning("invalid X-Woodard-User-Id (not int) for user=%s", email)
            return dict(ANONYMOUS_DENY)
        expected = compute_signature(
            email=email,
            roles=roles,
            secret=secret,
            user_id=user_id,
            display_name=display_name,
        )
    else:
        # Legacy 3-header path.
        user_id = 0
        display_name = email
        expected = compute_signature(email=email, roles=roles, secret=secret)

    # Both operands are str (hexdigest). compare_digest rejects mixed types.
    if not hmac.compare_digest(sig, expected):
        log.warning("HMAC mismatch for user=%s", email)
        return dict(ANONYMOUS_DENY)

    capabilities = _verify_capabilities(request, email=email, user_id=user_id, secret=secret)

    return {
        "email": email,
        "user_id": user_id,
        "display_name": display_name,
        "roles": roles,
        "capabilities": capabilities,
    }


def require_role(role: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has `role` or wildcard `*`."""

    def _require_role_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        if role in user["roles"] or "*" in user["roles"]:
            return
        raise HTTPException(status_code=403, detail=f"role '{role}' required")

    return _require_role_dep


def require_any_role(*roles: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has any of `roles`."""

    def _require_any_role_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        user_roles = set(user["roles"])
        if "*" in user_roles or user_roles & set(roles):
            return
        raise HTTPException(status_code=403, detail=f"one of {roles} required")

    return _require_any_role_dep


def require_capability(capability: str) -> Callable:
    """FastAPI dependency factory — 403 unless user holds `capability`.

    Bypasses, mirroring `require_role` and the platform's access model:

    - the dev wildcard capability ``"*"`` (same convention as wildcard roles);
    - the platform ``admin`` role — admins bypass capability checks per
      access-model.md, implemented here once so every module inherits it
      instead of re-deriving it.

    Deny by default: a falsy `capability` argument (empty string, `None`)
    always denies — even for an admin or wildcard caller — so a missing or
    blank constant fails closed instead of silently opening the route.
    """

    def _require_capability_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        if not capability:
            raise HTTPException(status_code=403, detail="capability required")
        if "admin" in user["roles"]:
            return
        caps = user.get("capabilities", [])
        if capability in caps or "*" in caps:
            return
        raise HTTPException(status_code=403, detail=f"capability '{capability}' required")

    return _require_capability_dep


def require_any_capability(*capabilities: str) -> Callable:
    """FastAPI dependency factory — 403 unless user holds any of `capabilities`.

    Same bypasses as `require_capability` (wildcard `*`, `admin` role). Deny
    by default: called with no arguments, always denies, even for admin/`*`.
    """

    def _require_any_capability_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        if not capabilities:
            raise HTTPException(status_code=403, detail="capability required")
        if "admin" in user["roles"]:
            return
        user_caps = set(user.get("capabilities", []))
        if "*" in user_caps or user_caps & set(capabilities):
            return
        raise HTTPException(status_code=403, detail=f"one of {capabilities} required")

    return _require_any_capability_dep
