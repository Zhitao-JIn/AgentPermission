import json
from pathlib import Path

from ..approval import ApprovalRequest


class LocalFileApprovalStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def create(self, request: ApprovalRequest) -> None:
        self.save(request)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        for item in self._read():
            if item["approval_id"] == approval_id:
                return ApprovalRequest.from_dict(item)
        return None

    def save(self, request: ApprovalRequest) -> None:
        items = [item for item in self._read() if item["approval_id"] != request.approval_id]
        items.append(request.to_dict())
        self._path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def _read(self) -> list[dict[str, str]]:
        if not self._path.exists():
            return []
        return json.loads(self._path.read_text(encoding="utf-8"))
