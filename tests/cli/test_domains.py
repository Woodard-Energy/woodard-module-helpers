"""Unit tests for woodard_module_helpers.cli._domains.fetch_valid_domains."""

import base64
import json
import logging

import pytest

from woodard_module_helpers.cli._domains import _FALLBACK_DOMAINS, fetch_valid_domains
from woodard_module_helpers.cli._shell import CommandError


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    """Clear the lru_cache between tests so each test gets a fresh call."""
    fetch_valid_domains.cache_clear()
    yield
    fetch_valid_domains.cache_clear()


def _make_gh_response(yaml_text: str) -> str:
    """Encode yaml_text as a GitHub Contents API JSON response."""
    encoded = base64.b64encode(yaml_text.encode("utf-8")).decode("ascii")
    return json.dumps({"content": encoded, "encoding": "base64"})


class TestHappyPath:
    def test_returns_slugs_from_yaml(self, mocker):
        yaml_body = "domains:\n  - slug: drilling\n  - slug: geology\n  - slug: land\n"
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        result = fetch_valid_domains()

        assert result == ("drilling", "geology", "land")

    def test_returns_all_five_known_domains(self, mocker):
        yaml_body = (
            "domains:\n"
            "  - slug: drilling\n"
            "  - slug: geology\n"
            "  - slug: land\n"
            "  - slug: midstream\n"
            "  - slug: reservoir\n"
        )
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        result = fetch_valid_domains()

        assert result == ("drilling", "geology", "land", "midstream", "reservoir")

    def test_result_is_a_tuple(self, mocker):
        yaml_body = "domains:\n  - slug: drilling\n"
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        result = fetch_valid_domains()

        assert isinstance(result, tuple)


class TestGhApiFailure:
    def test_returns_fallback_on_command_error(self, mocker):
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            side_effect=CommandError(["gh", "api", "..."], 1, "", "not authenticated"),
        )

        result = fetch_valid_domains()

        assert result == _FALLBACK_DOMAINS

    def test_logs_warning_on_command_error(self, mocker, caplog):
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            side_effect=CommandError(["gh", "api", "..."], 1, "", "not authenticated"),
        )

        with caplog.at_level(logging.WARNING, logger="woodard_module_helpers.cli._domains"):
            fetch_valid_domains()

        assert any("falling back" in r.message for r in caplog.records)


class TestMalformedJson:
    def test_returns_fallback_on_invalid_json(self, mocker):
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value="this is not json {{{",
        )

        result = fetch_valid_domains()

        assert result == _FALLBACK_DOMAINS

    def test_logs_warning_on_invalid_json(self, mocker, caplog):
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value="not-json",
        )

        with caplog.at_level(logging.WARNING, logger="woodard_module_helpers.cli._domains"):
            fetch_valid_domains()

        assert any("falling back" in r.message for r in caplog.records)

    def test_returns_fallback_when_content_key_missing(self, mocker):
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=json.dumps({"no_content_key": "here"}),
        )

        result = fetch_valid_domains()

        assert result == _FALLBACK_DOMAINS


class TestEmptyDomainsList:
    def test_returns_fallback_for_empty_domains_list(self, mocker):
        yaml_body = "domains: []\n"
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        result = fetch_valid_domains()

        assert result == _FALLBACK_DOMAINS

    def test_logs_warning_for_empty_domains_list(self, mocker, caplog):
        yaml_body = "domains: []\n"
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        with caplog.at_level(logging.WARNING, logger="woodard_module_helpers.cli._domains"):
            fetch_valid_domains()

        assert any("falling back" in r.message for r in caplog.records)

    def test_returns_fallback_for_null_yaml(self, mocker):
        yaml_body = "null\n"
        mocker.patch(
            "woodard_module_helpers.cli._domains.run",
            return_value=_make_gh_response(yaml_body),
        )

        result = fetch_valid_domains()

        assert result == _FALLBACK_DOMAINS
