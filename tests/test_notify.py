"""submit_notification: payload shape, HMAC contract, failure modes.

The signature test recomputes the HMAC exactly the way the shell verifies
it (intelligence-platform app/routes/notifications.py) — the two sides
share this contract, so this test IS the cross-repo vector.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from woodard_module_helpers.notify import NotifyError, submit_notification

SECRET = "test-secret"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("WOODARD_SLUG", "reservoir-model-optimizer")
    monkeypatch.delenv("WOODARD_SHELL_URL", raising=False)


def _capture(monkeypatch, response: httpx.Response | Exception):
    captured = {}

    def fake_post(url, *, content, timeout, headers):
        captured.update(url=url, content=content, timeout=timeout, headers=headers)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx, "post", fake_post)
    return captured


def _ok_response() -> httpx.Response:
    return httpx.Response(200, json={"id": 1, "delivered": 2, "unresolved_emails": []})


def test_payload_and_signature_verify_shell_side(env, monkeypatch):
    cap = _capture(monkeypatch, _ok_response())
    result = submit_notification(
        "Recompute finished", body="41 wells.",
        link="/reservoir/model-optimizer/p/1",
        emails=["a@woodardenergy.com"])
    assert result == {"id": 1, "delivered": 2, "unresolved_emails": []}
    assert cap["url"] == "http://127.0.0.1:8080/_api/notify"

    payload = json.loads(cap["content"])
    assert payload == {
        "module": "reservoir-model-optimizer",
        "title": "Recompute finished",
        "body": "41 wells.",
        "link": "/reservoir/model-optimizer/p/1",
        "emails": ["a@woodardenergy.com"],
    }
    # Recompute the shell-side verification
    ts = cap["headers"]["X-Woodard-Notify-Timestamp"]
    canonical = f"{ts}|{hashlib.sha256(cap['content']).hexdigest()}"
    expected = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert cap["headers"]["X-Woodard-Notify-Signature"] == expected
    assert cap["headers"]["Content-Type"] == "application/json"


def test_audience_variant_omits_emails(env, monkeypatch):
    cap = _capture(monkeypatch, _ok_response())
    submit_notification("New feature", audience="module")
    payload = json.loads(cap["content"])
    assert payload["audience"] == "module"
    assert "emails" not in payload and "link" not in payload


def test_requires_exactly_one_target(env, monkeypatch):
    _capture(monkeypatch, _ok_response())
    with pytest.raises(NotifyError):
        submit_notification("t")  # neither
    with pytest.raises(NotifyError):
        submit_notification("t", emails=["a@x.com"], audience="module")  # both


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("WOODARD_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("WOODARD_SLUG", raising=False)
    with pytest.raises(NotifyError):
        submit_notification("t", emails=["a@x.com"])


def test_non_200_raises(env, monkeypatch):
    _capture(monkeypatch, httpx.Response(401, text="bad signature"))
    with pytest.raises(NotifyError, match="401"):
        submit_notification("t", emails=["a@x.com"])


def test_transport_error_raises(env, monkeypatch):
    _capture(monkeypatch, httpx.ConnectError("refused"))
    with pytest.raises(NotifyError, match="unreachable"):
        submit_notification("t", emails=["a@x.com"])


def test_shell_url_env_override(env, monkeypatch):
    monkeypatch.setenv("WOODARD_SHELL_URL", "http://127.0.0.1:9999/")
    cap = _capture(monkeypatch, _ok_response())
    submit_notification("t", emails=["a@x.com"])
    assert cap["url"] == "http://127.0.0.1:9999/_api/notify"
