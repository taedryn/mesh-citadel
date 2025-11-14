# bbs/commands/builtins.py

from datetime import datetime, UTC
import logging

from citadel.commands.base import BaseCommand, CommandCategory
from citadel.commands.registry import register_command
from citadel.auth.permissions import PermissionLevel
from citadel.commands.responses import MessageResponse
from citadel.transport.packets import ToUser
from citadel.auth.permissions import is_allowed
from citadel.room.room import Room, SystemRoomIDs, RoomNotFoundError
from citadel.user.user import User
from citadel.workflows.base import WorkflowContext, WorkflowState

log = logging.getLogger(__name__)

# -------------------
# Core user commands
# -------------------

# command categories:
# * common
# * uncommon
# * unusual
# * admin


async def scan_messages(context, msg_ids):
    """given a set of message IDs, return a list of ToUser objects,
    each containing one of the indicated messages"""
    state = context.session_mgr.get_session_state(context.session_id)
    user = User(context.db, state.username)
    await user.load()
    room = Room(context.db, context.config, state.current_room)
    await room.load()
    if not msg_ids:
        return ToUser(
            session_id=context.session_id,
            text="No messages"
        )

    msgs = []
    for msg_id in msg_ids:
        msg = await context.msg_mgr.get_message_summary(
            msg_id,
            recipient_user=user,
            msg_len=50
        )
        # Message not authorized for this user (privacy check failed)
        if not msg:
            continue

        msgs.append(msg)

    return ToUser(
        session_id=context.session_id,
        text='\n'.join(msgs)
    )


async def read_messages(context, msg_ids):
    """given a set of message IDs, return a list of ToUser objects,
    each containing one of the indicated messages"""
    state = context.session_mgr.get_session_state(context.session_id)
    user = User(context.db, state.username)
    await user.load()
    room = Room(context.db, context.config, state.current_room)
    await room.load()
    if not msg_ids:
        return ToUser(
            session_id=context.session_id,
            text="No unread messages."
        )

    to_user_list = []
    for msg_id in msg_ids:
        msg = await context.msg_mgr.get_message(msg_id, recipient_user=user)
        # Message not authorized for this user (privacy check failed)
        if not msg:
            continue
        sender = User(context.db, msg["sender"])
        await sender.load()
        message_response = MessageResponse(
            id=msg["id"],
            sender=msg["sender"],
            display_name=sender.display_name,
            timestamp=msg["timestamp"],
            room=room.name,
            content=msg["content"],
            blocked=msg["blocked"],
            recipient=msg["recipient"]
        )
        log.debug(f"Adding message to read list: {msg['id']}")
        to_user_list.append(ToUser(
            session_id=context.session_id,
            text="",  # Message content is in the message field
            message=message_response
        ))

    # Mark all displayed messages as read by advancing to latest
    await room.skip_to_latest(user)
    log.debug(f"Returning list of {len(to_user_list)} messages")
    return to_user_list


@register_command
class GoNextUnreadCommand(BaseCommand):
    code = "G"
    name = "go_next_unread"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Goto next unread room"
    help_text = "Go to the next room with unread messages. This skips over rooms you've already read completely."

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

    def validate(self, context=None):
        super().validate(context)
        if context and context.get("room") == "Mail" and not self.args:
            raise ValueError("Recipient required in Mail room")

    async def run(self, context):
        from citadel.workflows.registry import get as get_workflow

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
class ReverseReadCommand(BaseCommand):
    code = "R"
    name = "reverse_read"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Reverse read messages"
    help_text = "Read messages in the current room, starting with the most recent and moving backwards."

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        msg_ids = await room.get_user_message_ids(user, reverse=True)
        log.debug(f"Found reverse message ids: {msg_ids}")
        return await read_messages(context, msg_ids)


@register_command
class ForwardReadCommand(BaseCommand):
    code = "F"
    name = "forward_read"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Forward read messages"
    help_text = "Read messages in the current room, starting with the oldest and moving forward."

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        msg_ids = await room.get_user_message_ids(user)
        log.debug(f"Found forward message ids: {msg_ids}")
        return await read_messages(context, msg_ids)


@register_command
class ReadNewMessagesCommand(BaseCommand):
    code = "N"
    name = "read_new_messages"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Read new messages"
    help_text = "Read new messages since last visit. Starts with the oldest mesasage you haven't read yet in this room."

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        msg_ids = await room.get_unread_message_ids(state.username)
        log.debug(f"Found new message ids: {msg_ids}")
        return await read_messages(context, msg_ids)


@register_command
class KnownRoomsCommand(BaseCommand):
    code = "K"
    name = "known_rooms"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Known rooms"
    help_text = "List all rooms known to you."

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()

        current_room_id = state.current_room

        rooms = await Room.get_all_visible_rooms(
            context.db, context.config, user
        )

        if not rooms:
            return ToUser(
                session_id=context.session_id,
                text="No rooms available to you."
            )

        lines = []
        for room in rooms:
            pre_marker = "-"
            post_marker = ""

            if room.room_id == current_room_id:
                post_marker = "<--"

            unread = await room.has_unread_messages(user)
            if unread:
                pre_marker = "*"

            line = f"{pre_marker} {room.name} {post_marker}"
            lines.append(line)

        room_list = "\n".join(lines)
        return ToUser(
            session_id=context.session_id,
            text=f"Known rooms:\n\n{room_list}"
        )


@register_command
class IgnoreRoomCommand(BaseCommand):
    code = "I"
    name = "ignore_room"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Ignore room"
    help_text = "Ignore or unignore the current room"


@register_command
class QuitCommand(BaseCommand):
    code = "Q"
    name = "quit"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Quit"
    help_text = "Quit or log off"

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        old_username = state.username if state else "unknown"

        log.info(f"User '{old_username}' logged out via quit command")

        # Start login workflow on existing session (resets to anonymous state)
        session_id, login_prompt = await context.session_mgr.start_login_workflow(
            context.config, context.db, context.session_id
        )

        if login_prompt:
            login_prompt.text = "Goodbye!\n\n" + login_prompt.text
            return login_prompt
        else:
            # Fallback if login workflow unavailable
            return ToUser(
                session_id=state.session_id,
                text="Goodbye! Please reconnect to log in again."
            )


@register_command
class StopCommand(BaseCommand):
    code = "STOP"  # Use full word since this is a special case
    name = "stop"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Stop messages"
    help_text = "Stop sending messages as soon as possible"

    async def run(self, context):
        num = await context.session_mgr.clear_msg_queue(context.session_id)
        if num == 1:
            mword = "message"
        else:
            mword = "messages"
        return ToUser(
            session_id=context.session_id,
            text=f"Stopped {num} pending {mword}"
        )


@register_command
class CancelCommand(BaseCommand):
    code = "CANCEL"  # Use full word since this is a special case
    name = "cancel"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Cancel workflow"
    help_text = "Cancel the current workflow and return to normal command mode"

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
                log.warning(
                    f"Error during workflow cleanup for {workflow_state.kind}: {e}")

        # Clear the workflow
        context.session_mgr.clear_workflow(context.session_id)

        # If the user is not logged in (e.g., cancelling registration/login), start login workflow
        session_state = context.session_mgr.get_session_state(
            context.session_id)
        if not session_state or not context.session_mgr.is_logged_in(context.session_id):
            session_id, login_prompt = await context.session_mgr.start_login_workflow(
                context.config, context.db, context.session_id
            )
            if login_prompt:
                login_prompt.text = f"Cancelled {workflow_state.kind} workflow.\n\n" + \
                    login_prompt.text
                return login_prompt

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

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        room = Room(context.db, context.config, state.current_room)
        await room.load()
        msg_ids = await room.get_user_message_ids(user)
        return await scan_messages(context, msg_ids)


@register_command
class ChangeRoomCommand(BaseCommand):
    code = "C"
    name = "change_room"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Change room"
    help_text = "Change to a room by name or number. Specify the room name or ID after the command letter."
    # add an args attribute for any command that takes an argument
    args = ""

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        current_room = Room(context.db, context.config, state.current_room)
        await current_room.load()
        try:
            next_room = await current_room.go_to_room(self.args)
            await next_room.load()
            log.debug(f'preparing to go to room {self.args}')
        except RoomNotFoundError:
            return ToUser(
                session_id=context.session_id,
                text=f"Room {self.args} not found.",
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
        menus = []
        for category in CommandCategory:
            text = self._build_category_menu(
                all_commands, user, room, category)
            if 'No available' in text:
                continue
            menus.append(text)

        return ToUser(
            session_id=context.session_id,
            text="\n\n".join(menus)
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

    async def run(self, context):

        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        try:
            mail_room = Room(context.db, context.config, SystemRoomIDs.MAIL_ID)
            await mail_room.load()
            log.debug(f'preparing to go to room {self.args}')
        except RoomNotFoundError:
            return ToUser(
                session_id=context.session_id,
                text=f"Room {self.args} not found.",
                is_error=True,
                error_code="no_next_room"
            )
        context.session_mgr.set_current_room(
            context.session_id, mail_room.room_id)
        return ToUser(
            session_id=context.session_id,
            text=f"You are now in room '{mail_room.name}'."
        )


@register_command
class WhoCommand(BaseCommand):
    code = "W"
    name = "who"
    category = CommandCategory.UNCOMMON
    permission_level = PermissionLevel.USER
    short_text = "Who's online"
    help_text = "List active users currently online."

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()

        # Check if user is privileged (aide or sysop)
        is_privileged = user.permission_level.value >= PermissionLevel.AIDE.value

        # Get all active sessions
        online_users = []
        now = datetime.now(UTC)

        with context.session_mgr.lock:
            for session_id, (session_state, last_active) in context.session_mgr.sessions.items():
                if not session_state.logged_in or not session_state.username:
                    continue

                # Load user to check public status
                online_user = User(context.db, session_state.username)
                await online_user.load()

                # TODO: Add has_posted_publicly field to users table and User model
                # For now, show all users (will be restricted once field is added)
                # For non-privileged users, only show users who have posted publicly
                # if not is_privileged and not online_user.has_posted_publicly:
                #     continue

                # Calculate activity status
                seconds_idle = (now - last_active).total_seconds()

                if is_privileged:
                    # Show granular timing for privileged users
                    if seconds_idle < 60:
                        activity_str = f"active ({int(seconds_idle)}s)"
                    elif seconds_idle < 3600:  # Less than 1 hour
                        activity_str = f"idle ({int(seconds_idle // 60)}m)"
                    else:  # 1+ hours
                        activity_str = f"idle ({int(seconds_idle // 3600)}h)"

                    # Include public/private status for privileged users
                    # TODO: Replace with actual has_posted_publicly check
                    visibility = "public"  # Placeholder until has_posted_publicly is implemented
                    user_info = f"{session_state.username} ({activity_str}) [{visibility}]"
                else:
                    # Simple active/idle for regular users
                    activity_str = "active" if seconds_idle < 60 else "idle"
                    user_info = f"{session_state.username} ({activity_str})"

                online_users.append(user_info)

        if not online_users:
            return ToUser(
                session_id=context.session_id,
                text="No users currently online."
            )

        # Sort alphabetically
        online_users.sort()
        user_list = "\n".join(online_users)

        return ToUser(
            session_id=context.session_id,
            text=f"Users currently online:\n{user_list}"
        )


@register_command
class DeleteMessageCommand(BaseCommand):
    code = "D"
    name = "delete_message"
    category = CommandCategory.COMMON
    permission_level = PermissionLevel.USER
    short_text = "Delete message"
    help_text = "Delete a message ID specified after the command letter. Only Aides and Sysops can delete others' messages."
    args = ""

    async def run(self, context):
        state = context.session_mgr.get_session_state(context.session_id)
        user = User(context.db, state.username)
        await user.load()
        permission_level = user.permission_level
        room = Room(context.db, context.config, state.current_room)
        await room.load()

        if not self.args:
            return ToUser(
                session_id=context.session_id,
                text='Message ID number must be specified. No action taken.',
                is_error=True
            )
        msg = await context.msg_mgr.get_message(self.args, user)

        allowed = False
        reason = ''
        if permission_level >= PermissionLevel.AIDE:
            allowed = True
            reason = 'is_aide'
        elif (user.username == msg['sender'] or user.username ==
              msg['recipient']):
            allowed = True
            reason = 'is_author'

        if allowed:
            await room.delete_message(msg['id'])
            log.info(
                f'Message {msg["id"]} deleted from room {room.name} by {user.username} (allowed because {reason})')
            return ToUser(
                session_id=context.session_id,
                text=f"Message {msg['id']} deleted"
            )
        else:
            log.info(
                f'User {user.username} tried to delete message {msg["id"]} in room {room.name}, but was denied (no permission)')
            return ToUser(
                session_id=context.session_id,
                text=f"You don't have permission to delete message {msg['id']}",
                is_error=True
            )


@register_command
class BlockUserCommand(BaseCommand):
    code = "B"
    name = "block_user"
    category = CommandCategory.UNUSUAL
    permission_level = PermissionLevel.USER
    short_text = "(Un)Block user"
    help_text = "Block or unblock another user. Specify username or display name after the command letter. Prevents you seeing their messages/mails (they can still see yours)."


@register_command
class ValidateUsersCommand(BaseCommand):
    code = "V"
    name = "validate_users"
    category = CommandCategory.AIDE
    permission_level = PermissionLevel.AIDE
    short_text = "Validate users"
    help_text = "Enter the user validation workflow to approve new users."

    async def run(self, context):
        # Check if there are any pending validations
        pending_users = await context.db.execute(
            "SELECT username, submitted_at FROM pending_validations ORDER BY submitted_at"
        )

        if not pending_users:
            return ToUser(
                session_id=context.session_id,
                text="No users pending validation."
            )

        # Start validation workflow
        context.session_mgr.set_workflow(
            context.session_id,
            WorkflowState(
                kind="validate_users",
                step=1,
                data={"pending_users": [user[0]
                                        for user in pending_users], "current_index": 0}
            )
        )

        from citadel.workflows import registry as workflow_registry
        handler = workflow_registry.get("validate_users")
        if handler:
            workflow_context = WorkflowContext(
                session_id=context.session_id,
                config=context.config,
                db=context.db,
                session_mgr=context.session_mgr,
                wf_state=context.session_mgr.get_workflow(context.session_id)
            )
            return await handler.start(workflow_context)

        return ToUser(
            session_id=context.session_id,
            text="Validation workflow not available.",
            is_error=True,
            error_code="workflow_unavailable"
        )


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

    async def run(self, context):
        # Start validation workflow
        context.session_mgr.set_workflow(
            context.session_id,
            WorkflowState(
                kind="create_room",
                step=1,
                data={}
            )
        )

        from citadel.workflows import registry as workflow_registry
        handler = workflow_registry.get("create_room")
        if handler:
            workflow_context = WorkflowContext(
                session_id=context.session_id,
                config=context.config,
                db=context.db,
                session_mgr=context.session_mgr,
                wf_state=context.session_mgr.get_workflow(context.session_id)
            )
            return await handler.start(workflow_context)

        return ToUser(
            session_id=context.session_id,
            text="Room creation workflow not available.",
            is_error=True,
            error_code="workflow_unavailable"
        )


@register_command
class EditRoomCommand(BaseCommand):
    code = ".ER"
    name = "edit_room"
    category = CommandCategory.SYSOP
    permission_level = PermissionLevel.SYSOP
    short_text = "Edit room"
    help_text = "Edit a room's characteristics"


@register_command
class EditUserCommand(BaseCommand):
    code = ".EU"
    name = "edit_user"
    category = CommandCategory.SYSOP
    permission_level = PermissionLevel.SYSOP
    short_text = "Edit user"
    help_text = "Edit a user's characteristics"


@register_command
class FastForwardCommand(BaseCommand):
    code = ".FF"
    name = "fast_forward"
    category = CommandCategory.UNUSUAL
    permission_level = PermissionLevel.USER
    short_text = "Fast-forward"
    help_text = "Fast-forward to the latest message in the current room, skipping over unread messages. This resets your last-read pointer to the latest message."
