# citadel/workflows/types.py

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class WorkflowPrompt:
    workflow: str
    step: int
    prompt: str
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResponse:
    workflow: str
    step: int
    response: str
