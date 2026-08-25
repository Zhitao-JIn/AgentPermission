from typing import Mapping

DENIED = 0
ALLOWED = 1
APPROVAL_REQUIRED = 2


def permission_matches(required: str, granted: str) -> bool:
    required_parts = required.split(":")
    granted_parts = granted.split(":")
    if len(required_parts) != len(granted_parts):
        return required == granted
    return all(
        granted_part in {required_part, "*"}
        for required_part, granted_part in zip(required_parts, granted_parts)
    )


def is_allowed(
    required: str,
    roles: set[str] | frozenset[str],
) -> int:
    from . import runtime_roles
    from . import runtime_policies

    permitted = any(
        permission_matches(required, granted)
        for role in roles
        for granted in runtime_roles.get(role, set())
    )
    if not permitted:
        return DENIED
    policy = runtime_policies.get(required, {})
    if isinstance(policy, dict) and policy.get("approval_required", False):
        return APPROVAL_REQUIRED
    return ALLOWED
