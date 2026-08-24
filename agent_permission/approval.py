from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from queue import Empty, Queue
from threading import Thread
from uuid import uuid4


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

    def __post_init__(self) -> None:
        if not self.approval_id:
            self.approval_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.expires_at:
            self.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(self.expires_at)

    def approve(self) -> None:
        self._transition(ApprovalStatus.APPROVED)

    def reject(self) -> None:
        self._transition(ApprovalStatus.REJECTED)

    def _transition(self, target: ApprovalStatus) -> None:
        if self.status is ApprovalStatus.PENDING and self.is_expired():
            self.status = ApprovalStatus.EXPIRED
        if self.status is not ApprovalStatus.PENDING:
            raise ValueError(f"Cannot transition {self.status} to {target}")
        self.status = target

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "ApprovalRequest":
        return cls(**{**data, "status": ApprovalStatus(data["status"])})


def wait_for_console_approval(request: ApprovalRequest, store: object) -> None:
    print("\n=== Approval Required ===")
    print(f"approval_id: {request.approval_id}")
    print(f"subject: {request.subject_id}")
    print(f"permission: {request.permission}")
    print(f"function: {request.function_name}")
    print("Type 'approve' or 'reject' within 10 seconds:")

    answers: Queue[str] = Queue()
    Thread(target=lambda: answers.put(input()), daemon=True).start()
    try:
        answer = answers.get(timeout=max(0.0, (datetime.fromisoformat(request.expires_at) - datetime.now(timezone.utc)).total_seconds()))
    except Empty:
        answer = ""
    if answer.strip().lower() == "approve":
        request.approve()
    elif answer.strip().lower() == "reject":
        request.reject()
    else:
        request.status = ApprovalStatus.EXPIRED
    store.save(request)
