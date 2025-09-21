# citadel/auth/checker.py

from citadel.auth.permissions import PermissionLevel
from citadel.commands.responses import ErrorResponse

# Map actions to the minimum permission level required
ACTION_REQUIREMENTS = {
    "read": PermissionLevel.UNVERIFIED,
    "quit": PermissionLevel.UNVERIFIED,
    "post": PermissionLevel.USER,
    "delete": PermissionLevel.AIDE,
    "moderate": PermissionLevel.AIDE,
    "admin": PermissionLevel.SYSOP,
}

def is_allowed(action: str, user, room=None) -> bool:
    required = ACTION_REQUIREMENTS.get(action)
    if required is None: # permission type not set up
        return False
    if user.permission_level < required:
        return False
    if room: # extend this if there are other room-specific perms
        if action == "read" and not room.can_user_read(user):
            return False
        if action == "post" and not room.can_user_post(user):
            return False
    return True

def permission_denied(action: str, user, room=None):
    return ErrorResponse(
        code="permission_denied",
        text=f"You do not have permission to {action} in {room.name if room else 'this context'}."
    )

