# citadel/auth/actions.py

# Map actions to the minimum permission level required
ACTION_REQUIREMENTS = {
    "read": PermissionLevel.UNVERIFIED,
    "post": PermissionLevel.USER,
    "delete": PermissionLevel.AIDE,
    "moderate": PermissionLevel.AIDE,
    "admin": PermissionLevel.SYSOP,
}

