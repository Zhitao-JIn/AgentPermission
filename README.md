# Agent Permission Guard

一个通过 Python 装饰器保护 Agent 工具函数的轻量权限库。

当前版本使用本地 JSON 文件模拟服务器返回的运行上下文、角色权限和风险策略。

## 快速使用

```python
from agent_permission import (
    initialize,
    permission_guard,
    requires_initialization,
    require_permission,
)


@initialize
def run_agent():
    # 调用函数前会自动重新读取 context.json 和 permissions.json
    return "initialized"


@requires_initialization
@require_permission("read:game:inspect")
def inspect(state):
    return state


@permission_guard
def another_tool(state):
    return state
```

装饰器含义：

- `@initialize`：执行被装饰函数前，先加载本地 context、roles 和 policies。
- `@requires_initialization`：要求权限系统已经初始化；未初始化时抛出 `RuntimeError`，不会执行函数。
- `@permission_guard`：使用函数完整名称作为权限名并执行权限检查。
- `@require_permission("...")`：使用显式权限名执行权限检查。

权限检查失败时，原函数不会执行。

## 配置位置

配置从 Python 进程启动目录下的 `config/` 读取：

```text
启动目录/
├── config/
│   ├── context.json
│   └── permissions.json
└── log/
```

`context.json`：

```json
{
  "subject_id": "pokemon-agent",
  "roles": ["player-agent"],
  "metadata": {
    "episode_id": "ep-001"
  }
}
```

`permissions.json`：

```json
{
  "roles": {
    "player-agent": [
      "read:game:*"
    ],
    "trusted-agent": [
      "execute:game:*"
    ]
  },
  "policies": {
    "execute:game:save": {
      "risk": "HIGH",
      "approval_required": true
    }
  }
}
```

`roles` 决定主体是否拥有权限；`policies` 决定拥有权限后是否需要审批。

每次权限检查都会通过 `get_current_context()` 获取当前 context，不缓存调用时的身份。

身份是**全进程唯一**的普通模块级全局：`set_current_context()` 一调，所有线程立刻看到新的那个，
调用方把受保护的函数放进线程池不需要做任何搬运。代价是同一进程内不能并发跑两个不同 subject，
见「当前边界」。

## 审批

配置了 `approval_required: true` 的权限会进入控制台审批流程：

```text
approve  # 批准并执行原函数
reject   # 拒绝执行
```

审批等待时间为 10 秒。拒绝、超时或权限不足时，原函数不会执行。

审批状态按权限保存到独立文件：

```text
log/data_execute_game_save.json
```

审批状态包括：

```text
PENDING → APPROVED
PENDING → REJECTED
PENDING → EXPIRED
```

## 审计

审计模块负责将权限和审批事件追加写入 JSONL 文件：

```python
from agent_permission.audit import AuditEventType, audit


audit.record(
    event=AuditEventType.PERMISSION_DENIED,
    subject_id="pokemon-agent",
    permission="delete:knowledge:document",
    function_name="delete_document",
)
```

默认输出：

```text
log/audit.jsonl
```

审计记录是历史事件；审批文件保存的是当前审批状态，两者分开存储。

## 运行测试

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

测试覆盖权限允许、权限拒绝、同步/异步装饰器、审批状态、审批文件和审批集成流程。

## 打包和安装

本地构建：

```powershell
python -m build
```

从 GitHub 安装：

```powershell
python -m pip install git+https://github.com/Zhitao-JIn/AgentPermission.git
```

使用方需要从自己的项目根目录启动 Python，并准备上述 `config/` 文件。

## 当前边界

当前版本不包含数据库、Web 审批界面、分布式锁、跨进程审批等待或远程服务器连接。本地 JSON 和控制台用于模拟这些外部能力。

**同一进程内只能有一个身份。** 身份存在普通模块级全局里，换成 ContextVar 就能按上下文隔离、
支持 multi-agent，但那样调用方必须自己把身份搬进每个 worker 线程/task——不搬的话身份会静默
退化成 `anonymous`，而角色表是普通全局、跨线程完好，症状于是表现为"并发时权限全被拒"，
且单线程路径一切正常。这个取舍选了"少一个能力，换掉一整类不会在开发期暴露的失效"。
