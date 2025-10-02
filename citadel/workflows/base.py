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
