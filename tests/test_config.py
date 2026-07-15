"""load_config(): local defaults, shell merge, and fail-open behavior."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from woodard_module_helpers import Settings, load_config

CONFIG_YAML = """\
version: 1
settings:
  - key: strip_history_days
    type: integer
    default: 95
  - key: forecast_mode
    type: choice
    default: hyperbolic
    choices: [hyperbolic, exponential]
"""


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CONFIG_YAML, encoding="utf-8")
    return str(p)


def _settings(**kw):
    # module_name holds the platform SLUG (WOODARD_SLUG), e.g.
    # "reservoir-model-optimizer" — load_config must strip the
    # "{module_domain}-" prefix to get the bare name the shell expects.
    base = dict(module_domain="reservoir", module_name="reservoir-model-optimizer",
                module_slot="dev", woodard_signing_secret="s3cret",
                shell_url="http://shell.test")
    base.update(kw)
    return Settings(**base)


def test_local_defaults_when_not_on_platform(cfg_file):
    # no module_domain/name → never calls the shell
    s = Settings(woodard_signing_secret="x")
    assert load_config(config_path=cfg_file, settings=s) == {
        "strip_history_days": 95, "forecast_mode": "hyperbolic"}


def test_absent_local_file_returns_empty(tmp_path):
    s = Settings(woodard_signing_secret="x")
    assert load_config(config_path=str(tmp_path / "nope.yaml"), settings=s) == {}


def test_fetches_merged_values_with_signed_header(cfg_file, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["sig"] = request.headers.get("x-woodard-config-sig")
        return httpx.Response(200, json={"values": {"strip_history_days": 365,
                                                    "forecast_mode": "hyperbolic"}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("woodard_module_helpers.config._transport", lambda: transport)
    got = load_config(config_path=cfg_file, settings=_settings())
    assert got == {"strip_history_days": 365, "forecast_mode": "hyperbolic"}
    assert seen["url"] == "http://shell.test/_config/reservoir/model-optimizer/dev"
    expected = hmac.new(b"s3cret", b"reservoir/model-optimizer/dev",
                        hashlib.sha256).hexdigest()
    assert seen["sig"] == expected


@pytest.mark.parametrize("response", [
    httpx.Response(404), httpx.Response(500),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": True}),
])
def test_fail_open_to_local_defaults(cfg_file, monkeypatch, response):
    transport = httpx.MockTransport(lambda req: response)
    monkeypatch.setattr("woodard_module_helpers.config._transport", lambda: transport)
    got = load_config(config_path=cfg_file, settings=_settings())
    assert got == {"strip_history_days": 95, "forecast_mode": "hyperbolic"}


def test_fail_open_on_timeout(cfg_file, monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("boom")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("woodard_module_helpers.config._transport", lambda: transport)
    got = load_config(config_path=cfg_file, settings=_settings())
    assert got["strip_history_days"] == 95


def test_settings_shell_url_default():
    assert Settings(woodard_signing_secret="x").shell_url == "http://127.0.0.1:8080"


def test_module_name_not_prefixed_by_domain_returns_local_defaults(cfg_file, monkeypatch):
    # module_name doesn't start with "{module_domain}-" → misconfiguration;
    # fail-open to local defaults without ever calling the shell.
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"values": {}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("woodard_module_helpers.config._transport", lambda: transport)
    s = _settings(module_domain="reservoir", module_name="weird")
    got = load_config(config_path=cfg_file, settings=s)
    assert got == {"strip_history_days": 95, "forecast_mode": "hyperbolic"}
    assert called is False
