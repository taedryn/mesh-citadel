import pytest
from datetime import datetime, timedelta
from session.manager import SessionManager
from freezegun import freeze_time
import threading

class MockConfig:
    def __init__(self, timeout=10):
        self.auth = {"session_timeout": timeout}

class MockDB:
    def __init__(self, existing_usernames=None, fail=False):
        self.existing_usernames = existing_usernames or {"alice", "bob"}
        self.fail = fail

    def execute(self, query, params):
        if self.fail:
            raise RuntimeError("Simulated DB failure")
        username = params[0]
        if username in self.existing_usernames:
            return [(1,)]
        return []

@pytest.fixture
def session_mgr():
    config = MockConfig(timeout=10)
    db = MockDB()
    mgr = SessionManager(config, db)
    return mgr

def test_sweeper_expires_stale_sessions(session_mgr):
    with freeze_time("2025-09-17 00:00:00") as frozen:
        token = session_mgr.create_session("alice")
        assert session_mgr.validate_session(token) == "alice"

        # Advance time past timeout
        frozen.move_to("2025-09-17 00:00:11")
        session_mgr.sweep_expired_sessions()  # Direct call

        assert session_mgr.validate_session(token) is None

def test_sweeper_preserves_active_sessions(session_mgr):
    with freeze_time("2025-09-17 00:00:00") as frozen:
        token = session_mgr.create_session("bob")
        assert session_mgr.validate_session(token) == "bob"

        # Advance time just before timeout
        frozen.move_to("2025-09-17 00:00:09")
        session_mgr._start_sweeper()
        threading.Event().wait(0.1)

        # Should still be valid
        assert session_mgr.validate_session(token) == "bob"

