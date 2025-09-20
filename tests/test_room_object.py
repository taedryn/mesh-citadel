import os
import pytest
import pytest_asyncio
import tempfile

from citadel.room.room import Room
from citadel.user.user import User
from citadel.message.manager import MessageManager
from citadel.room.errors import RoomNotFoundError, PermissionDeniedError
from citadel.db.initializer import initialize_database
from citadel.db.manager import DatabaseManager
from citadel.config import Config


@pytest.fixture
def config():
    path = tempfile.NamedTemporaryFile(delete=False)
    dummy_config = Config()
    dummy_config.bbs = {
        "max_messages_per_room": 3,
        "system_events_room_id": 999
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
    await initialize_database(db_mgr)

    yield db_mgr

    await db_mgr.shutdown()

@pytest_asyncio.fixture
async def setup_rooms(db):
    # Create a chain of 3 rooms
    await db.execute("INSERT INTO rooms (id, name, description, permission_level, prev_neighbor, next_neighbor) VALUES (1, 'Lobby', 'Main room', 'user', NULL, 2)")
    await db.execute("INSERT INTO rooms (id, name, description, permission_level, prev_neighbor, next_neighbor) VALUES (2, 'Tech', 'Tech talk', 'user', 1, 3)")
    await db.execute("INSERT INTO rooms (id, name, description, permission_level, prev_neighbor, next_neighbor) VALUES (3, 'Aides', 'Private aide room', 'aide', 2, NULL)")

@pytest_asyncio.fixture
async def setup_users(db):
    await db.execute("INSERT INTO users (username, permission, password_hash, salt) VALUES ('twit', 'twit', 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission, password_hash, salt) VALUES ('user', 'user', 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission, password_hash, salt) VALUES ('aide', 'aide', 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission, password_hash, salt) VALUES ('sysop', 'sysop', 'hash', 'salt')")

@pytest.mark.asyncio
async def test_room_initialization(db, config, setup_rooms):
    room = Room(db, config, 1)
    await room.load()
    assert room.name == "Lobby"
    assert room.next_neighbor == 2
    assert room.prev_neighbor is None

@pytest.mark.asyncio
async def test_permission_logic(db, config, setup_rooms, setup_users):
    lobby = Room(db, config, 1)
    await lobby.load()
    aides = Room(db, config, 3)
    await aides.load()

    user = User(db, "user")
    await user.load()
    aide = User(db, "aide")
    await aide.load()
    twit = User(db, "twit")
    await twit.load()

    assert lobby.can_user_read(user)
    assert not aides.can_user_read(user)
    assert aides.can_user_read(aide)
    assert not lobby.can_user_read(twit)

@pytest.mark.asyncio
async def test_ignore_logic(db, config, setup_rooms, setup_users):
    room = Room(db, config, 1)
    await room.load()
    user = User(db, "user")
    await user.load()

    assert not await room.is_ignored_by(user)
    await room.ignore_for_user(user)
    assert await room.is_ignored_by(user)
    await room.unignore_for_user(user)
    assert not await room.is_ignored_by(user)

@pytest.mark.asyncio
async def test_go_to_next_room_with_unread(db, config, setup_rooms, setup_users):
    await Room.initialize_room_order(db, config)
    lobby = Room(db, config, 1)
    await lobby.load()
    user = User(db, "user")
    await user.load()

    # Simulate unread messages in room 2
    await db.execute("INSERT INTO room_messages (room_id, message_id, timestamp) VALUES (2, 101, '2025-09-18T21:00:00Z')")
    await db.execute("INSERT INTO user_room_state (username, room_id, last_seen_message_id) VALUES ('user', 2, NULL)")

    next_room = await lobby.go_to_next_room(user, with_unread=True)
    await next_room.load()
    assert next_room.room_id == 2

@pytest.mark.asyncio
async def test_post_message_and_rotation(db, config, setup_rooms, setup_users):
    room = Room(db, config, 1)
    await room.load()
    user = User(db, "user")
    await user.load()

    ids = [await room.post_message(user.username, f"msg {i}") for i in range(3)]
    found_ids = await room.get_message_ids()
    assert found_ids == ids

    new_id = await room.post_message(user.username, "msg 4")
    remaining = await room.get_message_ids()
    assert len(remaining) == config.bbs["max_messages_per_room"]
    assert ids[0] not in remaining
    assert new_id in remaining

@pytest.mark.asyncio
async def test_user_read_tracking(db, config, setup_rooms, setup_users):
    room = Room(db, config, 1)
    await room.load()
    user = User(db, "user")
    await user.load()

    msg_id = await room.post_message(user.username, "Welcome!")
    msg = await room.get_next_unread_message(user)
    assert msg["id"] == msg_id

    # Should return None now that it's read
    assert await room.get_next_unread_message(user) is None

@pytest.mark.asyncio
async def test_skip_to_latest(db, config, setup_rooms, setup_users):
    room = Room(db, config, 1)
    await room.load()
    user = User(db, "user")
    await user.load()

    msg_id = await room.post_message(user.username, "Latest message")
    await room.skip_to_latest(user)

    pointer = await db.execute("SELECT last_seen_message_id FROM user_room_state WHERE username = ? AND room_id = ?", (user.username, room.room_id))
    assert pointer[0][0] == msg_id

@pytest.mark.asyncio
async def test_room_deletion_logs_event(db, config, setup_rooms, setup_users):
    await db.execute("INSERT INTO rooms (id, name, description, permission_level, prev_neighbor, next_neighbor) VALUES (999, 'System', 'System events', 'sysop', NULL, NULL)")
    system_room = Room(db, config, 999)
    await system_room.load()
    room = Room(db, config, 1)
    await room.load()
    await room.delete_room("sysop")

    messages = await db.execute("""
        SELECT m.content 
        FROM room_messages rm 
        JOIN messages m ON rm.message_id = m.id 
        WHERE rm.room_id = 999
    """)

    assert any("Room 'Lobby' was deleted." in msg[0] for msg in messages)

@pytest.mark.asyncio
async def test_get_id_by_name(db, config, setup_rooms):
    room = Room(db, config, 1)
    assert await room.get_id_by_name("Lobby") == 1
    assert await room.get_id_by_name("lobby") == 1
    with pytest.raises(RoomNotFoundError):
        await room.get_id_by_name("Nonexistent")

@pytest.mark.asyncio
async def test_go_to_room_by_name_or_id(db, config, setup_rooms):
    room = Room(db, config, 1)
    await room.load()
    lobby = await room.go_to_room("Lobby")
    await lobby.load()
    assert lobby.room_id == 1
    room_1 = await room.go_to_room("1")
    await room_1.load()
    assert room_1.room_id == 1
    room_1_int = await room.go_to_room(1)
    await room_1_int.load() == 1

    with pytest.raises(RoomNotFoundError):
        await room.go_to_room("NoSuchRoom")

