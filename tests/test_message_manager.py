import pytest
import pytest_asyncio
import tempfile
import os
from datetime import datetime, UTC

from citadel.auth.permissions import PermissionLevel
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.user.user import User
from citadel.message.manager import MessageManager
from citadel.message.errors import InvalidContentError, InvalidRecipientError


class DummyConfig:
    def __init__(self, path):
        self.database = {'db_path': path}
        self.logging = {
            'log_file_path': '/tmp/citadel.log', 'log_level': 'DEBUG'}
        self.bbs = {
            'max_messages_per_room': 100,  # For reference only
            'room_names': {
                'lobby': 'Lobby',
                'mail': 'Mail',
                'aides': 'Aides',
                'sysop': 'Sysop',
                'system': 'System'
            }
        }


@pytest_asyncio.fixture(scope="function")
async def db():
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = DummyConfig(temp_db.name)
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    # Insert test users
    await User.create(config, db_mgr, "alice", "hash", "salt", "Alice")
    alice = User(db_mgr, "alice")
    await alice.load()
    await alice.set_permission_level(PermissionLevel.USER)

    await User.create(config, db_mgr, "bob", "hash", "salt", "Bob")
    bob = User(db_mgr, "bob")
    await bob.load()
    await bob.set_permission_level(PermissionLevel.USER)

    yield db_mgr

    await db_mgr.shutdown()
    os.unlink(temp_db.name)


@pytest.fixture
def msg_mgr(db):
    config = DummyConfig("unused.db")
    return MessageManager(config, db)

# -------------------------------
# ✅ Core MessageManager Tests
# -------------------------------


@pytest.mark.asyncio
async def test_post_and_get_message(msg_mgr, db):
    msg_id = await msg_mgr.post_message("alice", "Hello world!")
    user = User(db, "bob")
    await user.load()
    msg = await msg_mgr.get_message(msg_id, recipient_user=user)

    assert msg["id"] == msg_id
    assert msg["sender"] == "alice"
    assert msg["content"] == "Hello world!"
    assert msg["display_name"] == "Alice"
    assert msg["blocked"] is False


@pytest.mark.asyncio
async def test_blocked_message(msg_mgr, db):
    msg_id = await msg_mgr.post_message("alice", "Secret message")
    bob = User(db, "bob")
    await bob.load()
    await bob.block_user("alice")

    msg = await msg_mgr.get_message(msg_id, recipient_user=bob)
    assert msg["blocked"] is True


@pytest.mark.asyncio
async def test_delete_message(msg_mgr, db):
    msg_id = await msg_mgr.post_message("alice", "Temporary message")
    del_result = await msg_mgr.delete_message(msg_id)
    assert del_result is True
    user = User(db, "bob")
    await user.load()
    # get_message() returns None before ever touching recipient_user for a
    # missing message, but the param is still required at the call site.
    get_result = await msg_mgr.get_message(msg_id, recipient_user=user)
    assert get_result is None


@pytest.mark.asyncio
async def test_get_messages_batch(msg_mgr, db):
    # There's no batch get_messages() method -- callers fetch one at a
    # time (see the read_messages() helper in commands/builtins.py).
    ids = [
        await msg_mgr.post_message("alice", f"Message {i}")
        for i in range(3)
    ]
    user = User(db, "bob")
    await user.load()
    messages = [await msg_mgr.get_message(mid, recipient_user=user) for mid in ids]

    assert len(messages) == 3
    assert all(msg["sender"] == "alice" for msg in messages)
    assert all("display_name" in msg for msg in messages)
    for msg in messages:
        assert msg["blocked"] is False


@pytest.mark.asyncio
async def test_message_summary_respects_packet_limit(msg_mgr, db):
    long_text = "X" * 500
    msg_id = await msg_mgr.post_message("alice", long_text)
    user = User(db, "bob")
    await user.load()
    # get_message_summary() truncates the combined header+content to
    # msg_len, so the result length is capped at msg_len directly.
    summary = await msg_mgr.get_message_summary(msg_id, recipient_user=user, msg_len=184)

    assert len(summary) <= 184


@pytest.mark.asyncio
async def test_post_message_with_empty_content(msg_mgr):
    with pytest.raises(InvalidContentError):
        await msg_mgr.post_message("alice", "")


@pytest.mark.asyncio
async def test_post_message_with_none_content(msg_mgr):
    with pytest.raises(InvalidContentError):
        await msg_mgr.post_message("alice", None)


@pytest.mark.asyncio
async def test_post_private_message_to_unknown_recipient(msg_mgr):
    with pytest.raises(InvalidRecipientError):
        await msg_mgr.post_message("alice", "Hi there", recipient="charlie")
