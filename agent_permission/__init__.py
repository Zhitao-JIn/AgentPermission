"""包的门面：只做 re-export，不持有任何运行时状态。

状态住在 `runtime.py`。曾经它们住在这里，导致 `decorator.py` 要反向 import 自己的包
（包 → 子模块 → 包 的循环），只能靠函数体内的延迟 import 绕开。依赖现在是单向的。
"""

from .decorator import permission_guard, require_permission
from .errors import (
    ApprovalExpired,
    ApprovalRejected,
    ApprovalRequired,
    PermissionDenied,
)
from .runtime import (
    PermissionContext,
    approval_store,
    get_current_context,
    get_runtime_policies,
    get_runtime_roles,
    initialize,
    requires_initialization,
)

__all__ = [
    "PermissionContext",
    "PermissionDenied",
    "ApprovalRequired",
    "ApprovalRejected",
    "ApprovalExpired",
    "get_current_context",
    "get_runtime_roles",
    "get_runtime_policies",
    "initialize",
    "requires_initialization",
    "approval_store",
    "permission_guard",
    "require_permission",
]
