# citadel/workflows/base.py

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from citadel.transport.packets import ToUser


class Workflow:
    """Abstract base for all workflows."""
    kind: str

    async def handle(self, processor, session_id, state, command, wf_state) -> "ToUser":
        """Process a command within this workflow.
        Must return a ToUser packet.
        """
        raise NotImplementedError

    async def cleanup(self, processor, session_id, wf_state):
        """Clean up workflow state when cancelled.

        Called when a workflow is cancelled via the cancel command.
        Should clean up any persistent state (database entries, session state, etc.)
        created during workflow execution.

        Args:
            processor: Command processor instance with access to db, config, sessions
            session_id: Session ID for the workflow being cancelled
            wf_state: Workflow state containing step and data
        """
        # Default implementation does nothing - workflows can override if needed
        pass
