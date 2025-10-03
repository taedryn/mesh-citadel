# citadel/auth/checker.py

import logging

from citadel.auth.permissions import PermissionLevel, ACTION_REQUIREMENTS
from citadel.transport.packets import ToUser
from citadel.room.room import SystemRoomIDs

log = logging.getLogger(__name__)

def is_allowed(action: str, user, room=None) -> bool:
    permission = ACTION_REQUIREMENTS.get(action)

    if permission is None:  # permission type not set up
        log.debug(f"{action} not allowed in {room} because permission not set up")
        return False

    # Special case: twit room is visible to twits but not most users
    if action in ["read_messages", "read_new_messages", "enter_message"] \
            and room \
            and room.room_id == SystemRoomIDs.TWIT_ID:
        if user.permission_level in {
            PermissionLevel.TWIT,
            PermissionLevel.AIDE,
            PermissionLevel.SYSOP,
            }:
            log.debug(f"{action} is allowed in {room} because user is a twit (or aide/sysop)")
            return True

    min_permission = permission.level
    if user.permission_level < min_permission:
        log.debug(f"{action} not allowed in {room} because user is a twit")
        return False

    if room:  # extend this if there are other room-specific perms
        read_actions = [
            "read_messages",
            "read_new_messages",
            "scan_messages",
            "ignore_room",
        ]
        if action in read_actions and not room.can_user_read(user):
            log.debug(f"{action} is not allowed in {room} because {user} can't read from this room")
            return False
        if action == "enter_message" and not room.can_user_post(user):
            log.debug(f"{action} is not allowed in {room} because {user} can't post in this room")
            return False

    log.debug(f"{action} is allowed in {room}")
    return True


def permission_denied(session_id, action: str, user, room=None):
    requirement = ACTION_REQUIREMENTS.get(action)
    if requirement:
        do_action = requirement.description
    else:
        do_action = action
    return ToUser(
        session_id=session_id,
        text=f"You do not have permission to {do_action} in {room.name if room else 'this context'}.",
        is_error=True,
        error_code="permission_denied"
    )
