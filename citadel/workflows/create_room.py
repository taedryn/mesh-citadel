# citadel/workflows/register_user.py

from datetime import datetime, UTC
import logging
import string

from citadel.auth.passwords import generate_salt, hash_password
from citadel.auth.permissions import PermissionLevel
from citadel.room.room import Room, RoomNotFoundError
from citadel.transport.packets import ToUser
from citadel.user.user import User, UserStatus
from citadel.workflows.base import Workflow, WorkflowState, WorkflowContext
from citadel.workflows.registry import register

log = logging.getLogger(__name__)

def is_ascii_string(user_str: str) -> bool:
    return all(c in string.ascii_letters + string.digits + "_-" for c in user_str)

@register
class CreateRoomWorkflow(Workflow):
    kind = "create_room"

    async def start(self, context):
        """Start the room creation workflow by prompting for room name."""
        text = "Preparing to create new room.\nPlease enter the room name:"
        return ToUser(
            session_id=context.session_id,
            text=text,
            hints={"type": "text", "workflow": self.kind, "step": 1}
        )

    async def handle(self, context, command):
        db = context.db

        step = context.wf_state.step
        data = context.wf_state.data

        # Cancellation is handled by transport layer, no need to check here

        # Step 1: Room name
        if step == 1:
            room_name = command.strip() if command else ""
            if not is_ascii_string(room_name):
                return ToUser(
                    session_id=context.session_id,
                    text="Room names are limited to ASCII characters only",
                    is_error=True,
                    error_code="invalid_room_name"
                )
            if not room_name or len(room_name) < 3:
                return ToUser(
                    session_id=context.session_id,
                    text="Room name must be at least 3 characters.",
                    is_error=True,
                    error_code="invalid_room_name"
                )
            try:
                room_id = await Room.get_id_by_name(context.db, room_name)
                if room_id:
                    return ToUser(
                        session_id=context.session_id,
                        text=f"'{room_name}' already exists. Please try again.",
                        is_error=True,
                        error_code="room_name_taken"
                    )
            except RoomNotFoundError:
                # room name doesn't exist yet, woot
                data['room_name'] = room_name

            session_state = context.session_mgr.get_session_state(context.session_id)
            current_room_id = session_state.current_room
            if current_room_id < Room.MIN_USER_ROOM_ID:
                current_room_id = await Room.get_last_room_id(context.db)
            current_room = Room(context.db, context.config, current_room_id)
            await current_room.load()
            next_room_id = current_room.next_neighbor


            context.session_mgr.clear_workflow(context.session_id)

            new_id = await Room.create(
                context.db,
                context.config,
                name=room_name,
                description="", # no description for now
                read_only=False, # read-only can only be set in the edit flow
                permission_level=PermissionLevel.USER,
                after_room_id=current_room_id
            )

            context.session_mgr.set_current_room(context.session_id, new_id)

            return ToUser(
                session_id=context.session_id,
                text=f"Room {room_name} created!"
            )

        return ToUser(
            session_id=context.session_id,
            text=f"Unknown step {step} in workflow {self.kind}",
            is_error=True,
            error_code="invalid_step"
        )

