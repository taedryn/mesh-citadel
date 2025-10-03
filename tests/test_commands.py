# tests/commands/test_commands.py

import pytest

from citadel.commands.registry import registry
from citadel.commands import builtins
from citadel.commands.base import BaseCommand
from citadel.auth.permissions import PermissionLevel


def test_registry_contains_all_expected_commands():
    # Codes from prompt.md
    expected_codes = {
        "G", "E", "R", "N", "K", "I", "Q", "S", "C", "H", "?", "M", "W", "D",
        "B", ".C", ".ER", ".EU", ".FF", "V", "cancel",
    }
    available_codes = set(registry.available().keys())
    missing = expected_codes - available_codes
    extra = available_codes - expected_codes
    assert not missing, f"Missing commands: {missing}"
    assert not extra, f"Unexpected extra commands: {extra}"


@pytest.mark.parametrize("code,expected_class", [
    ("K", builtins.KnownRoomsCommand),
    ("G", builtins.GoNextUnreadCommand),
    ("M", builtins.MailCommand),
    (".C", builtins.CreateRoomCommand),
])
def test_registry_lookup_returns_correct_class(code, expected_class):
    cls = registry.get(code)
    assert cls is expected_class
    assert issubclass(cls, BaseCommand)


def test_command_to_dict_includes_username_and_room():
    cmd = builtins.EnterMessageCommand(
        username="alice", room="Lobby", args={"content": "Hello"})
    d = cmd.to_dict()
    assert d["username"] == "alice"
    assert d["room"] == "Lobby"
    assert d["args"]["content"] == "Hello"
    assert d["code"] == "E"
    assert d["name"] == "enter_message"
    assert d["permission_level"] == PermissionLevel.USER.value


def test_permission_levels_are_set_correctly():
    assert builtins.CreateRoomCommand.permission_level == PermissionLevel.USER
    assert builtins.EditRoomCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.FastForwardCommand.permission_level == PermissionLevel.USER


def test_help_text_and_arg_schema_present():
    cmd_cls = builtins.EnterMessageCommand
    assert "message" in cmd_cls.help_text.lower()
    assert "content" in cmd_cls.arg_schema
    assert cmd_cls.arg_schema["content"]["required"] is True


def test_validate_users_command_metadata():
    cmd_cls = builtins.ValidateUsersCommand
    assert cmd_cls.code == "V"
    assert cmd_cls.name == "validate_users"
    assert cmd_cls.permission_level == PermissionLevel.AIDE
    assert "validation" in cmd_cls.help_text.lower()
    assert cmd_cls.arg_schema == {}


# -----------------------------------------------------------------------
# error-path validation tests
# -----------------------------------------------------------------------

def test_enter_message_requires_content():
    # Missing "content" should fail
    cmd = builtins.EnterMessageCommand(username="alice", room="Lobby", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Lobby"})


def test_enter_message_requires_recipient_in_mail_room():
    # In Mail room, recipient is required
    cmd = builtins.EnterMessageCommand(
        username="alice",
        room="Mail",
        args={"content": "Hello"}
    )
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Mail"})


def test_delete_message_requires_message_id():
    # Missing message_id should fail
    cmd = builtins.DeleteMessageCommand(username="bob", room="Lobby", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Lobby"})


def test_block_user_requires_target_user():
    # Missing target_user should fail
    cmd = builtins.BlockUserCommand(username="bob", room="Lobby", args={})
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Lobby"})


def test_validate_users_command_accepts_no_args():
    # No args should be fine
    cmd = builtins.ValidateUsersCommand(username="aide", args={})
    cmd.validate(context={"role": "aide"})  # should not raise

    # Extraneous args should fail
    cmd = builtins.ValidateUsersCommand(
        username="aide", args={"extra": "oops"})
    with pytest.raises(ValueError):
        cmd.validate(context={"role": "aide"})


# -----------------------------------------------------------------------
# positive validation tests
# -----------------------------------------------------------------------

def test_enter_message_valid_in_regular_room():
    cmd = builtins.EnterMessageCommand(
        username="alice",
        room="Lobby",
        args={"content": "Hello everyone!"}
    )
    # Should not raise
    cmd.validate(context={"room": "Lobby"})


def test_enter_message_valid_in_mail_room():
    cmd = builtins.EnterMessageCommand(
        username="alice",
        room="Mail",
        args={"content": "Private hello", "recipient": "bob"}
    )
    # Should not raise
    cmd.validate(context={"room": "Mail"})


def test_delete_message_valid():
    cmd = builtins.DeleteMessageCommand(
        username="bob",
        room="Lobby",
        args={"message_id": "1234"}
    )
    cmd.validate(context={"room": "Lobby"})


def test_block_user_valid():
    cmd = builtins.BlockUserCommand(
        username="bob",
        room="Lobby",
        args={"target_user": "charlie"}
    )
    cmd.validate(context={"room": "Lobby"})
