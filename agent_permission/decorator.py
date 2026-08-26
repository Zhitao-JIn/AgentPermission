import inspect
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, cast
from uuid import uuid4

from .approval import ApprovalRequest, wait_for_console_approval
from .audit import AuditEventType, audit
from .errors import ApprovalExpired, ApprovalRejected, PermissionDenied
from .rbac import ALLOWED, APPROVAL_REQUIRED, DENIED, is_allowed
from .runtime import approval_store, get_current_context

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
        context = get_current_context()
        if context is None:
            # 不退化成 anonymous。退化的话症状是「所有权限都被拒」，
            # 而真实原因是「没初始化」，查的人会去翻 permissions.json。
            raise RuntimeError(
                f"{function.__qualname__} was called before the permission runtime was "
                "initialized — wrap the entry point with @initialize"
            )

        subject_id = context.subject_id
        roles = context.roles
        permission = explicit or f"{function.__module__}:{function.__qualname__}"

        # 一次守卫调用内所有审计记录共用一个 trace_id。审批分支会产生四条记录，
        # 没有它就无法把 checked / created / approved / allowed 串成一条链
        # —— episode_id 的粒度是一整次 run，同名的 checked/allowed 对有几十组，串不起来。
        chain: dict[str, Any] = {
            "episode_id": context.episode_id,
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
            request = ApprovalRequest(permission, subject_id, function.__qualname__)
            audit.record(
                event=AuditEventType.APPROVAL_CREATED,
                approval_id=request.approval_id,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
                **chain,
            )
            approval_store.create(request)
            wait_for_console_approval(request, approval_store)

            if request.status.value == "EXPIRED":
                audit.record(
                    event=AuditEventType.APPROVAL_EXPIRED,
                    approval_id=request.approval_id,
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
                    approval_id=request.approval_id,
                    subject_id=subject_id,
                    permission=permission,
                    function_name=function.__qualname__,
                    reason=request.reason or "rejected without a stated reason",
                    **chain,
                )
                raise ApprovalRejected(request.approval_id)

            audit.record(
                event=AuditEventType.APPROVAL_APPROVED,
                approval_id=request.approval_id,
                subject_id=subject_id,
                permission=permission,
                function_name=function.__qualname__,
                reason=request.reason,
                **chain,
            )

        assert authorization in (ALLOWED, APPROVAL_REQUIRED), (
            f"unreachable: authorization {authorization!r} was neither denied nor handled"
        )
        # 不带 approval_id：审批链到 `APPROVAL_APPROVED` 就结束了，这条是守卫自己的结论。
        # 四条审批记录本来就被同一个 trace_id 串着，再带一次是冗余。
        audit.record(
            event=AuditEventType.PERMISSION_ALLOWED,
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
