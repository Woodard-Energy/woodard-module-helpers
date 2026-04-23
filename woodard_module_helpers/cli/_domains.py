"""Fetch the authoritative domain list from intelligence-platform/domains.yaml.

Uses `gh api` so authentication flows through the user's existing gh
credentials (no additional config needed). Cached per-process, so a single
`woodard-cli` invocation performs at most one network call.

Falls back to a conservative hardcoded list if the fetch fails — the shell
will still catch domain mismatches at module-registration time, so the
fallback is a safety net, not a security-critical boundary.
"""

import base64
import functools
import json
import logging

from woodard_module_helpers.cli._shell import CommandError, run

log = logging.getLogger(__name__)

# Fallback used when gh api fetch fails (offline, gh not auth'd, etc.).
# Kept pessimistic — includes the 5 known O&G domains as of v0.1.3. If the
# org adds a new domain to domains.yaml, users offline at that moment will
# get a "domain not valid" error from the CLI but can still succeed by
# running online or by bypassing the CLI for that step.
_FALLBACK_DOMAINS: tuple[str, ...] = (
    "drilling",
    "geology",
    "land",
    "midstream",
    "reservoir",
)

_DOMAINS_PATH = (
    "repos/woodard-energy/intelligence-platform/contents/domains.yaml"
)


@functools.lru_cache(maxsize=1)
def fetch_valid_domains() -> tuple[str, ...]:
    """Return the tuple of valid domain slugs from the shell's domains.yaml.

    Cached per-process (one lru_cache slot). Returns the fallback list + logs
    a warning if anything goes wrong.
    """
    try:
        out = run(["gh", "api", _DOMAINS_PATH])
    except CommandError as e:
        log.warning(
            "fetch_valid_domains: gh api failed (%s); falling back to %s",
            e.stderr.strip() if e.stderr else e,
            _FALLBACK_DOMAINS,
        )
        return _FALLBACK_DOMAINS

    try:
        # gh api returns the Contents API response; content is base64-encoded.
        payload = json.loads(out)
        raw_yaml = base64.b64decode(payload["content"]).decode("utf-8")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning(
            "fetch_valid_domains: could not decode gh api response (%s); "
            "falling back to %s",
            e,
            _FALLBACK_DOMAINS,
        )
        return _FALLBACK_DOMAINS

    # Parse the YAML. Use pyyaml if available; else a tiny inline parser
    # that handles the known schema. pyyaml is already a transitive dep via
    # fastapi -> starlette -> anyio, so available at runtime in practice.
    try:
        import yaml  # type: ignore[import-untyped]

        doc = yaml.safe_load(raw_yaml) or {}
        slugs = tuple(d["slug"] for d in doc.get("domains", []))
        if not slugs:
            raise ValueError("empty domains list")
        return slugs
    except Exception as e:  # noqa: BLE001
        log.warning(
            "fetch_valid_domains: YAML parse failed (%s); falling back to %s",
            e,
            _FALLBACK_DOMAINS,
        )
        return _FALLBACK_DOMAINS
