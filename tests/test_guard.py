import pytest

from agent_permission import permission_guard, require_permission
from agent_permission.errors import PermissionDenied


def test_denied_function_is_not_executed():
    executed = False

    @permission_guard
    def save():
        nonlocal executed
        executed = True

    with pytest.raises(PermissionDenied):
        save()
    assert executed is False


def test_default_context_and_wildcard_permission():
    @require_permission("read:game:inspect")
    def inspect():
        return "ok"

    assert inspect() == "ok"
