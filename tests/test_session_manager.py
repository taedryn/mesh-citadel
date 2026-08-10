import asyncio
import pytest
from datetime import datetime, timedelta, UTC
from citadel.room.room import SystemRoomIDs
from citadel.session.manager import SessionManager
from citadel.session.state import WorkflowState


class MockConfig:
    def __init__(self, timeout=3600):
        self.auth = {"session_timeout": timeout}


@pytest.fixture
def session_mgr():
    config = MockConfig(timeout=10)  # short timeout for testing
    # SessionManager.__init__ only stores db; session CRUD never touches it.
    return SessionManager(config, db=None)


def test_create_session_returns_provisional_state(session_mgr):
    # create_session is synchronous and doesn't validate against the DB --
    # it just provisions a session tied to a mesh node, with no username
    # until the login workflow binds one via mark_username().
    session_id = session_mgr.create_session("node-alice")
    assert isinstance(session_id, str)
    state = session_mgr.get_session_state(session_id)
    assert state.node_id == "node-alice"
    assert state.username is None
    assert state.logged_in is False


def test_create_session_without_node_id(session_mgr):
    session_id = session_mgr.create_session()
    assert isinstance(session_id, str)
    state = session_mgr.get_session_state(session_id)
    assert state.node_id is None


def test_touch_session_extends_activity(session_mgr):
    session_id = session_mgr.create_session("node-bob")
    assert session_mgr.touch_session(session_id) is True
    state = session_mgr.get_session_state(session_id)
    assert state.node_id == "node-bob"


def test_touch_session_invalid_session_id(session_mgr):
    assert session_mgr.touch_session("invalid-session_id") is False


@pytest.mark.asyncio
async def test_expire_session_manually(session_mgr):
    session_id = session_mgr.create_session("node-alice")
    assert await session_mgr.expire_session(session_id) is True
    state = session_mgr.get_session_state(session_id)
    assert state is None


@pytest.mark.asyncio
async def test_expire_session_nonexistent_session_id(session_mgr):
    assert await session_mgr.expire_session("invalid-session_id") is False


def test_get_session_state_returns_none_even_if_stale(session_mgr):
    # get_session_state() doesn't itself check expiry -- only is_expired()
    # and the sweeper do -- so a stale-but-not-yet-swept session should
    # still be returned by a direct lookup.
    session_id = session_mgr.create_session("node-bob")
    with session_mgr.lock:
        state, _ = session_mgr.sessions[session_id]
        session_mgr.sessions[session_id] = (
            state,
            datetime.now(UTC) - timedelta(seconds=999)
        )
    state = session_mgr.get_session_state(session_id)
    assert state.node_id == "node-bob"
    assert session_mgr.is_expired(session_id) is True


def test_get_session_state_invalid_session_id(session_mgr):
    assert session_mgr.get_session_state("invalid-session_id") is None


def test_is_expired_unregistered_session(session_mgr):
    assert session_mgr.is_expired("invalid-session_id") is True


def test_current_room_helpers(session_mgr):
    session_id = session_mgr.create_session("node-alice")

    # New sessions default to the Lobby.
    room = session_mgr.get_current_room(session_id)
    assert room == SystemRoomIDs.LOBBY_ID

    # Change room and verify.
    session_mgr.set_current_room(session_id, "TechTalk")
    assert session_mgr.get_current_room(session_id) == "TechTalk"

    # Invalid session_id should return None and not raise.
    assert session_mgr.get_current_room("invalid") is None
    session_mgr.set_current_room("invalid", "Nowhere")  # should be a no-op


def test_workflow_state_lifecycle(session_mgr):
    session_id = session_mgr.create_session("node-bob")

    # Initially no workflow.
    assert session_mgr.get_workflow(session_id) is None

    # Set a workflow.
    wf = WorkflowState(kind="validate_users", step=1,
                       data={"pending": ["alice"]})
    session_mgr.set_workflow(session_id, wf)
    got = session_mgr.get_workflow(session_id)
    assert got.kind == "validate_users"
    assert got.step == 1
    assert got.data["pending"] == ["alice"]

    # Clear workflow.
    session_mgr.clear_workflow(session_id)
    assert session_mgr.get_workflow(session_id) is None

    # Invalid session_id should be safe.
    assert session_mgr.get_workflow("invalid") is None
    session_mgr.set_workflow("invalid", wf)  # should be a no-op
    session_mgr.clear_workflow("invalid")    # should be a no-op


def test_mark_username_and_login_state(session_mgr):
    session_id = session_mgr.create_session("node-alice")
    session_mgr.mark_username(session_id, "alice")
    state = session_mgr.get_session_state(session_id)
    assert state.username == "alice"


@pytest.mark.asyncio
async def test_mark_logged_in_without_node_id():
    # mark_logged_in(False) with a node_id triggers a node-auth cache
    # eviction path that constructs a throwaway MeshCoreTransportEngine --
    # skip that entirely by not setting a node_id, which is enough to
    # cover the logged_in flag flip itself.
    config = MockConfig()
    mgr = SessionManager(config, db=None)
    session_id = mgr.create_session()
    await mgr.mark_logged_in(session_id, True)
    assert mgr.is_logged_in(session_id) is True
    await mgr.mark_logged_in(session_id, False)
    assert mgr.is_logged_in(session_id) is False


def test_is_logged_in_invalid_session_id(session_mgr):
    assert session_mgr.is_logged_in("invalid-session_id") is False
