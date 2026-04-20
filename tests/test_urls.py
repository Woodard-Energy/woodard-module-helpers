from unittest.mock import MagicMock

from woodard_module_helpers.urls import prefix, setup_templates


def test_prefix_with_empty_prefix(monkeypatch):
    monkeypatch.setenv("FORWARDED_PREFIX", "")
    assert prefix("/static/style.css") == "/static/style.css"
    assert prefix("style.css") == "/style.css"


def test_prefix_with_set_prefix(monkeypatch):
    monkeypatch.setenv("FORWARDED_PREFIX", "/geology/well-lookup")
    assert prefix("/static/style.css") == "/geology/well-lookup/static/style.css"
    assert prefix("style.css") == "/geology/well-lookup/style.css"


def test_prefix_strips_trailing_slash_on_prefix(monkeypatch):
    monkeypatch.setenv("FORWARDED_PREFIX", "/geology/well-lookup/")
    assert prefix("/static/x.css") == "/geology/well-lookup/static/x.css"


def test_setup_templates_registers_prefix_global():
    fake_templates = MagicMock()
    fake_templates.env.globals = {}
    setup_templates(fake_templates)
    assert "prefix" in fake_templates.env.globals
    assert fake_templates.env.globals["prefix"] is prefix
