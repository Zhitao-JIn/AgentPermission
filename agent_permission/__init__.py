import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
runtime_policies: dict[str, object] = {}
approval_store = LocalFileApprovalStore(_DEFAULT_CONFIG_DIR / "approvals.json")


def initialize(
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
    return context


runtime_context = initialize()

__all__ = [
    "PermissionContext",
    "PermissionDenied",
    "ApprovalRequired",
    "get_current_context",
    "initialize",
    "runtime_context",
    "runtime_policies",
    "approval_store",
    "set_current_context",
    "permission_guard",
    "require_permission",
]
