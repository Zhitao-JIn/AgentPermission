import inspect
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, cast
from uuid import uuid4

from .audit import AuditEventType, audit
from .errors import ApprovalExpired, ApprovalRejected, PermissionDenied
from .rbac import ALLOWED, APPROVAL_REQUIRED, DENIED, is_allowed

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

        # 一次守卫调用内所有审计记录共用一个 trace_id。审批分支会产生四条记录，
        # 没有它就无法把 checked / created / approved / allowed 串成一条链
        # —— episode_id 的粒度是一整次 run，同名的 checked/allowed 对有几十组，串不起来。
        chain: dict[str, Any] = {
            "episode_id": context.episode_id if context else "unbound",
            "trace_id": str(uuid4()),
        }

        audit.record(
            event=AuditEventType.PERMISSION_CHECKED,
            subject_id=subject_id,
            permission=permission,
            function_name=function.__qualname__,
            **chain,
        )

        authorization = is_allowed(permission, roles)
        approval_id: str | None = None

        if authorization == DENIED:
            reason = f"no role in {sorted(roles)} grants {permission!r}"
            audit.record(
                event=AuditEventType.PERMISSION_DENIED,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
                reason=reason,
                **chain,
            )
            raise PermissionDenied(subject_id, permission)

        if authorization == APPROVAL_REQUIRED:
            from .approval import ApprovalRequest, wait_for_console_approval

            request = ApprovalRequest(permission, subject_id, function.__qualname__)
            approval_id = request.approval_id
            audit.record(
                event=AuditEventType.APPROVAL_CREATED,
                approval_id=approval_id,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
                **chain,
            )
            # 和上面的 `get_current_context` 一样延迟导入：`__init__` 在自己
            # 执行到第 9 行时才 import 本模块，那时 `approval_store` 还没定义，
            # 顶层 import 会直接把整个包变成 import 不进来的状态。
            from . import approval_store

            approval_store.create(request)
            wait_for_console_approval(request, approval_store)

            if request.status.value == "EXPIRED":
                audit.record(
                    event=AuditEventType.APPROVAL_EXPIRED,
                    approval_id=approval_id,
                    subject_id=subject_id,
                    permission=permission,
                    function_name=function.__qualname__,
                    reason=request.reason or "no answer before the request expired",
                    **chain,
                )
                raise ApprovalExpired(request.approval_id)

            if request.status.value != "APPROVED":
                audit.record(
                    event=AuditEventType.APPROVAL_REJECTED,
                    approval_id=approval_id,
                    subject_id=subject_id,
                    permission=permission,
                    function_name=function.__qualname__,
                    reason=request.reason or "rejected without a stated reason",
                    **chain,
                )
                raise ApprovalRejected(request.approval_id)

            audit.record(
                event=AuditEventType.APPROVAL_APPROVED,
                approval_id=approval_id,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
                reason=request.reason,
                **chain,
            )

        assert authorization in (ALLOWED, APPROVAL_REQUIRED), (
            f"unreachable: authorization {authorization!r} was neither denied nor handled"
        )
        audit.record(
            event=AuditEventType.PERMISSION_ALLOWED,
            approval_id=approval_id,
            subject_id=subject_id,
            permission=permission,
            function_name=function.__qualname__,
            **chain,
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
