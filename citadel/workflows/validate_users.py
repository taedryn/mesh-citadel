""" this workflow is not currently functional, but is being left in
place to represent the fact that we do want a user-validation workflow
at some point soon. """

# citadel/workflows/validate_users.py

from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.transport.packets import ToUser


@register
class ValidateUsersWorkflow(Workflow):
    kind = "validate_users"

    async def handle(self, context, command):
        if command == "approve":
            context.session_mgr.clear_workflow(session_id)
            return ToUser(
                session_id=context.session_id,
                text="User approved."
            )
        elif command == "reject":
            context.session_mgr.clear_workflow(session_id)
            return ToUser(
                session_id=context.session_id,
                text="User rejected."
            )
        return ToUser(
            session_id=context.session_id,
            text=f"Command '{command}' not valid in workflow {self.kind}",
            is_error=True,
            error_code="invalid_workflow_command"
        )

    async def cleanup(self, context):
        """Clean up validate users workflow when cancelled.

        This workflow doesn't create persistent state, so no cleanup needed.
        """
        # No persistent state to clean up
        pass
