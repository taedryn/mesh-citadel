import pytest
import tempfile
import os
from datetime import datetime, UTC

from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.user.user import User

class DummyConfig:
    def __init__(self, path):
        self.database = {'db_path': path}
        self.logging = {'log_file_path': '/tmp/citadel.log', 'log_level': 'DEBUG'}

@pytest.fixture(scope="function")
def db():
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = DummyConfig(temp_db.name)
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    initialize_database(db_mgr)

    # Insert test users
    await db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission) VALUES (?, ?, ?, ?, ?, ?)",
                   ("alice", "hash1", b"salt1", "Alice", "2025-09-17T00:00:00Z", "user"))
    await db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission) VALUES (?, ?, ?, ?, ?, ?)",
                   ("bob", "hash2", b"salt2", "Bob", "2025-09-17T00:00:00Z", "user"))

    yield db_mgr

    db_mgr.shutdown()
    os.unlink(temp_db.name)

# -------------------------------
# ✅ Core User Tests
# -------------------------------

def test_user_loads_correctly(db):
    user = User(db, "alice")
    assert user.display_name == "Alice"
    assert user.permission == "user"
    assert user.last_login == "2025-09-17T00:00:00Z"

def test_display_name_update(db):
    user = User(db, "alice")
    user.display_name = "Alicia"
    reloaded = User(db, "alice")
    assert reloaded.display_name == "Alicia"

def test_permission_update(db):
    user = User(db, "alice")
    user.permission = "aide"
    reloaded = User(db, "alice")
    assert reloaded.permission == "aide"

def test_last_login_update(db):
    user = User(db, "alice")
    now = datetime(2025, 9, 17, 21, 0, tzinfo=UTC)
    user.last_login = now
    reloaded = User(db, "alice")
    assert reloaded.last_login == now.isoformat()

def test_password_update(db):
    user = User(db, "alice")
    user.update_password("newhash", b"newsalt")
    reloaded = User(db, "alice")
    assert reloaded.password_hash == "newhash"
    assert reloaded.salt == b"newsalt"

# -------------------------------
# ✅ Blocking Tests
# -------------------------------

def test_block_and_unblock_user(db):
    alice = User(db, "alice")
    bob = User(db, "bob")

    assert not alice.is_blocked("bob")
    alice.block_user("bob")
    assert alice.is_blocked("bob")
    alice.unblock_user("bob")
    assert not alice.is_blocked("bob")

def test_blocking_persists_across_sessions(db):
    alice = User(db, "alice")
    alice.block_user("bob")
    reloaded = User(db, "alice")
    assert reloaded.is_blocked("bob")

def test_unblock_nonexistent_user_does_not_error(db):
    alice = User(db, "alice")
    alice.unblock_user("charlie")  # Should not raise

