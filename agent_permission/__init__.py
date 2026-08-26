import json
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4
from functools import wraps

from .decorator import permission_guard, require_permission
from .errors import ApprovalRequired, PermissionDenied
from .stores import InMemoryApprovalStore


@dataclass(frozen=True)
class PermissionContext:
    """当前身份，外加这一次 run 的标识。

    `episode_id` 是权限流自己的编号，**不从 config 读、也不接受调用方注入**，
    语义严格是「一次 `@initialize` 到下一次之间」。

    它是**必填**的：编号只在 `_load_runtime()` 里铸，而那就是「开新一轮」的定义所在。
    给它默认值等于允许「谁碰巧构造了一个 context 对象」也成为一种边界定义，
    那正是编号会静默漂移的来源。
    """

    subject_id: str
    episode_id: str
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


def _set_current_context(context: PermissionContext) -> None:
    """换掉当前身份。**立即对所有线程生效**，见 `_current_context` 的说明。

    **内部函数，不导出。** 写入口只有 `_load_runtime()` 一个，它就是「开新一轮」
    这个动作本身。曾经这个 setter 是公开的（`42cf055` 把
    `_current_context` 从 ContextVar 改成普通全局时顺手导出的），但库里从来没有
    「运行中换 subject」的意图 —— `_current_context` 是进程级全局，本来就不支持
    并发多 subject。留着它只是多一个能让 `episode_id` 漂移的入口。
    """
    global _current_context
    _current_context = context


_DEFAULT_CONFIG_DIR = Path.cwd() / "config"
runtime_policies: dict[str, object] = {}
runtime_roles: dict[str, set[str]] = {}
_initialized = False


approval_store = InMemoryApprovalStore()
"""全进程唯一的审批存储。

key 是 `approval_id`（uuid4，全局唯一），所以不需要按 permission 分库 ——
那是文件存储时代的产物（一个 permission 一个 `data_*.json`，分的是文件名）。
分库唯一的效果是制造一个「实例拿错了就找不到请求」的洞，然后还得为它加一层缓存。
"""


def _load_runtime(
    context_path: str | Path = _DEFAULT_CONFIG_DIR / "context.json",
    permissions_path: str | Path = _DEFAULT_CONFIG_DIR / "permissions.json",
) -> PermissionContext:
    data = json.loads(Path(context_path).read_text(encoding="utf-8"))
    # `_load_runtime()` 就是「开新一轮」的定义所在，编号在这里铸。
    context = PermissionContext(
        subject_id=str(data["subject_id"]),
        roles=frozenset(data.get("roles", [])),
        metadata=data.get("metadata", {}),
        episode_id=str(uuid4()),
    )
    _set_current_context(context)
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


_inside_initialized_call = False
"""当前是否正处在某个 `@initialize` 函数体内。见 `initialize()` 的嵌套检查。"""


def initialize(function):
    """Initialize the permission runtime before calling the function.

    一次调用 = 一轮，`episode_id` 在这里铸新。

    **嵌套调用直接报错**，不是静默容忍：内层跑完之后外层剩下的部分已经属于新一轮了，
    而 `_current_context` 是普通全局、没有栈，换不回去 —— 症状是一次 run 的审计流
    从中间被切成两段，且没有任何东西会报警。它不该存在，所以让它响。
    """

    def enter():
        global _inside_initialized_call
        assert not _inside_initialized_call, (
            f"nested @initialize: {function.__qualname__} was called from inside another "
            "initialized call, which would silently start a new episode mid-run"
        )
        _load_runtime()
        _inside_initialized_call = True

    def leave():
        global _inside_initialized_call
        _inside_initialized_call = False

    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def async_wrapper(*args, **kwargs):
            enter()
            try:
                return await function(*args, **kwargs)
            finally:
                leave()

        return async_wrapper

    @wraps(function)
    def wrapper(*args, **kwargs):
        enter()
        try:
            return function(*args, **kwargs)
        finally:
            leave()

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
    "approval_store",
    "permission_guard",
    "require_permission",
]
