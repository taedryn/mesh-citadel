# citadel/responses.py

from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class MessageResponse:
    """Represents a BBS message to display to the user."""
    id: int
    sender: str
    display_name: str
    timestamp: str
    room: str
    content: str
    blocked: bool = False
    recipient: str = ""


@dataclass
class CommandResponse:
    """Represents the outcome of a command (not a full message)."""
    success: bool
    code: str
    text: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


@dataclass
class ErrorResponse(CommandResponse):
    """Specialization of CommandResponse for errors."""

    def __init__(self, code: str, text: str, payload: Optional[dict[str, Any]] = None):
        super().__init__(success=False, code=code, text=text, payload=payload)
