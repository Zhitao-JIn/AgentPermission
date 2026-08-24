from typing import Mapping

_role_permissions: dict[str, set[str]] = {}


def configure_role_permissions(roles: Mapping[str, set[str] | list[str]]) -> None:
    global _role_permissions
    _role_permissions = {str(role): set(values) for role, values in roles.items()}


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
) -> bool:
    return any(
        permission_matches(required, granted)
        for role in roles
        for granted in _role_permissions.get(role, set())
    )
