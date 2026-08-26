"""Submit platform notifications (the topbar bell) to the shell.

POST {WOODARD_SHELL_URL}/_api/notify, HMAC-gated with the same
WOODARD_SIGNING_SECRET the platform injects for identity verification —
no extra setup for a registered module. Treat notifications as
best-effort: catch NotifyError around calls that must not fail the
caller's own request. Contract:
intelligence-platform docs/superpowers/specs/2026-08-26-user-notifications-design.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import httpx

DEFAULT_SHELL_URL = "http://127.0.0.1:8080"


class NotifyError(RuntimeError):
    """A notification could not be submitted (config, transport, or shell
    rejection). Single exception type so callers can catch one thing."""


def submit_notification(
    title: str,
    *,
    body: str = "",
    link: str | None = None,
    emails: list[str] | None = None,
    audience: str | None = None,
    timeout: float = 5.0,
) -> dict:
    """Submit a notification to platform users.

    Target with exactly one of:
      emails=[...]        specific users (unknown emails come back in the
                          result's "unresolved_emails", not an error)
      audience="module"   everyone granted access to YOUR module

    link, if given, must be a relative platform path ("/domain/name/...").
    Returns the shell's response: {"id", "delivered", "unresolved_emails"}.
    Raises NotifyError on missing env, bad targeting, transport failure,
    or a non-200 from the shell.
    """
    secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    slug = os.environ.get("WOODARD_SLUG", "")
    if not secret or not slug:
        raise NotifyError(
            "WOODARD_SIGNING_SECRET and WOODARD_SLUG must be set "
            "(injected automatically on the platform; local dev has no shell)")
    if (emails is None) == (audience is None):
        raise NotifyError("pass exactly one of emails= or audience=")

    payload: dict = {"module": slug, "title": title, "body": body}
    if link is not None:
        payload["link"] = link
    if emails is not None:
        payload["emails"] = emails
    if audience is not None:
        payload["audience"] = audience

    raw = json.dumps(payload, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    canonical = f"{ts}|{hashlib.sha256(raw).hexdigest()}"
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    base = os.environ.get("WOODARD_SHELL_URL", DEFAULT_SHELL_URL).rstrip("/")
    try:
        resp = httpx.post(
            f"{base}/_api/notify",
            content=raw,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "X-Woodard-Notify-Timestamp": ts,
                "X-Woodard-Notify-Signature": sig,
            },
        )
    except httpx.HTTPError as exc:
        raise NotifyError(f"shell unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise NotifyError(
            f"notify failed: HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()
