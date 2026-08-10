# tests/commands/test_dot_commands.py

import pytest

from citadel.commands import builtins
from citadel.auth.permissions import PermissionLevel


def test_create_room_is_implemented_and_ignores_args_at_validate_time():
    # CreateRoomCommand doesn't validate args at all anymore -- it just
    # kicks off the create_room workflow, which collects the room name
    # interactively. validate() is the inherited BaseCommand no-op.
    assert builtins.CreateRoomCommand.is_implemented()
    cmd = builtins.CreateRoomCommand(username="aide", args="")
    cmd.validate(context={"role": "aide"})  # should not raise


def test_edit_room_not_yet_implemented():
    assert not builtins.EditRoomCommand.is_implemented()


def test_edit_user_not_yet_implemented():
    assert not builtins.EditUserCommand.is_implemented()


def test_fast_forward_not_yet_implemented():
    assert not builtins.FastForwardCommand.is_implemented()


def test_permissions_for_dot_commands():
    assert builtins.CreateRoomCommand.permission_level == PermissionLevel.USER
    assert builtins.EditRoomCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.EditUserCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.FastForwardCommand.permission_level == PermissionLevel.USER
