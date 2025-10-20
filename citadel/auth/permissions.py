from dataclasses import dataclass
from enum import IntEnum
import logging

from citadel.transport.packets import ToUser

log = logging.getLogger(__name__)


class PermissionLevel(IntEnum):
    UNVERIFIED = 0
    TWIT = 1
    USER = 2
    AIDE = 3
    SYSOP = 4


@dataclass
class PermissionInfo:
    level: PermissionLevel
    description: str


# Map actions to the minimum permission level required
# if you create a new command, add it here
ACTION_REQUIREMENTS = {
    "go_next_unread": PermissionInfo(level=PermissionLevel.TWIT,
                                     description="navigate to rooms with new messages"),
    "enter_message": PermissionInfo(level=PermissionLevel.USER,
                                    description="post messages"),
    "read_messages": PermissionInfo(level=PermissionLevel.TWIT,
                                    description="read messages"),
    "read_new_messages": PermissionInfo(level=PermissionLevel.TWIT,
                                        description="read new messages"),
    "forward_read": PermissionInfo(level=PermissionLevel.TWIT,
                                        description="read messages forware"),
    "reverse_read": PermissionInfo(level=PermissionLevel.TWIT,
                                        description="read messages reverse"),
    "known_rooms": PermissionInfo(level=PermissionLevel.USER,
                                  description="known rooms"),
    "ignore_room": PermissionInfo(level=PermissionLevel.USER,
                                  description="ignore rooms"),
    "quit": PermissionInfo(level=PermissionLevel.UNVERIFIED,
                           description="quit"),
    "scan_messages": PermissionInfo(level=PermissionLevel.TWIT,
                                    description="scan messages"),
    "change_room": PermissionInfo(level=PermissionLevel.TWIT,
                                  description="navigate to rooms"),
    "help": PermissionInfo(level=PermissionLevel.UNVERIFIED,
                           description="request help"),
    "mail": PermissionInfo(level=PermissionLevel.USER, description="go to the Mail room"),
    "who": PermissionInfo(level=PermissionLevel.USER, description="get a list of active users"),
    "delete_message": PermissionInfo(level=PermissionLevel.USER,
                                     description="delete messages"),
    "block_user": PermissionInfo(level=PermissionLevel.TWIT,
                                 description="block users"),
    "validate_users": PermissionInfo(level=PermissionLevel.AIDE,
                                     description="validate users"),
    "create_room": PermissionInfo(level=PermissionLevel.AIDE,
                                  description="create rooms"),
    "edit_room": PermissionInfo(level=PermissionLevel.AIDE,
                                description="edit rooms"),
    "edit_user": PermissionInfo(level=PermissionLevel.SYSOP,
                                description="edit users"),
    "fast_forward": PermissionInfo(level=PermissionLevel.USER,
                                   description="fast-forward messages"),
}


def is_allowed(action: str, user, room=None) -> bool:
    permission = ACTION_REQUIREMENTS.get(action)

    if permission is None:  # permission type not set up
        log.debug(
            f"{action} not allowed in {room} because permission not set up")
        return False

    # Special case: twit room is visible to twits but not most users
    from citadel.room.room import SystemRoomIDs
    if action in ["read_messages", "read_new_messages", "enter_message"] \
            and room \
            and room.room_id == SystemRoomIDs.TWIT_ID:
        if user.permission_level in {
            PermissionLevel.TWIT,
            PermissionLevel.AIDE,
            PermissionLevel.SYSOP,
        }:
            log.debug(
                f"{action} is allowed in {room} because user is a twit (or aide/sysop)")
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
            log.debug(
                f"{action} is not allowed in {room} because {user} can't read from this room")
            return False
        if action == "enter_message" and not room.can_user_post(user):
            log.debug(
                f"{action} is not allowed in {room} because {user} can't post in this room")
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
