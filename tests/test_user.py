import pytest
import pytest_asyncio
import tempfile
import os
from datetime import datetime, UTC

from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.user.user import User


class DummyConfig:
    def __init__(self, path):
        self.database = {'db_path': path}
        self.logging = {
            'log_file_path': '/tmp/citadel.log', 'log_level': 'DEBUG'}
        self.bbs = {
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
    await db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission_level) VALUES (?, ?, ?, ?, ?, ?)",
                         ("alice", "hash1", b"salt1", "Alice", "2025-09-17T00:00:00Z", 2))
    await db_mgr.execute("INSERT INTO users (username, password_hash, salt, display_name, last_login, permission_level) VALUES (?, ?, ?, ?, ?, ?)",
                         ("bob", "hash2", b"salt2", "Bob", "2025-09-17T00:00:00Z", 2))

    yield db_mgr

    await db_mgr.shutdown()
    os.unlink(temp_db.name)

# -------------------------------
# ✅ Core User Tests
# -------------------------------


@pytest.mark.asyncio
async def test_user_loads_correctly(db):
    user = User(db, "alice")
    await user.load()
    assert user.display_name == "Alice"
    assert user.permission_level.value == 2
    assert user.last_login == "2025-09-17T00:00:00Z"


@pytest.mark.asyncio
async def test_display_name_update(db):
    user = User(db, "alice")
    await user.load()
    await user.set_display_name("Alicia")
    reloaded = User(db, "alice")
    await reloaded.load()
    assert reloaded.display_name == "Alicia"


@pytest.mark.asyncio
async def test_permission_update(db):
    user = User(db, "alice")
    await user.load()
    from citadel.auth.permissions import PermissionLevel
    await user.set_permission_level(PermissionLevel.AIDE)
    reloaded = User(db, "alice")
    await reloaded.load()
    assert reloaded.permission_level == PermissionLevel.AIDE


@pytest.mark.asyncio
async def test_last_login_update(db):
    user = User(db, "alice")
    await user.load()
    now = datetime(2025, 9, 17, 21, 0, tzinfo=UTC)
    await user.set_last_login(now)
    reloaded = User(db, "alice")
    await reloaded.load()
    assert reloaded.last_login == now.isoformat()


@pytest.mark.asyncio
async def test_password_update(db):
    user = User(db, "alice")
    await user.load()
    await user.update_password("newhash", b"newsalt")
    reloaded = User(db, "alice")
    await reloaded.load()
    assert reloaded.password_hash == "newhash"
    assert reloaded.salt == b"newsalt"

# -------------------------------
# ✅ Blocking Tests
# -------------------------------


@pytest.mark.asyncio
async def test_block_and_unblock_user(db):
    alice = User(db, "alice")
    await alice.load()
    bob = User(db, "bob")
    await bob.load()

    assert not await alice.is_blocked("bob")
    await alice.block_user("bob")
    assert await alice.is_blocked("bob")
    await alice.unblock_user("bob")
    assert not await alice.is_blocked("bob")


@pytest.mark.asyncio
async def test_blocking_persists_across_sessions(db):
    alice = User(db, "alice")
    await alice.load()
    await alice.block_user("bob")
    reloaded = User(db, "alice")
    await reloaded.load()
    assert await reloaded.is_blocked("bob")


@pytest.mark.asyncio
async def test_unblock_nonexistent_user_does_not_error(db):
    alice = User(db, "alice")
    await alice.load()
    await alice.unblock_user("charlie")  # Should not raise
