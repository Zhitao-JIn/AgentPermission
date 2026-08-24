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
    event: str
    subject_id: str
    permission: str
    function_name: str
    decision: str = ""
    approval_id: str | None = None
    reason: str = ""
    trace_id: str | None = None
    episode_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditService:
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
        decision: str = "",
        approval_id: str | None = None,
        reason: str = "",
        trace_id: str | None = None,
        episode_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        audit_event = AuditEvent(
            event=event.value if isinstance(event, AuditEventType) else event,
            subject_id=subject_id,
            permission=permission,
            function_name=function_name,
            decision=decision,
            approval_id=approval_id,
            reason=reason,
            trace_id=trace_id,
            episode_id=episode_id,
            metadata=metadata or {},
        )
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(audit_event), ensure_ascii=False) + "\n")
        return audit_event


audit = AuditService()


__all__ = ["AuditEvent", "AuditEventType", "AuditService", "audit"]
