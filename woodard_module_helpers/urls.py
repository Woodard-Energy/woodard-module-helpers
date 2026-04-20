import os
from typing import Any


def prefix(path: str) -> str:
    """Prepend FORWARDED_PREFIX to `path` if set.

    Used in Jinja templates: <link href="{{ prefix('/static/style.css') }}">
    Handles leading/trailing slash edge cases so callers don't have to.
    """
    fp = os.environ.get("FORWARDED_PREFIX", "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{fp}{path}" if fp else path


def setup_templates(templates: Any) -> None:
    """Register `prefix` as a Jinja global on a Starlette/FastAPI Jinja2Templates.

    Call once during app setup:
        templates = Jinja2Templates(directory="app/templates")
        setup_templates(templates)
    """
    templates.env.globals["prefix"] = prefix
