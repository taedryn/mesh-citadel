# citadel/workflows/enter_message.py
from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.transport.packets import ToUser
from citadel.workflows.base import WorkflowState
from citadel.room.room import Room, SystemRoomIDs
from citadel.user.user import User

@register
class EnterMessageWorkflow(Workflow):
    kind = "enter_message"

    async def start(self, context):
        state = context.session_mgr.get_session_state(session_id)
        room_id = state.current_room
        if room_id == SystemRoomIDs.MAIL_ID:
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(
                    kind=self.kind,
                    step=1,
                    data=data
                )
            )
            return ToUser(
                session_id=context.session_id,
                text="Enter recipient username:",
                hints={"type": "text", "workflow": self.kind, "step": 1}
            )
        else:
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(
                    kind=self.kind,
                    step=2,
                    data=data
                )
            )
            return ToUser(
                session_id=context.session_id,
                text="Enter your message. End with a single '.' on a line:",
                hints={"type": "text", "workflow": self.kind, "step": 2}
            )

    async def handle(self, context, command):
        state = context.session_mgr.get_session_state(context.session_id)
        db = context.db
        config = context.config
        step = context.wf_state.step
        data = context.wf_state.data
        room = Room(db, config, state.current_room)
        await room.load()

        # Step 1: Recipient (Mail room only)
        if step == 1:
            recipient = command.strip()
            if not recipient or not await User.username_exists(db, recipient):
                return ToUser(
                    session_id=context.session_id,
                    text="Recipient not found. Try again.",
                    is_error=True,
                    error_code="invalid_recipient"
                )

            data["recipient"] = recipient
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(
                    kind=self.kind,
                    step=2,
                    data=data
                )
            )
            return ToUser(
                session_id=context.session_id,
                text="Enter your message. End with a single '.' on a line:",
                hints={"type": "text", "workflow": self.kind, "step": 2}
            )

        # Step 2: Message entry
        elif step == 2:
            line = command.strip()
            lines = data.get("lines", [])

            if line == ".":
                content = "\n".join(lines)
                if room.room_id == SystemRoomIDs.MAIL_ID:
                    msg_id = await room.post_message(
                        state.username,
                        content,
                        data["recipient"])
                else:
                    msg_id = await room.post_message(state.username, content)

                context.session_mgr.clear_workflow(context.session_id)
                return ToUser(
                    session_id=context.session_id,
                    text=f"Message {msg_id} posted in {room.name}."
                )
            else:
                lines.append(line)
                data["lines"] = lines
                context.session_mgr.set_workflow(
                    context.session_id,
                    WorkflowState(
                        kind=self.kind,
                        step=2,
                        data=data
                    )
                )
                return None

        return ToUser(
            session_id=context.session_id,
            text=f"Invalid step {step}",
            is_error=True,
            error_code="invalid_step"
        )

