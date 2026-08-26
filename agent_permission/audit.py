import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class AuditEventType(StrEnum):
    PERMISSION_CHECKED = "permission_checked"
    PERMISSION_ALLOWED = "permission_allowed"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_CREATED = "approval_created"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"


@dataclass(frozen=True)
class AuditEvent:
    """一条审计记录。

    顶层字段的准入判据只有一条：**它会被拿来当检索或关联的键**。
    不满足的补充信息一律进 `metadata`，因为那是自由字典、不建索引、不做 schema 校验。

    三个 ID 构成一个三层嵌套，**全部由本库自己生成**，不接受调用方注入：

    - `episode_id`：**一次 run** 唯一。`_load_runtime()`（即 `@initialize`）每跑一次
      生成一个，之后整个 run 内所有记录共用。
    - `trace_id`：**一次权限守卫调用**内共用。一次需要审批的调用会产生
      checked → approval_created → approval_approved → allowed 四条记录，
      它们靠这个字段串成一条链。
    - `event_id`：**每条记录**唯一。随机 uuid4，不可排序 —— 它只是行标识，
      不要拿它做 SSE 断线重连的游标（那需要单调递增整数，本类不提供）。

    `approval_id` 是横切的第四个，**只在审批分支存在**，生命周期比上面三个都短：
    request → approve / reject / expire，之后这个请求对象就没用了（存储纯内存实现
    也完全成立）。它进日志不是为了做 join —— 那四条记录本来就被同一个 `trace_id`
    串着 —— 而是因为**它是控制台打给人看的那个字符串**：不记它，日志这一侧就和
    操作员当时看到的东西对不上。

    刻意**不**提供「调用方的业务坐标」这类字段（步号、任务号之类）：那会让本库
    去认识调用方的函数签名。要把审计流和调用方自己的事件流对起来，方向是反的 ——
    调用方读 `get_current_context().episode_id`，在它自己的流里记一次映射即可。

    `reason` 只在决策为「否」时有内容（denied / rejected / expired）；
    allowed 路径上留空是正常的，不是数据丢失。
    """

    event: str
    subject_id: str
    permission: str
    function_name: str
    episode_id: str
    trace_id: str
    approval_id: str | None = None
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditService:
    """把审计事件按行追加到 JSONL 文件。

    调用方要保证：`record()` 的 `trace_id` 在同一次权限守卫调用内保持一致。
    本服务承诺：每次 `record()` 追加恰好一行合法 JSON，并返回写出的事件对象。
    """

    def __init__(self, path: str | Path = "log/audit.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        event: AuditEventType | str,
        subject_id: str,
        permission: str,
        function_name: str,
        *,
        episode_id: str,
        trace_id: str,
        approval_id: str | None = None,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        assert episode_id, "audit.record() requires an episode_id"
        assert trace_id, "audit.record() requires a trace_id"

        audit_event = AuditEvent(
            event=event.value if isinstance(event, AuditEventType) else event,
            subject_id=subject_id,
            permission=permission,
            function_name=function_name,
            episode_id=episode_id,
            trace_id=trace_id,
            approval_id=approval_id,
            reason=reason,
            metadata=metadata or {},
        )
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(audit_event), ensure_ascii=False) + "\n")
        return audit_event


audit = AuditService()


__all__ = ["AuditEvent", "AuditEventType", "AuditService", "audit"]
