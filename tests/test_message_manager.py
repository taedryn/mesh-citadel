import pytest
import tempfile
import os
from datetime import datetime, UTC

from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.user.user import User
from citadel.message.manager import MessageManager
from citadel.message.errors import InvalidContentError, InvalidRecipientError

class DummyConfig:
    def __init__(self, path):
        self.database = {'db_path': path}
        self.logging = {'log_file_path': '/tmp/citadel.log', 'log_level': 'DEBUG'}
        self.bbs = {'max_messages_per_room': 100}  # For reference only

@pytest.fixture(scope="function")
def db():
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = DummyConfig(temp_db.name)
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    initialize_database(db_mgr)

    # Insert test users
    db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission) VALUES (?, ?, ?, ?, ?, ?)",
                   ("alice", "hash", b"salt", "Alice", "2025-09-17T00:00:00Z", "user"))
    db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission) VALUES (?, ?, ?, ?, ?, ?)",
                   ("bob", "hash", b"salt", "Bob", "2025-09-17T00:00:00Z", "user"))

    yield db_mgr

    db_mgr.shutdown()
    os.unlink(temp_db.name)

@pytest.fixture
def msg_mgr(db):
    config = DummyConfig("unused.db")
    return MessageManager(config, db)

# -------------------------------
# ✅ Core MessageManager Tests
# -------------------------------

def test_post_and_get_message(msg_mgr, db):
    msg_id = msg_mgr.post_message("alice", "Hello world!")
    user = User(db, "bob")
    msg = msg_mgr.get_message(msg_id, recipient_user=user)

    assert msg["id"] == msg_id
    assert msg["sender"] == "alice"
    assert msg["content"] == "Hello world!"
    assert msg["display_name"] == "Alice"
    assert msg["blocked"] is False

def test_blocked_message(msg_mgr, db):
    msg_id = msg_mgr.post_message("alice", "Secret message")
    bob = User(db, "bob")
    bob.block_user("alice")

    msg = msg_mgr.get_message(msg_id, recipient_user=bob)
    assert msg["blocked"] is True

def test_delete_message(msg_mgr, db):
    msg_id = msg_mgr.post_message("alice", "Temporary message")
    assert msg_mgr.delete_message(msg_id) is True
    assert msg_mgr.get_message(msg_id) is None

def test_get_messages_batch(msg_mgr, db):
    ids = [
        msg_mgr.post_message("alice", f"Message {i}")
        for i in range(3)
    ]
    user = User(db, "bob")
    messages = msg_mgr.get_messages(ids, recipient_user=user)

    assert len(messages) == 3
    assert all(msg["sender"] == "alice" for msg in messages)
    assert all("display_name" in msg for msg in messages)
    assert all(msg["blocked"] is False for msg in messages)

def test_message_summary_respects_packet_limit(msg_mgr, db):
    long_text = "X" * 500
    msg_id = msg_mgr.post_message("alice", long_text)
    summary = msg_mgr.get_message_summary(msg_id)

    display_name = "Alice"
    timestamp_len = len(datetime.now(UTC).isoformat())
    reserved = len(display_name) + timestamp_len
    assert len(summary) <= 184 - reserved

def test_post_message_with_empty_content(msg_mgr):
    with pytest.raises(InvalidContentError):
        msg_mgr.post_message("alice", "")

def test_post_message_with_none_content(msg_mgr):
    with pytest.raises(InvalidContentError):
        msg_mgr.post_message("alice", None)

def test_post_private_message_to_unknown_recipient(msg_mgr):
    with pytest.raises(InvalidRecipientError):
        msg_mgr.post_message("alice", "Hi there", recipient="charlie")

