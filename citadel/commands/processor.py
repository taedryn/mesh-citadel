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
            "goto": self._handle_goto,
            "next": self._handle_next_room,
            # "previous": self._handle_previous_room,
            "post": self._handle_post,
            "read": self._handle_read,
            # add more commands here
        }

    async def process(self, token: str, command) -> CommandResponse | MessageResponse:
        # 1. Validate session
        state = self.sessions.validate_session(token)
        if not state:
            return ErrorResponse(code="invalid_session", text="Session expired or invalid.")
        self.sessions.touch_session(token)

        # 2. Workflow check
        wf = self.sessions.get_workflow(token)
        if wf:
            handler = workflow_registry.get(wf.kind)
            if not handler:
                return ErrorResponse(code="unknown_workflow", text=f"Unknown workflow: {wf.kind}")
            return await handler.handle(self, token, state, command, wf)

        # Permission check
        user = User(self.db, state.username)
        await user.load()
        room = None
        if state.current_room:
            room = Room(self.db, self.config, state.current_room)
            await room.load()

        if not is_allowed(command.name, user, room):
            return permission_denied(command.name, user, room)

        # 3. Normal dispatch
        handler = self.dispatch.get(command.name)
        if not handler:
            return ErrorResponse(code="unknown_command", text=f"Unknown command: {command.name}")

        try:
            return await handler(token, state, command)
        except Exception as e:
            log.exception("Command failed")
            return ErrorResponse(code="internal_error", text=str(e))

    # ------------------------------------------------------------
    # Simple, auth-free handlers
    # ------------------------------------------------------------
    async def _handle_quit(self, token, state, command):
        self.sessions.expire_session(token)
        return CommandResponse(success=True, code="quit", text="Goodbye!")

    # ------------------------------------------------------------
    # External handlers
    # ------------------------------------------------------------
    async def _handle_goto(self, token, state, command):
        room = Room(self.db, self.config, command.args[0])
        await room.load()
        self.sessions.set_current_room(token, room.room_id)
        return CommandResponse(success=True, code="room_changed",
                               text=f"You are now in room '{room.name}'.",
                               payload={"room_id": room.room_id, "room_name": room.name})

    async def _handle_next_room(self, token, state, command):
        user = User(self.db, state.username)
        await user.load()
        current_room = Room(self.db, self.config, state.current_room)
        await current_room.load()
        next_room = await current_room.go_to_next_room(user)
        if not next_room:
            return CommandResponse(success=True, code="no_next_room", text="No further rooms available.")
        self.sessions.set_current_room(token, next_room.room_id)
        return CommandResponse(success=True, code="room_changed",
                               text=f"You are now in room '{next_room.name}'.",
                               payload={"room_id": next_room.room_id})

    async def _handle_post(self, token, state, command):
        room = Room(self.db, self.config, state.current_room)
        await room.load()
        msg_id = await room.post_message(state.username, command.args[0])
        return CommandResponse(success=True, code="message_posted",
                               text=f"Message {msg_id} posted in {room.name}.",
                               payload={"message_id": msg_id})

    async def _handle_read(self, token, state, command):
        user = User(self.db, state.username)
        await user.load()
        room = Room(self.db, self.config, state.current_room)
        await room.load()
        msg = await room.get_next_unread_message(user)
        if not msg:
            return CommandResponse(success=True, code="no_unread", text="No unread messages.")
        return MessageResponse(
            id=msg["id"],
            sender=msg["sender"],
            display_name=msg["display_name"],
            timestamp=msg["timestamp"],
            room=room.name,
            content=msg["content"],
            blocked=msg["blocked"]
        )
