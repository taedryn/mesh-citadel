import os
import pytest
import pytest_asyncio
import tempfile

from citadel.auth.permissions import PermissionLevel
from citadel.room.room import Room, SystemRoomIDs
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


@pytest_asyncio.fixture
async def setup_rooms(db):
    # System rooms (1-5) are automatically created by initialize_database
    # Update room 2 name for the tests that expect "Tech" room
    await db.execute("UPDATE rooms SET name = 'Tech', description = 'Tech talk' WHERE id = 2")


@pytest_asyncio.fixture
async def setup_users(db):
    await db.execute("INSERT INTO users (username, permission_level, password_hash, salt) VALUES ('twit', 1, 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission_level, password_hash, salt) VALUES ('user', 2, 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission_level, password_hash, salt) VALUES ('aide', 3, 'hash', 'salt')")
    await db.execute("INSERT INTO users (username, permission_level, password_hash, salt) VALUES ('sysop', 4, 'hash', 'salt')")


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
    # Create a non-system room to delete (ID 100)
    await db.execute("INSERT INTO rooms (id, name, description, permission_level, prev_neighbor, next_neighbor) VALUES (100, 'Test Room', 'Room for deletion test', 2, NULL, NULL)")

    # Delete the test room - it should log to System room (ID 5)
    test_room = Room(db, config, 100)
    await test_room.load()
    await test_room.delete_room("sysop")

    # Check that deletion was logged to System room (ID 5)
    messages = await db.execute("""
        SELECT m.content
        FROM room_messages rm
        JOIN messages m ON rm.message_id = m.id
        WHERE rm.room_id = ?
    """, (SystemRoomIDs.SYSTEM_ID,))

    assert any("Room 'Test Room' was deleted." in msg[0] for msg in messages)


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


@pytest.mark.asyncio
async def test_system_rooms_initialization(db, config, setup_rooms, setup_users):
    """Test that all system rooms are properly initialized."""
    # Check that all system rooms exist with correct IDs
    for room_id in Room.SYSTEM_ROOM_IDS:
        result = await db.execute('SELECT id, name, prev_neighbor, next_neighbor FROM rooms WHERE id = ?', (room_id,))
        assert result, f"System room {room_id} should exist"
        room_data = result[0]
        assert room_data[0] == room_id, f"Room should have ID {room_id}"

    # Check room chain structure is correct
    lobby = await db.execute('SELECT prev_neighbor, next_neighbor FROM rooms WHERE id = ?', (SystemRoomIDs.LOBBY_ID,))
    assert lobby[0][0] is None, "Lobby should be first room (prev_neighbor = NULL)"
    assert lobby[0][1] == SystemRoomIDs.MAIL_ID, "Lobby should link to Mail room"

    twit = await db.execute('SELECT prev_neighbor, next_neighbor FROM rooms WHERE id = ?', (SystemRoomIDs.TWIT_ID,))
    assert twit[0][0] == SystemRoomIDs.SYSTEM_ID, "Twit room should link back to System room"
    assert twit[0][1] is None, "Twit should be last room (next_neighbor = NULL)"


@pytest.mark.asyncio
async def test_system_rooms_cannot_be_deleted(db, config, setup_rooms, setup_users):
    """Test that system rooms are protected from deletion."""
    # Try to delete each system room - should fail
    for room_id in Room.SYSTEM_ROOM_IDS:
        room = Room(db, config, room_id)
        await room.load()

        with pytest.raises(PermissionDeniedError):
            await room.delete_room("sysop")


@pytest.mark.asyncio
async def test_user_room_id_constraint(db, config, setup_rooms, setup_users):
    """Test that user-created rooms get IDs >= 100."""
    # Create first user room
    room_id1 = await Room.create(db, config, 'Test Room 1',
                                 'First test room', False, PermissionLevel.USER, SystemRoomIDs.SYSTEM_ID, None)

    # Create second user room
    room_id2 = await Room.create(db, config, 'Test Room 2',
                                 'Second test room', False, PermissionLevel.USER, room_id1, None)

    # Verify both rooms get IDs >= MIN_USER_ROOM_ID (100)
    assert room_id1 >= Room.MIN_USER_ROOM_ID, f"First room ID {room_id1} should be >= {Room.MIN_USER_ROOM_ID}"
    assert room_id2 >= Room.MIN_USER_ROOM_ID, f"Second room ID {room_id2} should be >= {Room.MIN_USER_ROOM_ID}"

    # Verify sequential assignment
    assert room_id2 > room_id1, f"Second room ID {room_id2} should be greater than first {room_id1}"

    # Verify rooms were actually created with correct IDs
    result1 = await db.execute("SELECT id, name FROM rooms WHERE id = ?", (room_id1,))
    assert result1[0][0] == room_id1 and result1[0][1] == 'Test Room 1'

    result2 = await db.execute("SELECT id, name FROM rooms WHERE id = ?", (room_id2,))
    assert result2[0][0] == room_id2 and result2[0][1] == 'Test Room 2'
