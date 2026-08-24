import inspect
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, cast

from .audit import *
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
        audit.record(
            event=AuditEventType.PERMISSION_CHECKED,
            subject_id=subject_id,
            permission=permission,
            function_name=function.__qualname__,
        )
        if not is_allowed(permission, roles):
            audit.record(
                event=AuditEventType.PERMISSION_DENIED,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
            )
            raise PermissionDenied(subject_id, permission)
        from . import get_approval_store, runtime_policies
        from .errors import ApprovalExpired, ApprovalRejected
        policy = runtime_policies.get(permission, {})
        if isinstance(policy, dict) and policy.get("approval_required", False):
            from .approval import ApprovalRequest
            from .approval import wait_for_console_approval
            request = ApprovalRequest(permission, subject_id, function.__qualname__)
            audit.record(
                event=AuditEventType.APPROVAL_CREATED,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
            )
            approval_store = get_approval_store(permission)
            approval_store.create(request)
            wait_for_console_approval(request, approval_store)
            if request.status.value == "EXPIRED":
                audit.record(
                    event=AuditEventType.APPROVAL_EXPIRED,
                    subject_id=subject_id,
                    permission=permission,
                    function_name=function.__qualname__,
                )
                raise ApprovalExpired(request.approval_id)
            if request.status.value != "APPROVED":
                audit.record(
                    event=AuditEventType.APPROVAL_REJECTED,
                    subject_id=subject_id,
                    permission=permission,
                    function_name=function.__qualname__,
                )
                raise ApprovalRejected(request.approval_id)
            audit.record(
                event=AuditEventType.APPROVAL_APPROVED,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
            )
        audit.record(
            event=AuditEventType.PERMISSION_ALLOWED,
            subject_id=subject_id,
            permission=permission,
            function_name=function.__qualname__,
        )
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
