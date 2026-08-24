import asyncio

from agent_permission.approval import ApprovalRequest, ApprovalStatus
from agent_permission.stores import LocalFileApprovalStore


def test_approval_can_be_approved_once():
    request = ApprovalRequest("execute:game:save", "agent-1", "save")

    request.approve()

    assert request.status is ApprovalStatus.APPROVED

    try:
        request.reject()
    except ValueError:
        pass
    else:
        raise AssertionError("A terminal approval must not transition again")


def test_local_file_store_round_trip(tmp_path):
    store = LocalFileApprovalStore(tmp_path / "data_execute_game_save.json")
    request = ApprovalRequest("execute:game:save", "agent-1", "save")

    store.create(request)
    loaded = store.get(request.approval_id)

    assert loaded is not None
    assert loaded.permission == "execute:game:save"
    assert loaded.status is ApprovalStatus.PENDING


def test_async_permission_guard_checks_before_function_body():
    from agent_permission import permission_guard
    from agent_permission.errors import PermissionDenied

    executed = False

    @permission_guard
    async def save():
        nonlocal executed
        executed = True

    async def run() -> None:
        try:
            await save()
        except PermissionDenied:
            pass
        else:
            raise AssertionError("The unapproved function should be denied")

    asyncio.run(run())
    assert executed is False
