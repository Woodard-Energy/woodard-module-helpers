"""Module-side report publishing for the platform's report distribution.

The shell owns WHO receives a report, WHEN, and delivery; a module owns WHAT
the report says. A module declares its reports in `reports.yaml` (read by the
shell on deploy) and registers render functions here:

    from woodard_module_helpers.reports import report, report_router

    @report("route-daily")
    def route_daily(req: RenderRequest) -> RenderResult: ...

    app.include_router(report_router())

The shell calls POST /_reports/render and POST /_reports/scopes over
localhost, signed with WOODARD_SIGNING_SECRET — the same scheme as
/_api/notify in the other direction: canonical f"{ts}|{sha256(body)}",
headers X-Woodard-Report-Timestamp / X-Woodard-Report-Signature, ±300 s.
A bad signature is a 404 (can't-probe, like /_config/).

Spec: intelligence-platform
docs/superpowers/specs/2026-10-15-report-distribution-design.md §4.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

TS_HEADER = "X-Woodard-Report-Timestamp"
SIG_HEADER = "X-Woodard-Report-Signature"
WINDOW_S = 300
AUDIENCES = ("internal", "external")

# A relative link ("/x", not protocol-relative "//x") or an absolute link to
# the platform host. External recipients cannot sign in, so either is a dead
# end at best and an inventory of internal URLs at worst.
_PLATFORM_LINK = re.compile(
    r"""href\s*=\s*["'](?:/(?!/)|https?://platform\.woodardenergy\.com)""",
    re.IGNORECASE,
)


def compute_report_signature(raw: bytes, ts: str, secret: str) -> str:
    canonical = f"{ts}|{hashlib.sha256(raw).hexdigest()}"
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_report_signature(
    raw: bytes, ts: str, sig: str, secret: str, *, now: float | None = None,
) -> bool:
    if not secret or not ts or not sig:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if abs(current - ts_int) > WINDOW_S:
        return False
    return hmac.compare_digest(compute_report_signature(raw, ts, secret), sig)


def contains_platform_link(html: str) -> bool:
    return _PLATFORM_LINK.search(html) is not None


@dataclass(frozen=True)
class RenderRequest:
    report: str
    scope: list[str]
    as_of: date
    audience: str  # "internal" | "external"


@dataclass
class Attachment:
    filename: str
    content_type: str
    content_b64: str


@dataclass
class RenderResult:
    subject: str
    html: str
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    data_as_of: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "html": self.html,
            "text": self.text,
            "attachments": [
                {"filename": a.filename, "content_type": a.content_type,
                 "content_b64": a.content_b64}
                for a in self.attachments
            ],
            "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
        }


@dataclass
class ScopeNode:
    id: str
    label: str
    children: list[ScopeNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label,
                "children": [c.to_dict() for c in self.children]}


class ReportError(Exception):
    """An expected, operator-safe render failure ("no wells in scope").

    The message is returned to the shell and shown on the Reports page, so
    never put secrets or raw driver errors in it. Any OTHER exception is
    logged here and reported to the shell only as "render failed".
    """


RenderFn = Callable[[RenderRequest], RenderResult]
ScopesFn = Callable[[], list[ScopeNode]]


def _parse_render_request(body: dict) -> RenderRequest:
    report = body.get("report")
    scope = body.get("scope", [])
    audience = body.get("audience")
    if not isinstance(report, str) or not report:
        raise HTTPException(status_code=422, detail="report must be a non-empty string")
    if not isinstance(scope, list) or not all(isinstance(s, str) for s in scope):
        raise HTTPException(status_code=422, detail="scope must be a list of strings")
    if audience not in AUDIENCES:
        raise HTTPException(status_code=422, detail="audience must be internal or external")
    try:
        as_of = date.fromisoformat(str(body.get("as_of")))
    except ValueError as e:
        raise HTTPException(status_code=422, detail="as_of must be YYYY-MM-DD") from e
    return RenderRequest(report=report, scope=scope, as_of=as_of, audience=audience)


async def _verified_json(request: Request) -> dict:
    raw = await request.body()
    secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not verify_report_signature(
        raw, request.headers.get(TS_HEADER, ""), request.headers.get(SIG_HEADER, ""), secret,
    ):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="body must be JSON") from e
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object")
    return body


class ReportRegistry:
    def __init__(self) -> None:
        self._renders: dict[str, RenderFn] = {}
        self._scopes: dict[str, ScopesFn] = {}

    def report(self, key: str) -> Callable[[RenderFn], RenderFn]:
        def deco(fn: RenderFn) -> RenderFn:
            if key in self._renders:
                raise ValueError(f"report {key!r} is already registered")
            self._renders[key] = fn
            return fn
        return deco

    def scopes(self, dimension: str) -> Callable[[ScopesFn], ScopesFn]:
        def deco(fn: ScopesFn) -> ScopesFn:
            if dimension in self._scopes:
                raise ValueError(f"scope dimension {dimension!r} is already registered")
            self._scopes[dimension] = fn
            return fn
        return deco

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.post("/_reports/render")
        async def render(request: Request) -> dict:
            req = _parse_render_request(await _verified_json(request))
            fn = self._renders.get(req.report)
            if fn is None:
                raise HTTPException(status_code=404, detail=f"unknown report: {req.report}")
            try:
                result = await run_in_threadpool(fn, req)
            except ReportError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except Exception as e:  # noqa: BLE001 — traceback stays in module logs
                logger.exception("report %s render failed", req.report)
                raise HTTPException(status_code=500, detail="render failed") from e
            if not isinstance(result, RenderResult) or not result.subject or not result.html:
                raise HTTPException(
                    status_code=500, detail="render returned an empty subject or html")
            if req.audience == "external" and contains_platform_link(result.html):
                raise HTTPException(
                    status_code=500, detail="external render contains a platform link")
            return result.to_dict()

        @router.post("/_reports/scopes")
        async def scopes(request: Request) -> dict:
            body = await _verified_json(request)
            fn = self._scopes.get(str(body.get("dimension", "")))
            if fn is None:
                raise HTTPException(status_code=404, detail="unknown scope dimension")
            try:
                nodes = await run_in_threadpool(fn)
            except Exception as e:  # noqa: BLE001
                logger.exception("scope dimension %s failed", body.get("dimension"))
                raise HTTPException(status_code=500, detail="scopes failed") from e
            return {"scopes": [n.to_dict() for n in nodes]}

        return router


registry = ReportRegistry()
report = registry.report
report_scopes = registry.scopes


def report_router() -> APIRouter:
    """Router for the module-wide default registry. Include once in app/main.py."""
    return registry.router()
