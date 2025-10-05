# bbs/commands/builtins.py

import logging

from citadel.commands.base import BaseCommand, CommandCategory
from citadel.commands.registry import register_command
from citadel.auth.permissions import PermissionLevel
from citadel.commands.responses import MessageResponse
from citadel.transport.packets import ToUser
from citadel.auth.permissions import is_allowed
from citadel.room.room import Room, SystemRoomIDs
from citadel.user.user import User
from citadel.workflows.base import WorkflowContext

log = logging.getLogger(__name__)

# -------------------
# Core user commands
# -------------------

# command categories:
# * common
# * uncommon
# * unusual
# * admin


@register_command
class GoNextUnreadCommand(BaseCommand):
    code = "G"
    name = "go_next_unread"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Goto next unread room"
    help_text = "Go to the next room with unread messages. This skips over rooms you've already read completely."
    arg_schema = {}

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        new_room = await room.go_to_next_room(user, with_unread=True)
        await new_room.load()
        context.session_mgr.set_current_room(
            context.session_id, new_room.room_id)

        # Check if we wrapped to Lobby due to no unread rooms
        if new_room.room_id == SystemRoomIDs.LOBBY_ID and room.room_id != SystemRoomIDs.LOBBY_ID:
            # Check if there are any unread messages in the system
            lobby_has_unread = await new_room.has_unread_messages(user)
            if lobby_has_unread:
                return ToUser(
                    session_id=context.session_id,
                    text=f"You are now in room '{new_room.name}'. New messages are available in other rooms."
                )
            else:
                return ToUser(
                    session_id=context.session_id,
                    text=f"You are now in room '{new_room.name}'. No rooms with unread messages found."
                )

        return ToUser(
            session_id=context.session_id,
            text=f"You are now in room '{new_room.name}'."
        )


@register_command
class EnterMessageCommand(BaseCommand):
    code = "E"
    name = "enter_message"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Enter message"
    help_text = "Compose and post a message to the current room"
    arg_schema = {
        "content": {"required": True, "type": "str", "help": "The body of the message"},
        "recipient": {"required": False, "type": "str", "help": "Recipient username (required in Mail)"},
    }

    def validate(self, context=None):
        super().validate(context)
        if context and context.get("room") == "Mail" and "recipient" not in self.args:
            raise ValueError("Recipient required in Mail room")

    async def run(self, context):
        from citadel.workflows.registry import get as get_workflow
        from citadel.workflows.base import WorkflowState

        state = context.session_mgr.get_session_state(context.session_id)
        if not state:
            return ToUser(
                session_id=context.session_id,
                text="Session not found",
                is_error=True,
                error_code="no_session"
            )

        wf_state = WorkflowState(kind="enter_message", step=1, data={})
        # Start the workflow
        context.session_mgr.set_workflow(context.session_id, wf_state)
        wf_context = WorkflowContext(
            session_id=context.session_id,
            db=context.db,
            config=context.config,
            session_mgr=context.session_mgr,
            wf_state=wf_state
        )

        workflow = get_workflow("enter_message")
        return await workflow.start(wf_context)


@register_command
class ReadMessagesCommand(BaseCommand):
    code = "R"
    name = "read_messages"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Read messages"
    help_text = "Read messages in the current room. Provide ID to read a specific message."
    arg_schema = {
        "message_id": {"required": False, "type": "str", "help": "ID of the message to read"}
    }


@register_command
class ReadNewMessagesCommand(BaseCommand):
    code = "N"
    name = "read_new_messages"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Read new messages"
    help_text = "Read new messages since last visit. Starts with the oldest mesasage you haven't read yet in this room."
    arg_schema = {}

    async def run(self, context):
        from citadel.commands.responses import MessageResponse

        state = context.session_mgr.get_session_state(context.session_id)
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        msg_ids = await room.get_unread_message_ids(state.username)
        if not msg_ids:
            return ToUser(
                session_id=context.session_id,
                text="No unread messages."
            )

        to_user_list = []
        for msg_id in msg_ids:
            msg = await context.msg_mgr.get_message(msg_id)
            sender = User(context.db, msg["sender"])
            await sender.load()
            message_response = MessageResponse(
                id=msg["id"],
                sender=msg["sender"],
                display_name=sender.display_name,
                timestamp=msg["timestamp"],
                room=room.name,
                content=msg["content"],
                blocked=msg["blocked"]
            )
            to_user_list.append(ToUser(
                session_id=context.session_id,
                text="",  # Message content is in the message field
                message=message_response
            ))
        return to_user_list


@register_command
class KnownRoomsCommand(BaseCommand):
    code = "K"
    name = "known_rooms"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Known rooms"
    help_text = "List all rooms known to you."
    arg_schema = {}


@register_command
class IgnoreRoomCommand(BaseCommand):
    code = "I"
    name = "ignore_room"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Ignore room"
    help_text = "Ignore or unignore the current room"
    arg_schema = {}


@register_command
class QuitCommand(BaseCommand):
    code = "Q"
    name = "quit"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Quit"
    help_text = "Quit or log off"
    arg_schema = {}

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        context.session_mgr.expire_session(context.session_id)
        log.info(f"User '{state.username}' logged out via quit command")
        return ToUser(
            session_id=context.session_id,
            text="Goodbye!"
        )


@register_command
class CancelCommand(BaseCommand):
    code = "cancel"  # Use full word since this is a special case
    name = "cancel"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Cancel workflow"
    help_text = "Cancel the current workflow and return to normal command mode"
    arg_schema = {}

    async def run(self, context):
        from citadel.workflows import registry as workflow_registry

        # Check if user is in a workflow
        workflow_state = context.session_mgr.get_workflow(context.session_id)
        if not workflow_state:
            return ToUser(
                session_id=context.session_id,
                text="No active workflow to cancel.",
                is_error=True,
                error_code="no_workflow"
            )

        # Call cleanup on the workflow if it has one
        handler = workflow_registry.get(workflow_state.kind)
        if handler and hasattr(handler, 'cleanup'):
            try:
                await handler.cleanup(context)
            except Exception as e:
                log.warning(f"Error during workflow cleanup for {workflow_state.kind}: {e}")

        # Clear the workflow
        context.session_mgr.clear_workflow(context.session_id)

        return ToUser(
            session_id=context.session_id,
            text=f"Cancelled {workflow_state.kind} workflow."
        )


@register_command
class ScanMessagesCommand(BaseCommand):
    code = "S"
    name = "scan_messages"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Scan messages"
    help_text = "Show message summaries in the current room."
    arg_schema = {}


@register_command
class ChangeRoomCommand(BaseCommand):
    code = "C"
    name = "change_room"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Change room"
    help_text = "Change to a room by name or number. Specify the room name or ID after the command letter."
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Name or number of the room to enter"}
    }

    async def run(self, context):

        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        current_room = Room(context.db, context.config, state.current_room)
        await current_room.load()
        next_room = await current_room.go_to_room(self.args["room"])
        log.debug(f'preparing to go to room {self.args["room"]}')
        if not next_room:
            return ToUser(
                session_id=context.session_id,
                text=f"Room {self.args['room']} not found.",
                is_error=True,
                error_code="no_next_room"
            )
        context.session_mgr.set_current_room(
            context.session_id, next_room.room_id)
        return ToUser(
            session_id=context.session_id,
            text=f"You are now in room '{next_room.name}'."
        )


@register_command
class HelpCommand(BaseCommand):
    code = "H"
    name = "help"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Help"
    help_text = "Display a help menu of available commands"
    arg_schema = {
        "command": {"required": False, "type": "str", "help": "Optional command code for detailed help"}
    }

    async def run(self, context):
        from citadel.commands.registry import registry

        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()

        # Get current room for permission checking
        room = None
        if state.current_room:
            room = Room(context.db, context.config, state.current_room)
            await room.load()

        # If specific command requested, show detailed help
        if "command" in self.args and self.args["command"]:
            return await self._show_command_help(context.session_id, self.args["command"], user, room)

        # Build dynamic menu by category
        all_commands = registry.available()
        menu_text = self._build_category_menu(
            all_commands, user, room, CommandCategory.COMMON)

        return ToUser(
            session_id=context.session_id,
            text=menu_text
        )

    def _build_category_menu(self, all_commands, user, room, category):
        """Build menu for a specific category."""
        # Filter to implemented commands user can access in this category
        available_commands = []
        for cmd_class in all_commands.values():
            if (cmd_class.is_implemented() and
                cmd_class.category == category and
                    is_allowed(cmd_class.name, user, room)):
                available_commands.append(cmd_class)

        # Sort by command code for consistent ordering
        available_commands.sort(key=lambda c: c.code)

        # Build compact menu text
        menu_lines = []
        for cmd in available_commands:
            menu_lines.append(f"{cmd.code}-{cmd.short_text}")

        if not menu_lines:
            return "No available commands in this category."

        # Add category header and join lines
        category_name = category.name.title()
        header = f"{category_name} Commands:"
        return header + "\n" + "  ".join(menu_lines)

    async def _show_command_help(self, session_id, command_code, user, room):
        """Show detailed help for a specific command."""
        from citadel.commands.registry import registry

        cmd_class = registry.get(command_code.upper())
        if not cmd_class:
            return ToUser(
                session_id=session_id,
                text=f"Unknown command: {command_code}",
                is_error=True,
                error_code="unknown_command"
            )

        if not is_allowed(cmd_class.name, user, room):
            return ToUser(
                session_id=session_id,
                text=f"You don't have permission to use command {command_code}",
                is_error=True,
                error_code="permission_denied"
            )

        if not cmd_class.is_implemented():
            return ToUser(
                session_id=session_id,
                text=f"{cmd_class.code} - {cmd_class.short_text}\n(Not yet implemented)"
            )

        # Build detailed help text
        help_text = f"{cmd_class.code} - {cmd_class.short_text}\n{cmd_class.help_text}"

        if cmd_class.arg_schema:
            help_text += "\n\nArguments:"
            for arg, spec in cmd_class.arg_schema.items():
                required = " (required)" if spec.get(
                    "required") else " (optional)"
                help_text += f"\n  {arg}: {spec.get('help', 'No description')}{required}"

        return ToUser(
            session_id=session_id,
            text=help_text
        )


# this is a duplicate of the HelpCommand, but with a different command letter
@register_command
class MenuCommand(BaseCommand):
    code = "?"
    name = "help"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Help"
    help_text = "Display a help menu of available commands"
    arg_schema = {
        "command": {"required": False, "type": "str", "help": "Optional command code for detailed help"}
    }

    # Use the same implementation as HelpCommand
    run = HelpCommand.run
    _build_category_menu = HelpCommand._build_category_menu
    _show_command_help = HelpCommand._show_command_help


@register_command
class MailCommand(BaseCommand):
    code = "M"
    name = "mail"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Go to Mail"
    help_text = "Go directly to the Mail room to send/receive private messages."
    arg_schema = {}


@register_command
class WhoCommand(BaseCommand):
    code = "W"
    name = "who"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Who's online"
    help_text = "List active users currently online."
    arg_schema = {}


@register_command
class DeleteMessageCommand(BaseCommand):
    code = "D"
    name = "delete_message"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Delete message"
    help_text = "Delete either the most recently displayed message, or a message ID specified after the command letter. Only Aides and Sysops can delete others' messages."
    arg_schema = {
        "message_id": {"required": True, "type": "str", "help": "ID of the message to delete"}
    }


@register_command
class BlockUserCommand(BaseCommand):
    code = "B"
    name = "block_user"
    category = CommandCategory.UNUSUAL
    permission_level = PermissionLevel.USER
    short_text = "(Un)Block user"
    help_text = "Block or unblock another user. Specify username or display name after the command letter. Prevents you seeing their messages/mails (they can still see yours)."
    arg_schema = {
        "target_user": {"required": True, "type": "str", "help": "Username of the user to block/unblock"}
    }


@register_command
class ValidateUsersCommand(BaseCommand):
    code = "V"
    name = "validate_users"
    category = CommandCategory.AIDE
    permission_level = PermissionLevel.AIDE
    short_text = "Validate users"
    help_text = "Enter the user validation workflow to approve new users."
    arg_schema = {}  # no args; interactive workflow


# -------------------
# Dot commands (administrative / less common)
# -------------------

@register_command
class CreateRoomCommand(BaseCommand):
    code = ".C"
    name = "create_room"
    category = CommandCategory.UNUSUAL
    permission_level = PermissionLevel.USER
    short_text = "Create room"
    help_text = "Create a new room. Sends you into an interactive workflow to create the new room."
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Name of the new room"},
        "description": {"required": False, "type": "str", "help": "Optional description of the room"}
    }


@register_command
class EditRoomCommand(BaseCommand):
    code = ".ER"
    name = "edit_room"
    category = CommandCategory.SYSOP
    permission_level = PermissionLevel.SYSOP
    short_text = "Edit room"
    help_text = "Edit a room's characteristics"
    arg_schema = {
        "room": {"required": True, "type": "str", "help": "Room to edit"},
        "attributes": {"required": True, "type": "dict", "help": "Room attributes to update"}
    }


@register_command
class EditUserCommand(BaseCommand):
    code = ".EU"
    name = "edit_user"
    category = CommandCategory.SYSOP
    permission_level = PermissionLevel.SYSOP
    short_text = "Edit user"
    help_text = "Edit a user's characteristics"
    arg_schema = {
        "target_user": {"required": True, "type": "str", "help": "Username of the user to edit"},
        "attributes": {"required": True, "type": "dict", "help": "User attributes to update"}
    }


@register_command
class FastForwardCommand(BaseCommand):
    code = ".FF"
    name = "fast_forward"
    category = CommandCategory.UNUSUAL
    permission_level = PermissionLevel.USER
    short_text = "Fast-forward"
    help_text = "Fast-forward to the latest message in the current room, skipping over unread messages. This resets your last-read pointer to the latest message."
    arg_schema = {}
