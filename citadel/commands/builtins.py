# bbs/commands/builtins.py

from citadel.commands.base import BaseCommand
from citadel.commands.registry import register_command
from citadel.auth.permissions import PermissionLevel

# -------------------
# Core user commands
# -------------------


@register_command
class GoNextUnreadCommand(BaseCommand):
    code = "G"
    name = "go_next_unread"
    permission = PermissionLevel.USER
    help_text = "Go to the next room with unread messages."
    arg_schema = {}


@register_command
class EnterMessageCommand(BaseCommand):
    code = "E"
    name = "enter_message"
    permission = PermissionLevel.USER
    help_text = "Compose and post a message to the current room."
    arg_schema = {
        "content": {"required": True, "type": "str", "help": "The body of the message."},
        "recipient": {"required": False, "type": "str", "help": "Recipient username (required in Mail)."},
    }

    def validate(self, context=None):
        super().validate(context)
        if context and context.get("room") == "Mail" and "recipient" not in self.args:
            raise ValueError("Recipient required in Mail room")


@register_command
class ReadMessagesCommand(BaseCommand):
    code = "R"
    name = "read_messages"
    permission = PermissionLevel.USER
    help_text = "Read messages in the current room. Provide ID to read a specific message."
    arg_schema = {
        "message_id": {"required": False, "type": "str", "help": "ID of the message to read."}
    }


@register_command
class ReadNewMessagesCommand(BaseCommand):
    code = "N"
    name = "read_new_messages"
    permission = PermissionLevel.USER
    help_text = "Read new messages since last visit."
    arg_schema = {}


@register_command
class ListRoomsCommand(BaseCommand):
    code = "L"
    name = "list_rooms"
    permission = PermissionLevel.USER
    help_text = "List available rooms."
    arg_schema = {}


@register_command
class IgnoreRoomCommand(BaseCommand):
    code = "I"
    name = "ignore_room"
    permission = PermissionLevel.USER
    help_text = "Ignore or unignore the current room."
    arg_schema = {}


@register_command
class QuitCommand(BaseCommand):
    code = "Q"
    name = "quit"
    permission = PermissionLevel.USER
    help_text = "Quit or log off."
    arg_schema = {}


@register_command
class ScanMessagesCommand(BaseCommand):
    code = "S"
    name = "scan_messages"
    permission = PermissionLevel.USER
    help_text = "Show message headers or summaries in the current room."
    arg_schema = {}


@register_command
class ChangeRoomCommand(BaseCommand):
    code = "C"
    name = "change_room"
    permission = PermissionLevel.USER
    help_text = "Change to a room by name or number."
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Name or number of the room to enter."}
    }


@register_command
class HelpCommand(BaseCommand):
    code = "H"
    name = "help"
    permission = PermissionLevel.USER
    help_text = "Display help for available commands."
    arg_schema = {
        "command": {"required": False, "type": "str", "help": "Optional command code for detailed help."}
    }


@register_command
class MailCommand(BaseCommand):
    code = "M"
    name = "mail"
    permission = PermissionLevel.USER
    help_text = "Go to the Mail room to send/receive private messages."
    arg_schema = {}


@register_command
class WhoCommand(BaseCommand):
    code = "W"
    name = "who"
    permission = PermissionLevel.USER
    help_text = "List active users currently online."
    arg_schema = {}


@register_command
class DeleteMessageCommand(BaseCommand):
    code = "D"
    name = "delete_message"
    permission = PermissionLevel.USER
    help_text = "Delete a message by ID."
    arg_schema = {
        "message_id": {"required": True, "type": "str", "help": "ID of the message to delete."}
    }


@register_command
class BlockUserCommand(BaseCommand):
    code = "B"
    name = "block_user"
    permission = PermissionLevel.USER
    help_text = "Block or unblock another user."
    arg_schema = {
        "target_user": {"required": True, "type": "str", "help": "Username of the user to block/unblock."}
    }


@register_command
class ValidateUsersCommand(BaseCommand):
    code = "V"
    name = "validate_users"
    permission = PermissionLevel.AIDE
    help_text = "Enter the user validation workflow to approve new users."
    arg_schema = {}  # no args; interactive workflow


# -------------------
# Dot commands (administrative / less common)
# -------------------

@register_command
class CreateRoomCommand(BaseCommand):
    code = ".C"
    name = "create_room"
    permission = PermissionLevel.AIDE
    help_text = "Create a new room."
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Name of the new room."},
        "description": {"required": False, "type": "str", "help": "Optional description of the room."}
    }


@register_command
class EditRoomCommand(BaseCommand):
    code = ".ER"
    name = "edit_room"
    permission = PermissionLevel.SYSOP
    help_text = "Edit a room's characteristics."
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Room to edit."},
        "attributes": {"required": True, "type": "dict", "help": "Room attributes to update."}
    }


@register_command
class EditUserCommand(BaseCommand):
    code = ".EU"
    name = "edit_user"
    permission = PermissionLevel.SYSOP
    help_text = "Edit a user's characteristics."
    arg_schema = {
        "target_user": {"required": True, "type": "str", "help": "Username of the user to edit."},
        "attributes": {"required": True, "type": "dict", "help": "User attributes to update."}
    }


@register_command
class FastForwardCommand(BaseCommand):
    code = ".FF"
    name = "fast_forward"
    permission = PermissionLevel.USER
    help_text = "Fast-forward to the latest message in the current room."
    arg_schema = {}
