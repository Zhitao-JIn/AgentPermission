from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from queue import Empty, Queue
from threading import Thread
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .interfaces.approval_store import ApprovalStore

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 10.0
"""默认审批等待时长。控制台审批是同步阻塞的，调长了会把整局挂住，所以默认取小值；
需要人真的去看一眼再决定的场景，由调用方构造 `ApprovalRequest` 时显式加长。"""


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class ApprovalRequest:
    permission: str
    subject_id: str
    function_name: str
    approval_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = ""
    reason: str = ""
    expires_at: str = ""
    timeout_seconds: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.approval_id:
            self.approval_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.expires_at:
            self.expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=self.timeout_seconds)
            ).isoformat()

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(self.expires_at)

    def seconds_remaining(self) -> float:
        remaining = datetime.fromisoformat(self.expires_at) - datetime.now(timezone.utc)
        return max(0.0, remaining.total_seconds())

    def approve(self, reason: str = "") -> None:
        self._transition(ApprovalStatus.APPROVED, reason)

    def reject(self, reason: str = "") -> None:
        self._transition(ApprovalStatus.REJECTED, reason)

    def expire(self, reason: str = "") -> None:
        self.status = ApprovalStatus.EXPIRED
        if reason:
            self.reason = reason

    def _transition(self, target: ApprovalStatus, reason: str = "") -> None:
        if self.status is ApprovalStatus.PENDING and self.is_expired():
            self.status = ApprovalStatus.EXPIRED
        if self.status is not ApprovalStatus.PENDING:
            raise ValueError(f"Cannot transition {self.status} to {target}")
        self.status = target
        if reason:
            self.reason = reason

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ApprovalRequest":
        return cls(**{**data, "status": ApprovalStatus(data["status"])})  # type: ignore[arg-type]


def wait_for_console_approval(request: ApprovalRequest, store: "ApprovalStore") -> None:
    """在控制台上同步等一个人做决定，超时按 EXPIRED 处理。

    输入格式是 `approve` / `reject`，**可以在同一行后面跟一句理由**
    （`reject 会覆盖存档`）。理由不另起一次 input：第二次读取要单独算超时预算，
    而人已经按下回车之后再让他等一个不确定的超时窗口，比拿不到理由更糟。

    调用方要保证：`request` 处于 PENDING。
    本函数承诺：返回时 `request.status` 一定不是 PENDING，且已经写回 `store`。
    """
    assert request.status is ApprovalStatus.PENDING, (
        f"wait_for_console_approval() got a {request.status} request"
    )

    print("\n=== Approval Required ===")
    print(f"approval_id: {request.approval_id}")
    print(f"subject: {request.subject_id}")
    print(f"permission: {request.permission}")
    print(f"function: {request.function_name}")
    print(
        f"Type 'approve' or 'reject' (optionally followed by a reason) "
        f"within {request.timeout_seconds:.0f} seconds:"
    )

    answers: Queue[str] = Queue()
    Thread(target=lambda: answers.put(input()), daemon=True).start()
    try:
        answer = answers.get(timeout=request.seconds_remaining())
    except Empty:
        answer = ""

    decision, _, reason = answer.strip().partition(" ")
    reason = reason.strip()

    if decision.lower() == "approve":
        request.approve(reason)
    elif decision.lower() == "reject":
        request.reject(reason)
    else:
        request.expire("no answer before the request expired")

    store.save(request)

    assert request.status is not ApprovalStatus.PENDING, "approval left in PENDING"
