import pytest
from datetime import datetime, timedelta
from citadel.session.manager import SessionManager
from freezegun import freeze_time
import threading


class MockConfig:
    def __init__(self, timeout=10):
        self.auth = {"session_timeout": timeout}


@pytest.fixture
def session_mgr():
    config = MockConfig(timeout=10)
    # session CRUD never touches db, so a stub is fine here.
    mgr = SessionManager(config, db=None)
    return mgr


def test_sweeper_expires_stale_sessions(session_mgr):
    with freeze_time("2025-09-17 00:00:00") as frozen:
        session_id = session_mgr.create_session("node-alice")
        state = session_mgr.get_session_state(session_id)
        assert state.node_id == "node-alice"

        # Advance time past timeout
        frozen.move_to("2025-09-17 00:00:11")
        session_mgr.sweep_expired_sessions()  # Direct call

        assert session_mgr.get_session_state(session_id) is None


def test_sweeper_preserves_active_sessions(session_mgr):
    with freeze_time("2025-09-17 00:00:00") as frozen:
        session_id = session_mgr.create_session("node-bob")
        state = session_mgr.get_session_state(session_id)
        assert state.node_id == "node-bob"

        # Advance time just before timeout
        frozen.move_to("2025-09-17 00:00:09")
        session_mgr.sweep_expired_sessions()  # Direct call

        # Should still be valid
        state = session_mgr.get_session_state(session_id)
        assert state.node_id == "node-bob"
