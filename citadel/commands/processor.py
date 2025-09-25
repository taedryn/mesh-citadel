# citadel/command/processor.py

import logging
from citadel.auth.checker import is_allowed, permission_denied
from citadel.commands.base import CommandContext
from citadel.commands.responses import MessageResponse, CommandResponse, ErrorResponse
from citadel.session.manager import SessionManager
from citadel.user.user import User
from citadel.room.room import Room, SystemRoomIDs
from citadel.message.manager import MessageManager
from citadel.workflows import registry as workflow_registry

log = logging.getLogger(__name__)


class CommandProcessor:
    def __init__(self, config, db, session_mgr: SessionManager):
        self.config = config
        self.db = db
        self.sessions = session_mgr
        self.msg_mgr = MessageManager(config, db)


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

        # 3. Execute command via its run method
        try:
            context = CommandContext(
                db=self.db,
                config=self.config,
                session_mgr=self.sessions,
                msg_mgr=self.msg_mgr,
                session_id=session_id
            )
            return await command.run(context)
        except RuntimeError as e:
            log.error(f"Command execution failed: {e}")
            return ErrorResponse(code="command_error", text=str(e))
        except ValueError as e:
            log.warning(f"Command validation failed: {e}")
            return ErrorResponse(code="validation_error", text=str(e))

