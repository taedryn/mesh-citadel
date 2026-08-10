# tests/commands/test_commands.py

import pytest
import pytest_asyncio
import os
import tempfile

from citadel.commands.registry import registry
from citadel.commands import builtins
from citadel.commands.base import BaseCommand
from citadel.commands.processor import CommandProcessor
from citadel.auth.permissions import PermissionLevel
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.room.room import Room, SystemRoomIDs
from citadel.session.manager import SessionManager
from citadel.transport.packets import FromUser, FromUserType
from citadel.user.user import User


def test_registry_contains_all_expected_commands():
    # Core codes that should always be present. This is intentionally a
    # subset check, not exact-set equality -- new commands (e.g. AskAICommand)
    # get added over time and shouldn't break this test. CANCEL is the
    # actual registered code (not lowercase "cancel" -- it's a full-word
    # code, same as STOP, since both are special-cased command letters).
    expected_codes = {
        "G", "E", "R", "N", "K", "I", "Q", "S", "C", "H", "?", "M", "W", "D",
        "B", ".C", ".ER", ".EU", ".FF", "V", "CANCEL", "STOP",
    }
    available_codes = set(registry.available().keys())
    missing = expected_codes - available_codes
    assert not missing, f"Missing commands: {missing}"


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
        username="alice", room="Lobby", args="Hello")
    d = cmd.to_dict()
    assert d["username"] == "alice"
    assert d["room"] == "Lobby"
    assert d["args"] == "Hello"
    assert d["code"] == "E"
    assert d["name"] == "enter_message"
    assert d["permission_level"] == PermissionLevel.USER.value


def test_permission_levels_are_set_correctly():
    assert builtins.CreateRoomCommand.permission_level == PermissionLevel.USER
    assert builtins.EditRoomCommand.permission_level == PermissionLevel.SYSOP
    assert builtins.FastForwardCommand.permission_level == PermissionLevel.USER


def test_help_text_present():
    # The old arg_schema-based validation system was deliberately removed
    # mid-transition (see BaseCommand.validate()'s docstring) -- commands
    # now validate their own args inside run(), not via a declared schema.
    cmd_cls = builtins.EnterMessageCommand
    assert "message" in cmd_cls.help_text.lower()
    assert not hasattr(cmd_cls, "arg_schema")


def test_validate_users_command_metadata():
    cmd_cls = builtins.ValidateUsersCommand
    assert cmd_cls.code == "V"
    assert cmd_cls.name == "validate_users"
    assert cmd_cls.permission_level == PermissionLevel.AIDE
    assert "validation" in cmd_cls.help_text.lower()


def test_block_user_not_yet_implemented():
    # No arg validation exists for this command (at the run() level or
    # otherwise) because there's no run() at all yet.
    assert not builtins.BlockUserCommand.is_implemented()


# -----------------------------------------------------------------------
# EnterMessageCommand.validate() -- the one command that still has a real
# (if minimal) override of the otherwise-dead validate() hook. It isn't
# called anywhere in the live request path (CommandProcessor never calls
# command.validate()), but it exists and does something, so it's still
# worth covering directly.
# -----------------------------------------------------------------------

def test_enter_message_validate_requires_args_in_mail_room():
    cmd = builtins.EnterMessageCommand(username="alice", room="Mail", args="")
    with pytest.raises(ValueError):
        cmd.validate(context={"room": "Mail"})


def test_enter_message_validate_allows_any_nonempty_args_in_mail_room():
    # validate() only checks that *some* argument text was supplied, not
    # that it specifically looks like a recipient -- args is a flat string
    # now, not a {"recipient": ...} dict.
    cmd = builtins.EnterMessageCommand(username="alice", room="Mail", args="bob")
    cmd.validate(context={"room": "Mail"})  # should not raise


def test_enter_message_validate_allows_empty_args_outside_mail_room():
    cmd = builtins.EnterMessageCommand(username="alice", room="Lobby", args="")
    cmd.validate(context={"room": "Lobby"})  # should not raise


# -----------------------------------------------------------------------
# Real run()-level arg handling, via a full CommandProcessor -- this is
# where argument validation actually lives now for most commands.
# -----------------------------------------------------------------------

@pytest.fixture
def config():
    path = tempfile.NamedTemporaryFile(delete=False)
    local_config = Config()
    local_config.database['db_path'] = path.name
    yield local_config
    os.unlink(path.name)


@pytest_asyncio.fixture
async def db(config):
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)
    yield db_mgr
    await db_mgr.shutdown()


@pytest_asyncio.fixture
async def logged_in_session(db, config):
    await User.create(config, db, "bob", "x", "y")
    bob = User(db, "bob")
    await bob.load()
    await bob.set_permission_level(PermissionLevel.USER)

    session_mgr = SessionManager(config, db)
    session_id = session_mgr.create_session("bob")
    session_mgr.mark_username(session_id, "bob")
    await session_mgr.mark_logged_in(session_id)
    return session_mgr, session_id


@pytest.mark.asyncio
async def test_delete_message_requires_message_id(db, config, logged_in_session):
    session_mgr, session_id = logged_in_session
    processor = CommandProcessor(config, db, session_mgr)

    cmd = builtins.DeleteMessageCommand(username="bob")
    fromuser = FromUser(session_id=session_id, payload=cmd, payload_type=FromUserType.COMMAND)
    resp = await processor.process(fromuser)

    assert resp.is_error
    assert "must be specified" in resp.text


@pytest.mark.asyncio
async def test_validate_users_command_accepts_no_args(db, config):
    await User.create(config, db, "aide", "x", "y")
    aide = User(db, "aide")
    await aide.load()
    await aide.set_permission_level(PermissionLevel.AIDE)

    session_mgr = SessionManager(config, db)
    session_id = session_mgr.create_session("aide")
    session_mgr.mark_username(session_id, "aide")
    await session_mgr.mark_logged_in(session_id)

    processor = CommandProcessor(config, db, session_mgr)
    cmd = builtins.ValidateUsersCommand(username="aide")
    fromuser = FromUser(session_id=session_id, payload=cmd, payload_type=FromUserType.COMMAND)
    resp = await processor.process(fromuser)

    assert not resp.is_error
    assert "No users pending validation." in resp.text
