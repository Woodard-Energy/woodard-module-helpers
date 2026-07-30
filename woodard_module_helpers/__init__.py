__version__ = "1.6.0"

from woodard_module_helpers.config import load_config
from woodard_module_helpers.db import (
    SchemaBase,
    build_mssql_url,
    build_postgres_url,
    get_engine,
    get_session,
    session_dep,
)
from woodard_module_helpers.identity import (
    compute_capability_signature,
    compute_signature,
    current_user,
    require_any_capability,
    require_any_role,
    require_capability,
    require_role,
)
from woodard_module_helpers.migrations import run_migrations, upgrade_head
from woodard_module_helpers.settings import Settings
from woodard_module_helpers.urls import prefix, setup_templates

__all__ = [
    "__version__",
    "Settings",
    "prefix",
    "setup_templates",
    "current_user",
    "require_role",
    "require_any_role",
    "require_capability",
    "require_any_capability",
    "compute_signature",
    "compute_capability_signature",
    "SchemaBase",
    "build_mssql_url",
    "build_postgres_url",
    "get_engine",
    "get_session",
    "session_dep",
    "run_migrations",
    "upgrade_head",
    "load_config",
    # signed_identity_headers is available via woodard_module_helpers.testing
    # (not re-exported here to avoid a pytest hard-dependency at runtime)
]
