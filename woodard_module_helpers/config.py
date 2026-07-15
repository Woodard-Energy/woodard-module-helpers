"""Tunable module config — config.yaml defaults + platform overrides.

Modules declare runtime-tunable settings in a config.yaml at the repo root
(see module-template). Developers change values in the platform dev-hub;
this helper fetches the merged result from the shell at startup. Call it
ONCE (module-template wires it in app/config.py next to Settings) — values
apply on restart, matching the platform's restart-to-apply model.

Fail-open: if the shell is unreachable or answers junk, the module boots
with its local config.yaml defaults and logs a warning.

Note on naming: ``Settings.module_name`` holds the platform SLUG (the
``WOODARD_SLUG`` env var, e.g. ``"reservoir-model-optimizer"``), not the
bare module name. The shell's ``/_config`` endpoint contract uses the bare
name (``domain/name/slot``, e.g. ``reservoir/model-optimizer/dev``), so
this module derives it by stripping the ``"{module_domain}-"`` prefix from
the slug.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any

import httpx
import yaml

from woodard_module_helpers.settings import Settings

logger = logging.getLogger("woodard.config")


def _transport() -> httpx.BaseTransport | None:
    """Indirection point so tests can inject httpx.MockTransport."""
    return None


def _local_defaults(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        settings = data.get("settings") if isinstance(data, dict) else None
        if not isinstance(settings, list):
            return {}
        return {
            s["key"]: s["default"] for s in settings
            if isinstance(s, dict) and "key" in s and "default" in s
        }
    except Exception:
        logger.warning("config.yaml at %s could not be parsed; ignoring", config_path)
        return {}


def _bare_module_name(settings: Settings) -> str | None:
    """Strip the "{module_domain}-" prefix off the slug to get the bare name.

    Returns None (misconfiguration) if module_name doesn't start with that
    prefix — the caller should fail open rather than guess.
    """
    prefix = f"{settings.module_domain}-"
    if not settings.module_name.startswith(prefix):
        return None
    return settings.module_name[len(prefix):]


def load_config(*, config_path: str = "config.yaml",
                settings: Settings | None = None,
                timeout: float = 2.0) -> dict[str, Any]:
    """Merged tunable config for this module (key -> value)."""
    settings = settings or Settings()
    defaults = _local_defaults(config_path)
    if not (settings.module_domain and settings.module_name):
        return defaults   # local dev, off-platform: local file only
    name = _bare_module_name(settings)
    if name is None:
        logger.warning(
            "module_name %r does not start with module_domain prefix %r; "
            "using local defaults",
            settings.module_name, f"{settings.module_domain}-",
        )
        return defaults
    ident = f"{settings.module_domain}/{name}/{settings.module_slot}"
    sig = hmac.new(settings.woodard_signing_secret.encode(),
                   ident.encode(), hashlib.sha256).hexdigest()
    url = f"{settings.shell_url.rstrip('/')}/_config/{ident}"
    try:
        with httpx.Client(timeout=timeout, transport=_transport()) as client:
            r = client.get(url, headers={"X-Woodard-Config-Sig": sig})
        r.raise_for_status()
        values = r.json().get("values")
        if not isinstance(values, dict):
            raise ValueError("response missing 'values' mapping")
    except Exception as e:
        logger.warning("config fetch from shell failed (%s); using local defaults", e)
        return defaults
    return {**defaults, **values}
