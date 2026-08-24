from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class ApprovalRequest:
    permission: str
    subject_id: str
    function_name: str
    approval_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.approval_id:
            self.approval_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def approve(self) -> None:
        self._transition(ApprovalStatus.APPROVED)

    def reject(self) -> None:
        self._transition(ApprovalStatus.REJECTED)

    def _transition(self, target: ApprovalStatus) -> None:
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
