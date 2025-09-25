import asyncio
import pytest
from datetime import datetime, timedelta, UTC
from citadel.session.manager import SessionManager
from citadel.session.state import WorkflowState


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


@pytest.mark.asyncio
async def test_create_and_validate_session(session_mgr):
    token = await session_mgr.create_session("alice")
    assert isinstance(token, str)
    state = session_mgr.validate_session(token)
    assert state.username == "alice"


@pytest.mark.asyncio
async def test_touch_session_extends_activity(session_mgr):
    token = await session_mgr.create_session("bob")
    assert session_mgr.touch_session(token) is True
    state = session_mgr.validate_session(token)
    assert state.username == "bob"


@pytest.mark.asyncio
async def test_expire_session_manually(session_mgr):
    token = await session_mgr.create_session("alice")
    assert session_mgr.expire_session(token) is True
    state = session_mgr.validate_session(token)
    assert state is None


@pytest.mark.asyncio
async def test_validate_returns_username_even_if_stale(session_mgr):
    token = await session_mgr.create_session("bob")
    # Simulate staleness
    with session_mgr.lock:
        username, _ = session_mgr.sessions[token]
        session_mgr.sessions[token] = (
            username,
            datetime.now(UTC) - timedelta(seconds=999)
        )
    # Should still return username until sweeper runs
    state = session_mgr.validate_session(token)
    assert state.username == "bob"


@pytest.mark.asyncio
async def test_create_session_invalid_username(session_mgr):
    with pytest.raises(ValueError):
        await session_mgr.create_session("charlie")  # not in mock DB


@pytest.mark.asyncio
async def test_db_failure_during_user_check():
    config = MockConfig()
    db = MockDB(fail=True)
    mgr = SessionManager(config, db)
    with pytest.raises(ValueError):
        await mgr.create_session("alice")


@pytest.mark.asyncio
async def test_expire_session_nonexistent_token(session_mgr):
    assert session_mgr.expire_session("invalid-token") is False


@pytest.mark.asyncio
async def test_touch_session_invalid_token(session_mgr):
    assert session_mgr.touch_session("invalid-token") is False


@pytest.mark.asyncio
async def test_validate_session_invalid_token(session_mgr):
    state = session_mgr.validate_session("invalid-token")
    assert state is None


@pytest.mark.asyncio
async def test_current_room_helpers(session_mgr):
    token = await session_mgr.create_session("alice")

    # Default should be Lobby (or None, depending on your SessionState default)
    room = session_mgr.get_current_room(token)
    assert room in (None, "Lobby")

    # Change room and verify
    session_mgr.set_current_room(token, "TechTalk")
    assert session_mgr.get_current_room(token) == "TechTalk"

    # Invalid token should return None and not raise
    assert session_mgr.get_current_room("invalid") is None
    session_mgr.set_current_room("invalid", "Nowhere")  # should be a no-op


@pytest.mark.asyncio
async def test_workflow_state_lifecycle(session_mgr):
    token = await session_mgr.create_session("bob")

    # Initially no workflow
    assert session_mgr.get_workflow(token) is None

    # Set a workflow
    wf = WorkflowState(kind="validate_users", step=1,
                       data={"pending": ["alice"]})
    session_mgr.set_workflow(token, wf)
    got = session_mgr.get_workflow(token)
    assert got.kind == "validate_users"
    assert got.step == 1
    assert got.data["pending"] == ["alice"]

    # Clear workflow
    session_mgr.clear_workflow(token)
    assert session_mgr.get_workflow(token) is None

    # Invalid token should be safe
    assert session_mgr.get_workflow("invalid") is None
    session_mgr.set_workflow("invalid", wf)  # should be a no-op
    session_mgr.clear_workflow("invalid")    # should be a no-op
