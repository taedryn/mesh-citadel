# citadel/workflows/base.py

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from citadel.transport.packets import ToUser
    from citadel.session.state import WorkflowState


@dataclass
class WorkflowContext:
    """providers necessary for workflow execution, so we can avoid
    passing every last thing as an argument"""
    session_id: str
    db: "DatabaseManager"
    config: "ConfigManager"
    session_mgr: "SessionManager"
    wf_state: "WorkflowState"


@dataclass
class WorkflowState:
    kind: str
    step: int = 0
    data: Dict[str, Any] = field(default_factory=dict)


class Workflow:
    """Abstract base for all workflows."""
    kind: str

    async def handle(self, context, command) -> "ToUser":
        """Process a command within this workflow.
        Must return a ToUser packet.
        'context' is a WorkflowContext object.
        'command' appears to be the input from the user?
        """
        raise NotImplementedError

    async def start(self, context) -> "ToUser":
        """Generate the first prompt when this workflow is started.

        Called immediately after workflow creation to provide the initial
        user prompt. Should return a ToUser packet with appropriate hints.

        Default implementation delegates to handle() with None command,
        but workflows can override for custom start behavior.
        """
        return await self.handle(context, None)

    async def cleanup(self, context):
        """Clean up workflow state when cancelled.

        Called when a workflow is cancelled via the cancel command.
        Should clean up any persistent state (database entries, session state, etc.)
        created during workflow execution.

        Args:
            context: WorkflowContext object containing manager,
            session, and state information
        """
        # Default implementation does nothing - workflows can override if needed
        pass
