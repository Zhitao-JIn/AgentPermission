import json
import inspect
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from functools import wraps

from .decorator import permission_guard, require_permission
from .errors import ApprovalRequired, PermissionDenied
from .rbac import configure_role_permissions
from .stores import LocalFileApprovalStore


@dataclass(frozen=True)
class PermissionContext:
    subject_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)


_current_context: ContextVar[PermissionContext | None] = ContextVar(
    "agent_permission_context", default=None
)


def get_current_context() -> PermissionContext | None:
    return _current_context.get()


def set_current_context(context: PermissionContext) -> None:
    _current_context.set(context)

_DEFAULT_CONFIG_DIR = Path.cwd() / "config"
runtime_policies: dict[str, object] = {}
_initialized = False
_LOG_DIR = _DEFAULT_CONFIG_DIR.parent / "log"


def get_approval_store(permission: str) -> LocalFileApprovalStore:
    safe_permission = permission.replace(":", "_").replace("/", "_")
    return LocalFileApprovalStore(_LOG_DIR / f"data_{safe_permission}.json")


def _load_runtime(
    context_path: str | Path = _DEFAULT_CONFIG_DIR / "context.json",
    permissions_path: str | Path = _DEFAULT_CONFIG_DIR / "permissions.json",
) -> PermissionContext:
    data = json.loads(Path(context_path).read_text(encoding="utf-8"))
    context = PermissionContext(
        subject_id=str(data["subject_id"]),
        roles=frozenset(data.get("roles", [])),
        metadata=data.get("metadata", {}),
    )
    set_current_context(context)
    permissions = json.loads(Path(permissions_path).read_text(encoding="utf-8"))
    global runtime_policies
    runtime_policies = permissions.get("policies", {})
    configure_role_permissions(permissions.get("roles", permissions))
    global _initialized
    _initialized = True
    return context


def initialize(function):
    """Initialize the permission runtime before calling the function."""
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def async_wrapper(*args, **kwargs):
            _load_runtime()
            return await function(*args, **kwargs)

        return async_wrapper

    @wraps(function)
    def wrapper(*args, **kwargs):
        _load_runtime()
        return function(*args, **kwargs)

    return wrapper


def requires_initialization(function):
    """Require initialize() or an @initialize function to run first."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not _initialized:
            raise RuntimeError(
                f"{function.__qualname__} requires permission initialization"
            )
        return function(*args, **kwargs)

    return wrapper


runtime_context = _load_runtime()

__all__ = [
    "PermissionContext",
    "PermissionDenied",
    "ApprovalRequired",
    "get_current_context",
    "initialize",
    "requires_initialization",
    "runtime_context",
    "runtime_policies",
    "get_approval_store",
    "set_current_context",
    "permission_guard",
    "require_permission",
]
