# citadel/workflows/validate_users.py

from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.commands.responses import CommandResponse, ErrorResponse

@register
class ValidateUsersWorkflow(Workflow):
    kind = "validate_users"

    async def handle(self, processor, token, state, command, wf_state):
        if command.name == "approve":
            processor.sessions.clear_workflow(token)
            return CommandResponse(success=True, code="user_validated", text="User approved.")
        elif command.name == "reject":
            processor.sessions.clear_workflow(token)
            return CommandResponse(success=True, code="user_rejected", text="User rejected.")
        return ErrorResponse(code="invalid_workflow_command",
                             text=f"Command {command.name} not valid in workflow {self.kind}")

