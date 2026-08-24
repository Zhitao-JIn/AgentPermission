# Agent Permission Guard

一个通过 Python 装饰器保护 Agent 工具函数的轻量权限库。

当前版本使用本地 JSON 文件模拟服务器返回的运行上下文和权限策略：

```text
import agent_permission
    ↓
自动读取 config/context.json
自动读取 config/permissions.json
    ↓
调用带装饰器的工具函数
    ↓
RBAC 权限检查
    ↓
允许执行，或拒绝执行
```

## 快速使用

```python
from agent_permission import permission_guard, require_permission


@permission_guard
def inspect(state):
    return state


@require_permission("execute:game:save")
def save(state):
    return state
```

`@permission_guard` 默认使用函数的完整名称作为权限名：

```text
模块路径:函数限定名
```

`@require_permission("...")` 可以显式指定权限名，推荐用于稳定的业务权限。

## 本地配置

`config/context.json` 保存当前运行上下文：

```json
{
  "subject_id": "pokemon-agent",
  "roles": ["player-agent"],
  "metadata": {"episode_id": "ep-001"}
}
```

`config/permissions.json` 同时保存角色权限和风险策略：

```json
{
  "roles": {
    "player-agent": ["read:game:*"]
  },
  "policies": {
    "execute:game:save": {
      "risk": "HIGH",
      "approval_required": true
    }
  }
}
```

导入 `agent_permission` 时，默认配置会自动加载。每次权限检查都会通过 `get_current_context()` 获取当前 context。

## 审批

高风险权限会在控制台显示审批详情，并等待最多 10 秒：

```text
approve  # 执行原函数
reject   # 拒绝执行
```

审批状态写入按权限划分的文件：

```text
log/data_execute_game_save.json
```

审批拒绝或超时，原函数不会执行。

## 审计

审计事件由 `AuditService` 追加写入：

```python
from agent_permission.audit import AuditEventType, audit

audit.record(
    event=AuditEventType.PERMISSION_DENIED,
    subject_id="pokemon-agent",
    permission="delete:knowledge:document",
    function_name="delete_document",
)
```

默认文件为：

```text
log/audit.jsonl
```

## 测试

安装测试依赖后运行：

```text
python -m pip install -e ".[test]"
python -m pytest -q
```

测试覆盖权限允许、权限拒绝、同步/异步装饰器、审批状态、审批文件和审批集成流程。

## 当前边界

当前版本不包含数据库、Web 审批界面、分布式锁、跨进程审批等待或远程服务器连接。LocalFile 存储和本地 JSON 配置用于模拟这些外部能力。
