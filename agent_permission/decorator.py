import inspect
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, cast

from .errors import PermissionDenied
from .rbac import is_allowed

P = ParamSpec("P")
R = TypeVar("R")
def permission_guard(function: Callable[P, R]) -> Callable[P, R]:
    return _guard(function, None)


def require_permission(permission: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        return _guard(function, permission)
    return decorate


def _guard(function: Callable[P, R], explicit: str | None) -> Callable[P, R]:
    def check_permission() -> None:
        from . import get_current_context

        context = get_current_context()
        subject_id = context.subject_id if context else "anonymous"
        roles = context.roles if context else frozenset()
        permission = explicit or f"{function.__module__}:{function.__qualname__}"
        if not is_allowed(permission, roles):
            raise PermissionDenied(subject_id, permission)
        from . import ApprovalRequired, approval_store, runtime_policies
        policy = runtime_policies.get(permission, {})
        if isinstance(policy, dict) and policy.get("approval_required", False):
            from .approval import ApprovalRequest
            request = ApprovalRequest(permission, subject_id, function.__qualname__)
            approval_store.create(request)
            raise ApprovalRequired(request.approval_id)

    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            check_permission()
            return await function(*args, **kwargs)

        return cast(Callable[P, R], async_wrapper)

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        check_permission()
        return function(*args, **kwargs)

    return cast(Callable[P, R], wrapper)
