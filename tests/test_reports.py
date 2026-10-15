import json
import threading
import time
from datetime import UTC, date, datetime

import httpx
import pytest
from fastapi import FastAPI

from woodard_module_helpers.reports import (
    RenderRequest,
    RenderResult,
    ReportError,
    ReportRegistry,
    ScopeNode,
    compute_report_signature,
    contains_platform_link,
    verify_report_signature,
)
from woodard_module_helpers.testing import signed_report_headers

SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", SECRET)


def _app(reg: ReportRegistry) -> FastAPI:
    app = FastAPI()
    app.include_router(reg.router())
    return app


async def _post(app: FastAPI, path: str, payload: dict, *, headers: dict | None = None):
    raw = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", **(headers or signed_report_headers(raw, SECRET))}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://m") as c:
        return await c.post(path, content=raw, headers=hdrs)


def _render_body(**over) -> dict:
    body = {"report": "r1", "scope": ["a"], "as_of": "2026-10-15", "audience": "internal"}
    body.update(over)
    return body


# --- signature -------------------------------------------------------------

def test_signature_roundtrip():
    raw = b'{"x":1}'
    ts = str(int(time.time()))
    sig = compute_report_signature(raw, ts, SECRET)
    assert verify_report_signature(raw, ts, sig, SECRET)


def test_signature_rejects_tampered_body():
    ts = str(int(time.time()))
    sig = compute_report_signature(b'{"x":1}', ts, SECRET)
    assert not verify_report_signature(b'{"x":2}', ts, sig, SECRET)


def test_signature_rejects_stale_timestamp():
    raw = b"{}"
    ts = str(int(time.time()) - 301)
    sig = compute_report_signature(raw, ts, SECRET)
    assert not verify_report_signature(raw, ts, sig, SECRET)


def test_signature_non_ascii_is_false_not_error():
    assert verify_report_signature(b"{}", str(int(time.time())), "é", SECRET) is False


def test_signature_rejects_empty_secret_and_garbage_ts():
    assert not verify_report_signature(b"{}", "123", "abc", "")
    assert not verify_report_signature(b"{}", "not-a-number", "abc", SECRET)


# --- render endpoint -------------------------------------------------------

async def test_render_happy_path_passes_parsed_request():
    reg = ReportRegistry()
    seen: list[RenderRequest] = []

    @reg.report("r1")
    def r1(req: RenderRequest) -> RenderResult:
        seen.append(req)
        return RenderResult(
            subject="S", html="<p>hi</p>",
            data_as_of=datetime(2026, 10, 15, 6, 0, tzinfo=UTC),
        )

    r = await _post(_app(reg), "/_reports/render", _render_body(scope=["a", "b"]))
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "S"
    assert body["html"] == "<p>hi</p>"
    assert body["attachments"] == []
    assert body["data_as_of"] == "2026-10-15T06:00:00+00:00"
    assert seen == [RenderRequest(report="r1", scope=["a", "b"],
                                  as_of=date(2026, 10, 15), audience="internal")]


async def test_render_runs_in_worker_thread():
    reg = ReportRegistry()
    main_thread = threading.get_ident()
    thread_ids: list[int] = []

    @reg.report("r1")
    def r1(req):
        thread_ids.append(threading.get_ident())
        return RenderResult(subject="S", html="<p>x</p>")

    await _post(_app(reg), "/_reports/render", _render_body())
    assert thread_ids and thread_ids[0] != main_thread


async def test_bad_signature_is_404():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="S", html="x"))
    r = await _post(_app(reg), "/_reports/render", _render_body(),
                    headers={"X-Woodard-Report-Timestamp": str(int(time.time())),
                             "X-Woodard-Report-Signature": "deadbeef"})
    assert r.status_code == 404


async def test_non_ascii_signature_header_is_404():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="S", html="x"))
    r = await _post(_app(reg), "/_reports/render", _render_body(),
                    headers={"X-Woodard-Report-Timestamp": str(int(time.time())),
                             "X-Woodard-Report-Signature": b"\xe9"})  # latin-1 on the wire
    assert r.status_code == 404


async def test_unknown_report_is_404_with_detail():
    r = await _post(_app(ReportRegistry()), "/_reports/render", _render_body(report="nope"))
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown report: nope"


@pytest.mark.parametrize("over", [
    {"audience": "everyone"},
    {"as_of": "15/10/2026"},
    {"scope": "a"},
    {"scope": [1, 2]},
    {"report": ""},
])
async def test_invalid_request_is_422(over):
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="S", html="x"))
    r = await _post(_app(reg), "/_reports/render", _render_body(**over))
    assert r.status_code == 422


async def test_report_error_message_crosses_wire_as_422():
    reg = ReportRegistry()

    @reg.report("r1")
    def r1(req):
        raise ReportError("no wells in scope")

    r = await _post(_app(reg), "/_reports/render", _render_body())
    assert r.status_code == 422
    assert r.json()["detail"] == "no wells in scope"


async def test_unexpected_exception_is_generic_500():
    reg = ReportRegistry()

    @reg.report("r1")
    def r1(req):
        raise RuntimeError("password=hunter2 in a connection string")

    r = await _post(_app(reg), "/_reports/render", _render_body())
    assert r.status_code == 500
    assert r.json() == {"detail": "render failed"}


async def test_empty_subject_or_html_is_500():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="", html="<p>x</p>"))
    r = await _post(_app(reg), "/_reports/render", _render_body())
    assert r.status_code == 500
    assert r.json() == {"detail": "render returned an empty subject or html"}


async def test_external_render_with_platform_link_is_500():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="S", html='<a href="/operations/x">x</a>'))
    r = await _post(_app(reg), "/_reports/render", _render_body(audience="external"))
    assert r.status_code == 500
    assert r.json() == {"detail": "external render contains a platform link"}


async def test_internal_render_may_contain_platform_link():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: RenderResult(subject="S", html='<a href="/operations/x">x</a>'))
    r = await _post(_app(reg), "/_reports/render", _render_body(audience="internal"))
    assert r.status_code == 200


def test_duplicate_registration_raises():
    reg = ReportRegistry()
    reg.report("r1")(lambda req: None)
    with pytest.raises(ValueError):
        reg.report("r1")(lambda req: None)


# --- scopes endpoint -------------------------------------------------------

async def test_scopes_returns_tree():
    reg = ReportRegistry()

    @reg.scopes("hier")
    def hier():
        return [ScopeNode(id="f1", label="Marietta",
                          children=[ScopeNode(id="r1", label="Marietta Route 1")])]

    r = await _post(_app(reg), "/_reports/scopes", {"dimension": "hier"})
    assert r.status_code == 200
    assert r.json() == {"scopes": [
        {"id": "f1", "label": "Marietta",
         "children": [{"id": "r1", "label": "Marietta Route 1", "children": []}]},
    ]}


async def test_unknown_dimension_is_404():
    r = await _post(_app(ReportRegistry()), "/_reports/scopes", {"dimension": "x"})
    assert r.status_code == 404


# --- link detection --------------------------------------------------------

@pytest.mark.parametrize("html,expected", [
    ('<a href="/operations/today">x</a>', True),
    ("<a href='/x'>x</a>", True),
    ('<a href="https://platform.woodardenergy.com/x">x</a>', True),
    ('<a HREF = "/x">x</a>', True),
    ('<a href="//cdn.example.com/x">x</a>', False),
    ('<a href="https://www.weather.gov">x</a>', False),
    ("<p>see /operations in the platform</p>", False),
])
def test_contains_platform_link(html, expected):
    assert contains_platform_link(html) is expected
