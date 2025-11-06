# citadel/command/processor.py

import logging

from citadel.auth.permissions import is_allowed, permission_denied
from citadel.commands.base import CommandContext
from citadel.message.manager import MessageManager
from citadel.room.room import Room, SystemRoomIDs
from citadel.session.manager import SessionManager
from citadel.transport.packets import FromUser, ToUser
from citadel.transport.validator import InputValidator
from citadel.user.user import User
from citadel.workflows import registry as workflow_registry
from citadel.workflows.base import WorkflowContext

# Import to register built-in commands
import citadel.commands.builtins  # noqa: F401

log = logging.getLogger(__name__)


class CommandProcessor:
    def __init__(self, config, db, session_mgr: SessionManager):
        self.config = config
        self.db = db
        self.sessions = session_mgr
        self.msg_mgr = MessageManager(config, db)
        self.validator = InputValidator(session_mgr)

    async def process(self, packet: FromUser) -> ToUser:
        # 1. Validate input packet
        validation_error = self.validator.validate(packet)
        if validation_error:
            return validation_error  # Already a ToUser error packet

        # 2. Extract session and validate state
        session_id = packet.session_id
        state = self.sessions.get_session_state(session_id)
        wf_state = self.sessions.get_workflow(session_id)
        if not state:
            return ToUser(
                session_id=session_id,
                text="Session expired or invalid.",
                is_error=True,
                error_code="invalid_session"
            )
        if not wf_state and not state.logged_in:
            return ToUser(
                session_id=session_id,
                text="You must log in to use commands.",
                is_error=True,
                error_code="not_logged_in"
            )

        self.sessions.touch_session(session_id)

        # 3. Handle workflow if active
        if wf_state:
            handler = workflow_registry.get(wf_state.kind)
            if not handler:
                return ToUser(
                    session_id=session_id,
                    text=f"Unknown workflow: {wf_state.kind}",
                    is_error=True,
                    error_code="unknown_workflow"
                )

            # For workflows, pass raw string response directly
            if packet.payload_type.value == "workflow_response":
                context = WorkflowContext(
                    session_id=session_id,
                    db=self.db,
                    config=self.config,
                    session_mgr=self.sessions,
                    wf_state=wf_state
                )
                return await handler.handle(context, packet.payload)
            else:
                # Got command packet while in workflow - only allow cancel command
                command = packet.payload
                if command.name == "cancel":
                    # Allow cancel command to execute even in workflow
                    pass  # Continue to regular command processing below
                else:
                    return ToUser(
                        session_id=session_id,
                        text="Cannot execute commands while in a workflow. Type 'cancel' to exit the workflow.",
                        is_error=True,
                        error_code="workflow_active"
                    )

        # 5. Handle regular commands
        if packet.payload_type.value != "command":
            return ToUser(
                session_id=session_id,
                text="Invalid request type outside of workflow.",
                is_error=True,
                error_code="invalid_request_type"
            )

        command = packet.payload
        log.debug(f"Processing command: {command.name} for session {session_id}")

        # Permission check
        user = User(self.db, state.username)
        await user.load()

        room = None
        if state.current_room:
            room = Room(self.db, self.config, state.current_room)
            await room.load()

        if not is_allowed(command.name, user, room):
            return permission_denied(session_id, command.name, user, room)


        # 6. Execute command via its run method
        try:
            context = CommandContext(
                db=self.db,
                config=self.config,
                session_mgr=self.sessions,
                msg_mgr=self.msg_mgr,
                session_id=session_id,
            )
            result = await command.run(context)
            return result
        except RuntimeError as e:
            log.error(f"Command execution failed: {e}")
            return ToUser(
                session_id=session_id,
                text=str(e),
                is_error=True,
                error_code="command_error"
            )
        except ValueError as e:
            log.warning(f"Command validation failed: {e}")
            return ToUser(
                session_id=session_id,
                text=str(e),
                is_error=True,
                error_code="validation_error"
            )
