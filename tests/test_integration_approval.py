import agent_permission
import json
import pytest
from pathlib import Path

from agent_permission import PermissionContext, set_current_context
from agent_permission.approval import ApprovalStatus
from agent_permission.errors import ApprovalRejected
from agent_permission.rbac import configure_role_permissions
from agent_permission.stores import LocalFileApprovalStore


@pytest.fixture
def protected_save(monkeypatch):
    configure_role_permissions({"trusted-agent": {"execute:game:save"}})
    set_current_context(PermissionContext("pokemon-agent", frozenset({"trusted-agent"})))
    monkeypatch.setitem(
        agent_permission.runtime_policies,
        "execute:game:save",
        {"risk": "HIGH", "approval_required": True},
    )
    approval_path = Path(agent_permission.__file__).resolve().parent.parent / "log" / "data_execute_game_save.json"
    if approval_path.exists():
        approval_path.unlink()
    store = agent_permission.get_approval_store("execute:game:save")

    executed = []

    @agent_permission.require_permission("execute:game:save")
    def save(state: str) -> str:
        executed.append(state)
        return "saved"

    try:
        yield save, executed, store, approval_path
    finally:
        if approval_path.exists():
            approval_path.unlink()


def test_rejected_approval_blocks_function(monkeypatch, protected_save):
    save, executed, store, approval_path = protected_save
    monkeypatch.setattr("builtins.input", lambda: "reject")

    with pytest.raises(ApprovalRejected):
        save("state-1")

    assert executed == []
    assert approval_path.exists()
    assert isinstance(json.loads(approval_path.read_text(encoding="utf-8")), list)
    requests = store._read()
    assert len(requests) == 1
    assert requests[0]["status"] == ApprovalStatus.REJECTED.value


def test_approved_request_allows_function(monkeypatch, protected_save):
    save, executed, store, approval_path = protected_save
    monkeypatch.setattr("builtins.input", lambda: "approve")

    assert save("state-2") == "saved"

    assert executed == ["state-2"]
    assert approval_path.exists()
    assert isinstance(json.loads(approval_path.read_text(encoding="utf-8")), list)
    requests = store._read()
    assert len(requests) == 1
    assert requests[0]["status"] == ApprovalStatus.APPROVED.value
