import asyncio
import pytest
from datetime import datetime, timedelta, UTC
from session.manager import SessionManager

class MockConfig:
    def __init__(self, timeout=3600):
        self.auth = {"session_timeout": timeout}

class MockDB:
    def __init__(self, existing_usernames=None, fail=False):
        self.existing_usernames = existing_usernames or {"alice", "bob"}
        self.fail = fail

    async def execute(self, query, params):
        if self.fail:
            raise RuntimeError("Simulated DB failure")
        username = params[0]
        if username in self.existing_usernames:
            return [(1,)]
        return []

@pytest.fixture
def session_mgr():
    config = MockConfig(timeout=10)  # short timeout for testing
    db = MockDB()
    return SessionManager(config, db)

def test_create_and_validate_session(session_mgr):
    token = session_mgr.create_session("alice")
    assert isinstance(token, str)
    assert session_mgr.validate_session(token) == "alice"

def test_touch_session_extends_activity(session_mgr):
    token = session_mgr.create_session("bob")
    assert session_mgr.touch_session(token) is True
    assert session_mgr.validate_session(token) == "bob"

def test_expire_session_manually(session_mgr):
    token = session_mgr.create_session("alice")
    assert session_mgr.expire_session(token) is True
    assert session_mgr.validate_session(token) is None

def test_validate_returns_username_even_if_stale(session_mgr):
    token = session_mgr.create_session("bob")
    # Simulate staleness
    with session_mgr.lock:
        username, _ = session_mgr.sessions[token]
        session_mgr.sessions[token] = (
                username,
                datetime.now(UTC) - timedelta(seconds=999)
        )
    # Should still return username until sweeper runs
    assert session_mgr.validate_session(token) == "bob"

def test_create_session_invalid_username(session_mgr):
    with pytest.raises(ValueError):
        session_mgr.create_session("charlie")  # not in mock DB

def test_db_failure_during_user_check():
    config = MockConfig()
    db = MockDB(fail=True)
    mgr = SessionManager(config, db)
    with pytest.raises(ValueError):
        mgr.create_session("alice")

def test_expire_session_nonexistent_token(session_mgr):
    assert session_mgr.expire_session("invalid-token") is False

def test_touch_session_invalid_token(session_mgr):
    assert session_mgr.touch_session("invalid-token") is False

def test_validate_session_invalid_token(session_mgr):
    assert session_mgr.validate_session("invalid-token") is None

