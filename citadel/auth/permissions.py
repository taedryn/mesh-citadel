from dataclasses import dataclass
from enum import IntEnum


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
    "list_rooms": PermissionInfo(level=PermissionLevel.USER,
                                 description="list rooms"),
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
