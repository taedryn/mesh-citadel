# bbs/commands/registry.py

from typing import Dict, Type
from citadel.commands.base import BaseCommand

class CommandRegistry:
    def __init__(self):
        self._commands: Dict[str, Type[BaseCommand]] = {}

    def register(self, command_cls: Type[BaseCommand]) -> None:
        if not issubclass(command_cls, BaseCommand):
            raise TypeError("Only subclasses of BaseCommand can be registered")
        if not getattr(command_cls, "code", None):
            raise ValueError("BaseCommand class must define a code")
        if not getattr(command_cls, "permission", None):
            raise ValueError("BaseCommand class must define a permission level")
        self._commands[command_cls.code] = command_cls

    def get(self, code: str) -> Type[BaseCommand]:
        return self._commands[code]

    def available(self) -> Dict[str, Type[BaseCommand]]:
        return dict(self._commands)

    def catalog(self):
        return {
            code: {
                "name": cls.name,
                "permission": cls.permission.value,
                "help": cls.help_text,
                "args": cls.arg_schema,
            }
            for code, cls in self._commands.items()
        }


# Global singleton
registry = CommandRegistry()

def register_command(cls: Type[BaseCommand]) -> Type[BaseCommand]:
    registry.register(cls)
    return cls

