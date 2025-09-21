# citadel/workflows/base.py

from citadel.commands.responses import CommandResponse, ErrorResponse

class Workflow:
    """Abstract base for all workflows."""
    kind: str

    async def handle(self, processor, token, state, command, wf_state):
        """Process a command within this workflow.
        Must return a CommandResponse or MessageResponse.
        """
        raise NotImplementedError

