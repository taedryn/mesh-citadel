# bbs/commands/base.py

from abc import ABC
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, TYPE_CHECKING
from citadel.auth.permissions import PermissionLevel

if TYPE_CHECKING:
    from citadel.db.manager import DatabaseManager
    from citadel.config import Config
    from citadel.session.manager import SessionManager
    from citadel.message.manager import MessageManager
    from citadel.commands.responses import MessageResponse
    from citadel.transport.packets import ToUser


@dataclass
class CommandContext:
    """Context provided to command handlers containing all necessary
    provider objects."""
    db: "DatabaseManager"
    config: "Config"
    session_mgr: "SessionManager"
    msg_mgr: "MessageManager"
    session_id: str


class CommandCategory(IntEnum):
    """ these values are used in the classification of different
    commands to figure out how to display them in the help menu."""
    COMMON = 1
    UNCOMMON = 2
    UNUSUAL = 3
    AIDE = 4
    SYSOP = 5


class BaseCommand(ABC):
    """
    Base class for all BBS commands.
    Transport layers construct these objects and pass them
    to the BBS interpreter for execution.
    """

    # Every subclass must override these
    code: str        # short code, e.g. "L" for list rooms
    name: str        # canonical name, e.g. "list_rooms"
    category: CommandCategory = CommandCategory.COMMON
    permission_level: PermissionLevel = PermissionLevel.USER

    # Human‑readable description
    short_text: str = ""
    help_text: str = ""

    # Argument schema: dict of arg_name →
    # { "required": bool, "type": str, "help": str }
    arg_schema: Dict[str, Dict[str, Any]] = {}

    # Schema version for forward compatibility
    schema_version: str = "1.0"

    def __init__(
        self,
        username: str,
        room: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
    ):
        # username must always be supplied (can be empty string, but not None)
        if username is None:
            raise ValueError(
                "username must be supplied (can be empty string, but not None)")
        self.username = username
        self.room = room
        self.args: Dict[str, Any] = args or {}

    def validate(self, context: Optional[Dict[str, Any]] = None) -> None:
        # Check for required args
        for arg, spec in self.arg_schema.items():
            if spec.get("required") and arg not in self.args:
                raise ValueError(f"Missing required argument: {arg}")

        # Check for extraneous args
        for arg in self.args:
            if arg not in self.arg_schema:
                raise ValueError(f"Unexpected argument: {arg}")

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the command into a dict for logging, debugging,
        or transport across system boundaries.
        """
        return {
            "version": self.schema_version,
            "code": self.code,
            "name": self.name,
            "username": self.username,
            "room": self.room,
            "args": self.args,
            "permission_level": self.permission_level.value,
        }

    async def run(self, context: CommandContext) -> "ToUser | list[ToUser]":
        """Execute the command with the given context."""
        raise NotImplementedError(
            f"{self.__class__.__name__} not yet implemented")

    @classmethod
    def is_implemented(cls) -> bool:
        """Check if this command has been implemented (run method overridden)."""
        return cls.run != BaseCommand.run

    def __repr__(self) -> str:
        return f"<Command {self.code} ({self.name}) user={self.username!r} room={self.room!r} args={self.args!r} permission_level={self.permission_level.value}>"
