import json
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from functools import wraps

from .decorator import permission_guard, require_permission
from .errors import ApprovalRequired, PermissionDenied
from .stores import LocalFileApprovalStore


@dataclass(frozen=True)
class PermissionContext:
    subject_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)


_current_context: PermissionContext | None = None
"""当前身份。**普通模块级全局，不是 ContextVar。**

语义是「全进程唯一，每次 episode 由 `@initialize` 重置一次」。
用 ContextVar 表达这个语义是错的：ContextVar 全局的只是**变量对象本身**，
值存在「当前执行上下文」那张映射表里，而新起的线程带的是一张空表 ——
`get()` 落到 `default=None`，于是 worker 线程里 `runtime_roles`（普通全局）
是好的、身份却退化成 anonymous，所有权限检查静默 DENIED。

这个失效**只在多线程路径上出现**，单线程调用一切正常，所以它不会在开发期暴露，
只会在调用方某天为了降低延迟把调用并发化之后，表现为"权限突然全被拒"。

代价，写在这里而不是留给使用方猜：**同一进程内不能并发跑两个不同 subject。**
要支持 multi-agent 时再换回 ContextVar，届时必须同时提供跨线程/跨任务的
搬运手段（`copy_context()` 或线程池 `initializer`），不能只把类型换回去。
"""


def get_current_context() -> PermissionContext | None:
    """取当前身份。未初始化时返回 None（调用方按 anonymous 处理）。"""
    return _current_context


def set_current_context(context: PermissionContext) -> None:
    """换掉当前身份。**立即对所有线程生效**，见 `_current_context` 的说明。"""
    global _current_context
    _current_context = context

_DEFAULT_CONFIG_DIR = Path.cwd() / "config"
runtime_policies: dict[str, object] = {}
runtime_roles: dict[str, set[str]] = {}
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
    global runtime_roles
    runtime_roles = {
        str(role): set(values)
        for role, values in permissions.get("roles", permissions).items()
    }
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
    "runtime_roles",
    "get_approval_store",
    "set_current_context",
    "permission_guard",
    "require_permission",
]
