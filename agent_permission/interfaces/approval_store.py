from typing import Protocol

from ..approval import ApprovalRequest


class ApprovalStore(Protocol):
    def create(self, request: ApprovalRequest) -> None: ...

    def save(self, request: ApprovalRequest) -> None: ...
