# woodard-module-helpers

Shared library for Woodard Intelligence Platform modules.

## v1.0.0 — library-only

As of v1.0.0, this package ships only the shared library (auth helpers,
settings, db helpers, testing fixtures). The previous CLI verbs
(`woodard create-module`, `push-dev`, `request-prod`, etc.) have been
retired in favor of the workspace-driven thin-template workflow — see
`woodard-energy/woodard-modules-workspace`.

## Install (in a module repo)

```toml
# pyproject.toml
dependencies = [
    "woodard-module-helpers @ git+https://github.com/woodard-energy/woodard-module-helpers@v1.0.0",
]
```

## Library API

### `current_user(request)` — identity + auth

```python
from fastapi import Request
from woodard_module_helpers import current_user

def my_handler(request: Request):
    user = current_user(request)   # raises 401 if signature fails
    if "admin" not in user.roles:
        raise HTTPException(403)
```

The shell injects 5 signed headers on every request. `current_user()` verifies
the HMAC signature using `WOODARD_SIGNING_SECRET` and returns a `Principal`.

- If `WOODARD_SIGNING_SECRET` is unset (local dev), returns `ANONYMOUS_DEV` with the `*` wildcard role.
- If the secret is set but signing fails, returns `ANONYMOUS_DENY` with no roles — role gates will deny.

### `Settings` — environment config

```python
from woodard_module_helpers import Settings

s = Settings()
print(s.woodard_slug)   # e.g. "reservoir-model-optimizer"
print(s.woodard_slot)   # "prod" or "dev"
print(s.port)           # TCP port
```

Reads all config from env vars (injected by the platform into `.env`). Never
hardcode VM paths — use `Settings` as the single source of truth.

### `signed_identity_headers(...)` — testing helper

```python
from woodard_module_helpers.testing import signed_identity_headers

headers = signed_identity_headers(
    email="alice@woodardenergy.com",
    user_id=42,
    display_name="Alice",
    roles=["admin", "reservoir"],
    secret="test-secret",
)
```

Produces the 5 signed headers for use in test HTTP clients.

### `setup_templates(app, directory)` — Jinja2 templates

```python
from woodard_module_helpers import setup_templates

templates = setup_templates(app, directory="templates")
```

Configures Jinja2 with the platform's standard template environment.

### Database helpers

```python
from woodard_module_helpers.db import get_engine, get_session

engine = get_engine()   # reads DATABASE_URL from env
```

### URLs helper

```python
from woodard_module_helpers.urls import static_url, embed_url
```

## Pytest plugin

The package registers a `pytest11` entry point that provides the
`woodard_test_client` fixture automatically in any module's test suite:

```python
# tests/test_something.py
def test_my_endpoint(woodard_test_client):
    resp = woodard_test_client.get("/my-endpoint")
    assert resp.status_code == 200
```

The fixture wires up a `TestClient` with properly signed identity headers so
module endpoints that call `current_user()` work correctly in tests.
