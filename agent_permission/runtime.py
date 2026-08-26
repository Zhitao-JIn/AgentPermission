"""运行时状态：当前身份、角色表、策略表、审批存储，以及初始化入口。

**这些东西曾经住在 `__init__.py` 里**，于是 `decorator.py` 要用它们就得反向 import
自己的包，形成 包 → 子模块 → 包 的循环，只能靠函数体内的延迟 import 绕开。
搬到这里之后依赖是单向的：`__init__` → `decorator` → `runtime`，延迟 import 全部消失。

`__init__.py` 的职责收回成纯粹的门面（re-export），不再是状态的宿主。
"""

import inspect
import json
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

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
`get()` 落到 `default=None`，于是 worker 线程里 `_runtime_roles`（普通全局）
是好的、身份却退化成 anonymous，所有权限检查静默 DENIED。

这个失效**只在多线程路径上出现**，单线程调用一切正常，所以它不会在开发期暴露，
只会在调用方某天为了降低延迟把调用并发化之后，表现为"权限突然全被拒"。

代价，写在这里而不是留给使用方猜：**同一进程内不能并发跑两个不同 subject。**
要支持 multi-agent 时再换回 ContextVar，届时必须同时提供跨线程/跨任务的
搬运手段（`copy_context()` 或线程池 `initializer`），不能只把类型换回去。
"""


def get_current_context() -> PermissionContext | None:
    """取当前身份。未初始化时返回 None —— 守卫会把这种情况当错误抛出，不退化成 anonymous。"""
    return _current_context

_DEFAULT_CONFIG_DIR = Path.cwd() / "config"
_runtime_policies: dict[str, object] = {}
_runtime_roles: dict[str, set[str]] = {}
_initialized = False


def get_runtime_roles() -> dict[str, set[str]]:
    """取角色 → 授权串的表。

    **必须走这个 getter，不能直接导出那个全局。** `_load_runtime()` 每轮把它
    **整个重新绑定**，而 `from .runtime import _runtime_roles` 绑的是当时那个对象 ——
    拿到的会是初始空字典，之后永不更新，症状是「改了 permissions.json 不生效」
    或者「所有权限都被拒」。同 `get_current_context()`。
    """
    return _runtime_roles


def get_runtime_policies() -> dict[str, object]:
    """取 permission → 策略（`approval_required` 等）的表。理由同 `get_runtime_roles()`。"""
    return _runtime_policies

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
    """读两个 config 文件，铸新编号，装好身份与角色/策略表。

    **只在 `@initialize` 里被调用**，不再有 import 时的模块级调用 ——
    那会让 `import agent_permission` 依赖当前工作目录下存在 `config/`，
    从别的目录 import、或者在测试里 import，都会直接炸。
    """
    data = json.loads(Path(context_path).read_text(encoding="utf-8"))
    # `_load_runtime()` 就是「开新一轮」的定义所在，编号在这里铸。
    context = PermissionContext(
        subject_id=str(data["subject_id"]),
        roles=frozenset(data.get("roles", [])),
        metadata=data.get("metadata", {}),
        episode_id=str(uuid4()),
    )

    global _current_context
    _current_context = context

    permissions = json.loads(Path(permissions_path).read_text(encoding="utf-8"))
    global _runtime_policies
    _runtime_policies = permissions.get("policies", {})
    global _runtime_roles
    _runtime_roles = {
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
