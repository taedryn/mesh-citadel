import os
import pytest
import pytest_asyncio
import tempfile

from citadel.auth.permissions import PermissionLevel
from citadel.config import Config
from citadel.commands.processor import CommandProcessor
from citadel.commands.builtins import (
    GoNextUnreadCommand,
    ChangeRoomCommand,
    EnterMessageCommand,
    ReadNewMessagesCommand,
)
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.room.room import Room, SystemRoomIDs
from citadel.session.manager import SessionManager
from citadel.transport.packets import ToUser, FromUser, FromUserType
from citadel.user.user import User


@pytest.fixture
def config():
    path = tempfile.NamedTemporaryFile(delete=False)
    dummy_config = Config()
    dummy_config.bbs = {
        "max_messages_per_room": 3,
        'room_names': {
            'lobby': 'Lobby',
            'mail': 'Mail',
            'aides': 'Aides',
            'sysop': 'Sysop',
            'system': 'System'
        }
    }
    dummy_config.database = {
        "db_path": path.name,
    }
    dummy_config.logging = {
        'log_file_path': '/tmp/citadel.log',
        'log_level': 'DEBUG'
    }

    yield dummy_config

    os.unlink(path.name)


@pytest_asyncio.fixture
async def db(config):
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    yield db_mgr

    await db_mgr.shutdown()


@pytest.mark.asyncio
async def test_go_next_unread_moves_session(db, config):
    session_mgr = SessionManager(config, db)
    # Create user and session
    await User.create(config, db, 'alice', 'a', 'b', 'Alice W')
    alice = User(db, 'alice')
    await alice.load()
    await alice.set_permission_level(PermissionLevel.USER)
    session_id = await session_mgr.create_session("alice")

    # add a room linked to Lobby
    new_room_id = await Room.create(
        db, config, 'General', '', False, PermissionLevel.USER,
        SystemRoomIDs.LOBBY_ID, False)
    # Post a message in General so it's unread
    general = Room(db, config, new_room_id)
    await general.load()
    await general.post_message("alice", "hello world")

    processor = CommandProcessor(config, db, session_mgr)
    processor.sessions.mark_logged_in(session_id)
    cmd = GoNextUnreadCommand(username="alice", args={})
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)

    assert isinstance(resp, ToUser)
    assert session_mgr.get_current_room(session_id) == new_room_id


@pytest.mark.asyncio
async def test_change_room_by_name_and_id(db, config):
    session_mgr = SessionManager(config, db)
    await User.create(config, db, "bob", "x", "y")
    bob = User(db, "bob")
    await bob.load()
    await bob.set_permission_level(PermissionLevel.USER)
    session_id = await session_mgr.create_session("bob")

    # Create a room
    room_id = await Room.create(db, config, 'TechTalk', '', False, PermissionLevel.USER, SystemRoomIDs.LOBBY_ID, False)

    processor = CommandProcessor(config, db, session_mgr)
    processor.sessions.mark_logged_in(session_id)

    # Change by name
    cmd = ChangeRoomCommand(username="bob", args={"room": "TechTalk"})
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert not resp.is_error, f'got an error: {resp.error_code}'
    assert session_mgr.get_current_room(session_id) == room_id

    # Change by id
    cmd = ChangeRoomCommand(username="bob", args={"room": str(room_id)})
    fromuser.payload = cmd
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert session_mgr.get_current_room(session_id) == room_id


@pytest.mark.asyncio
async def test_enter_message_requires_recipient_in_mail_room(db, config):
    session_mgr = SessionManager(config, db)
    await User.create(config, db, "carol", "x", "y")
    carol = User(db, "carol")
    await carol.load()
    await carol.set_permission_level(PermissionLevel.USER)
    session_id = await session_mgr.create_session("carol")

    # Set current room to Mail room (already exists from system initialization)
    session_mgr.set_current_room(session_id, SystemRoomIDs.MAIL_ID)

    processor = CommandProcessor(config, db, session_mgr)
    processor.sessions.mark_logged_in(session_id)

    # Missing recipient should fail
    cmd = EnterMessageCommand(username="carol", args={"content": "hi"})
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert resp.is_error
    assert resp.error_code == "missing_recipient"

    # With recipient should succeed
    await User.create(config, db, "dave", "x", "y")
    dave = User(db, "dave")
    await dave.load()
    await dave.set_permission_level(PermissionLevel.USER)
    cmd = EnterMessageCommand(username="carol", args={
                              "content": "hi", "recipient": "dave"})
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)


@pytest.mark.asyncio
async def test_read_new_messages_returns_unread(db, config):
    session_mgr = SessionManager(config, db)
    await User.create(config, db, "erin", "x", "y")
    erin = User(db, "erin")
    await erin.load()
    await erin.set_permission_level(PermissionLevel.USER)
    session_id = await session_mgr.create_session("erin")

    # Create a room and set as current
    room_id = await Room.create(db, config, 'General', '', False, PermissionLevel.USER, SystemRoomIDs.LOBBY_ID, False)
    session_mgr.set_current_room(session_id, room_id)

    room = Room(db, config, room_id)
    await room.load()
    await room.post_message("erin", "first")
    await room.post_message("erin", "second")

    processor = CommandProcessor(config, db, session_mgr)
    processor.sessions.mark_logged_in(session_id)
    cmd = ReadNewMessagesCommand(username="erin", args={})
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)

    assert isinstance(resp, list)
    assert all(isinstance(r, ToUser) for r in resp)
    assert len(resp) == 2
    assert resp[0].message.content == "first"
    assert resp[1].message.content == "second"
