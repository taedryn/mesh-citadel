# citadel/transport/packets.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict

from citadel.commands.responses import MessageResponse


class FromUserType(str, Enum):
    """Types of payload that can be sent from user to BBS."""
    COMMAND = "command"
    WORKFLOW_RESPONSE = "workflow_response"


@dataclass
class ToUser:
    """Packet sent from BBS to transport layer for user display."""
    session_id: str
    text: str
    hints: Dict[str, Any] = field(default_factory=dict)
    message: Optional[MessageResponse] = None
    is_error: bool = False
    error_code: Optional[str] = None


@dataclass
class FromUser:
    """Packet sent from transport layer to BBS containing validated user input."""
    session_id: str
    payload: Any
    payload_type: FromUserType