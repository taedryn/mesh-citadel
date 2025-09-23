# citadel/command/processor.py

import logging
from citadel.auth.checker import is_allowed, permission_denied
from citadel.commands.responses import MessageResponse, CommandResponse, ErrorResponse
from citadel.session.manager import SessionManager
from citadel.user.user import User
from citadel.room.room import Room
from citadel.message.manager import MessageManager
from citadel.workflows import registry as workflow_registry

log = logging.getLogger(__name__)


class CommandProcessor:
    def __init__(self, config, db, session_mgr: SessionManager):
        self.config = config
        self.db = db
        self.sessions = session_mgr

        # Normal command dispatch table
        self.dispatch = {
            "quit": self._handle_quit,
            "go_next_unread": self._handle_go_next_unread,
            "change_room": self._handle_change_room,
            "enter_message": self._handle_enter_message,
            "read_new_messages": self._handle_read_new_messages,
            # add more commands here
        }

    async def process(self, session_id: str, command) -> CommandResponse | MessageResponse:
        # 1. Validate session
        state = self.sessions.validate_session(session_id)
        if not state:
            return ErrorResponse(code="invalid_session", text="Session expired or invalid.")
        self.sessions.touch_session(session_id)

        # 2. Workflow check
        wf = self.sessions.get_workflow(session_id)
        if wf:
            handler = workflow_registry.get(wf.kind)
            if not handler:
                return ErrorResponse(code="unknown_workflow", text=f"Unknown workflow: {wf.kind}")
            return await handler.handle(self, session_id, state, command, wf)

        # Permission check
        user = User(self.db, state.username)
        await user.load()
        room = None
        if state.current_room:
            room = Room(self.db, self.config, state.current_room)
            await room.load()

        if not is_allowed(command.name, user, room):
            print('processor is denying this one')
            return permission_denied(command.name, user, room)

        # 3. Normal dispatch
        handler = self.dispatch.get(command.name)
        if not handler:
            return ErrorResponse(code="unknown_command", text=f"Unknown command: {command.name}")

        try:
            return await handler(session_id, state, command)
        except Exception as e:
            log.exception("Command failed")
            return ErrorResponse(code="internal_error", text=str(e))

    # ------------------------------------------------------------
    # Simple, auth-free handlers
    # ------------------------------------------------------------
    async def _handle_quit(self, session_id, state, command):
        self.sessions.expire_session(session_id)
        return CommandResponse(success=True, code="quit", text="Goodbye!")

    # ------------------------------------------------------------
    # External handlers
    # ------------------------------------------------------------
    async def _handle_go_next_unread(self, session_id, state, command):
        user = User(self.db, state.username)
        await user.load()
        room = Room(self.db, self.config, command.args[0])
        await room.load()
        new_room = room.go_to_next_room(user, with_unread=True)
        await new_room.load()
        self.sessions.set_current_room(session_id, new_room.room_id)
        return CommandResponse(success=True, code="room_changed",
                               text=f"You are now in room '{new_room.name}'.",
                               payload={"room_id": new_room.room_id,
                                        "room_name": new_room.name})

    async def _handle_change_room(self, session_id, state, command):
        user = User(self.db, state.username)
        await user.load()
        current_room = Room(self.db, self.config, state.current_room)
        await current_room.load()
        next_room = await current_room.go_to_room(command.room)
        if not next_room:
            return ErrorResponse(code="no_next_room",
                                   text=f"Room {command.room} not found.")
        self.sessions.set_current_room(session_id, next_room.room_id)
        return CommandResponse(success=True, code="room_changed",
                               text=f"You are now in room '{next_room.name}'.",
                               payload={"room_id": next_room.room_id})

    async def _handle_enter_message(self, session_id, state, command):
        room = Room(self.db, self.config, state.current_room)
        await room.load()
        if room.id == SystemRoomIDs.MAIL_ID:
            if 'recipient' not in command:
                return ErrorResponse(code="missing_recipient",
                                     text=f"Messages in {room.name} require a recipient")
            else:
                msg_id = await room.post_message(state.username,
                                                 command["content"],
                                                 command["recipient"])
        else:
            msg_id = await room.post_message(state.username, command["content"])
        return CommandResponse(success=True, code="message_posted",
                               text=f"Message {msg_id} posted in {room.name}.",
                               payload={"message_id": msg_id})

    async def _handle_read_new_messages(self, session_id, state, command) -> list[MessageResponse]:
        room = Room(self.db, self.config, state.current_room)
        await room.load()
        msg_ids = await room.get_unread_message_ids(state.username)
        if not msg_ids:
            return CommandResponse(success=True, code="no_unread", text="No unread messages.")
        messages = []
        for msg_id in msg_ids:
            msg = self.msg_mgr.get_message(msg_id)
            sender = User(self.db, msg["sender"])
            await sender.load()
            messages.append(MessageResponse(
                id=msg["id"],
                sender=msg["sender"],
                display_name=sender.display_name,
                timestamp=msg["timestamp"],
                room=room.name,
                content=msg["content"],
                blocked=msg["blocked"]
            ))
        return messages
