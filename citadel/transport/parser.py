# citadel/transport/parser.py

import logging
from typing import Union
from citadel.commands.base import BaseCommand
from citadel.commands.registry import registry
from citadel.transport.packets import ToUser

log = logging.getLogger(__name__)


class TextParser:
    """Parses text input into BaseCommand objects."""

    def __init__(self):
        pass

    def parse_command(self, text: str) -> Union[BaseCommand, bool]:
        """
        Parse a text string into a BaseCommand object.

        Args:
            text: Raw text input from user (e.g., "G", "H V", "E message text")

        Returns:
            BaseCommand instance if parsing succeeds, False if it fails
        """
        if not text or not text.strip():
            log.warning("Empty command failed")
            return False

        # Split command and arguments
        parts = text.strip().split(None, 1)  # Split on first whitespace only
        command_code = parts[0].upper()
        args_text = parts[1] if len(parts) > 1 else ""

        # Look up command class in registry
        command_cls = registry.get(command_code)
        if not command_cls:
            log.warning(f"Unknown command: {command_code}")
            return False

        # Create command instance with placeholder username (real username comes from session)
        command = command_cls(username="")

        # Store raw args text - individual commands can parse as needed
        if hasattr(command, 'args'):
            command.args = args_text

        return command
