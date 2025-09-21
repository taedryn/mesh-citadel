# bbs/commands/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from citadel.auth.permissions import PermissionLevel


class BaseCommand(ABC):
    """
    Base class for all BBS commands.
    Transport layers construct these objects and pass them
    to the BBS interpreter for execution.
    """

    # Every subclass must override these
    code: str        # short code, e.g. "L" for list rooms
    name: str        # canonical name, e.g. "list_rooms"
    permission: PermissionLevel = PermissionLevel.USER

    # Human‑readable description
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
            "permission": self.permission.value,
        }

    def __repr__(self) -> str:
        return f"<Command {self.code} ({self.name}) user={self.username!r} room={self.room!r} args={self.args!r} permission={self.permission.value}>"
