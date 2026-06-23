__version__ = "1.3.0"

from woodard_module_helpers.db import (
    SchemaBase,
    build_mssql_url,
    build_postgres_url,
    get_engine,
    get_session,
    session_dep,
)
from woodard_module_helpers.identity import (
    compute_signature,
    current_user,
    require_any_role,
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
    "compute_signature",
    "SchemaBase",
    "build_mssql_url",
    "build_postgres_url",
    "get_engine",
    "get_session",
    "session_dep",
    "run_migrations",
    "upgrade_head",
    # signed_identity_headers is available via woodard_module_helpers.testing
    # (not re-exported here to avoid a pytest hard-dependency at runtime)
]
