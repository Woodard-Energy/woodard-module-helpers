__version__ = "0.2.0"

from woodard_module_helpers.db import (
    SchemaBase,
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
    "get_engine",
    "get_session",
    "session_dep",
    # signed_identity_headers is available via woodard_module_helpers.testing
    # (not re-exported here to avoid a pytest hard-dependency at runtime)
]
