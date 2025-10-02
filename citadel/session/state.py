# citadel/session/state.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class WorkflowState:
    kind: str
    step: int = 0
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    username: Optional[str] = None
    current_room: Optional[int] = None
    workflow: Optional[WorkflowState] = None
    logged_in: bool = False
