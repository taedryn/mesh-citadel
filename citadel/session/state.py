# citadel/session/state.py

from dataclasses import dataclass
from typing import Optional, Dict, Any

from citadel.workflows.base import WorkflowState


@dataclass
class SessionState:
    username: Optional[str] = None
    current_room: Optional[int] = None
    workflow: Optional[WorkflowState] = None
    logged_in: bool = False
