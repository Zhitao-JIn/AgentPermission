class PermissionDenied(Exception):
    """Raised before a protected function runs without sufficient permission."""

    def __init__(self, subject_id: str, permission: str) -> None:
        self.subject_id = subject_id
        self.permission = permission
        super().__init__(f"Subject {subject_id!r} is not allowed to use {permission!r}")


class ApprovalRequired(Exception):
    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"Approval required: {approval_id}")


class ApprovalRejected(Exception):
    pass


class ApprovalExpired(Exception):
    pass
