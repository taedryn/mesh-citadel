# tests/commands/test_dot_commands.py

import pytest

from citadel.commands import builtins
from citadel.auth.permissions import PermissionLevel


def test_create_room_requires_room_name():
    cmd = builtins.CreateRoomCommand(username="aide", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"role": "aide"})


def test_create_room_valid():
    cmd = builtins.CreateRoomCommand(
        username="aide",
        args={"room": "NewRoom", "description": "A test room"}
    )
    cmd.validate(context={"role": "aide"})


def test_edit_room_requires_room_and_attributes():
    cmd = builtins.EditRoomCommand(username="sysop", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"role": "sysop"})


def test_edit_room_valid():
    cmd = builtins.EditRoomCommand(
        username="sysop",
        args={"room": "Lobby", "attributes": {"topic": "New topic"}}
    )
    cmd.validate(context={"role": "sysop"})


def test_edit_user_requires_target_and_attributes():
    cmd = builtins.EditUserCommand(username="sysop", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"role": "sysop"})


def test_edit_user_valid():
    cmd = builtins.EditUserCommand(
        username="sysop",
        args={"target_user": "alice", "attributes": {"permission": "aide"}}
    )
    cmd.validate(context={"role": "sysop"})


def test_fast_forward_has_no_args():
    cmd = builtins.FastForwardCommand(username="bob", args={})
    cmd.validate(context={"room": "Lobby"})  # should not raise

    # If args are provided, it should fail
    cmd = builtins.FastForwardCommand(username="bob", args={"extra": "oops"})
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Lobby"})


def test_permissions_for_dot_commands():
    assert builtins.CreateRoomCommand.permission_level == PermissionLevel.AIDE
    assert builtins.EditRoomCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.EditUserCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.FastForwardCommand.permission_level == PermissionLevel.USER

