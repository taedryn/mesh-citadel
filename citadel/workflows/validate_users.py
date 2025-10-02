# citadel/workflows/validate_users.py

from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.transport.packets import ToUser


@register
class ValidateUsersWorkflow(Workflow):
    kind = "validate_users"

    async def handle(self, processor, session_id, state, command, wf_state):
        if command == "approve":
            processor.sessions.clear_workflow(session_id)
            return ToUser(
                session_id=session_id,
                text="User approved."
            )
        elif command == "reject":
            processor.sessions.clear_workflow(session_id)
            return ToUser(
                session_id=session_id,
                text="User rejected."
            )
        return ToUser(
            session_id=session_id,
            text=f"Command '{command}' not valid in workflow {self.kind}",
            is_error=True,
            error_code="invalid_workflow_command"
        )
