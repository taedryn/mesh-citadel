import pytest
from unittest.mock import AsyncMock, MagicMock

from citadel.room.room import SystemRoomIDs
from citadel.session.state import SessionState
from citadel.workflows.login import LoginWorkflow
from citadel.workflows.base import WorkflowContext, WorkflowState
from citadel.transport.packets import ToUser


@pytest.fixture
def mock_sessions():
    sessions = MagicMock()
    sessions.mark_username = MagicMock()
    # mark_logged_in is async on the real SessionManager -- must be an
    # AsyncMock or `await`ing it inside LoginWorkflow raises a TypeError.
    sessions.mark_logged_in = AsyncMock()
    sessions.clear_workflow = MagicMock()
    sessions.set_workflow = MagicMock()
    # No physical mesh node attached to this session, so LoginWorkflow's
    # node-auth password-cache branch is a no-op.
    sessions.get_session_state = MagicMock(
        return_value=SessionState(
            username="bob", current_room=SystemRoomIDs.LOBBY_ID, node_id=None
        )
    )
    return sessions


def make_context(session_id, wf_state, sessions, db=None):
    return WorkflowContext(
        session_id=session_id,
        db=db or AsyncMock(),
        config=MagicMock(bbs={}),
        session_mgr=sessions,
        wf_state=wf_state,
    )


@pytest.mark.asyncio
async def test_login_workflow_happy_path(mock_sessions, monkeypatch):
    workflow = LoginWorkflow()
    session_id = "session123"

    # Step 1: prompt for username
    wf_state = WorkflowState(kind="login", step=1, data={})
    context = make_context(session_id, wf_state, mock_sessions)
    response = await workflow.handle(context, None)
    assert isinstance(response, ToUser)
    assert not response.is_error
    assert "Enter your username:" in response.text
    assert response.hints["type"] == "text"

    # Step 2: provide username
    wf_state = WorkflowState(kind="login", step=2, data={})
    context = make_context(session_id, wf_state, mock_sessions)
    monkeypatch.setattr(
        "citadel.workflows.login.User.username_exists",
        AsyncMock(return_value="bob"),
    )
    response = await workflow.handle(context, "bob")
    assert not response.is_error
    assert response.text == "2: Enter your password:"
    assert response.hints["type"] == "password"

    # Step 3: provide password
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob"})
    context = make_context(session_id, wf_state, mock_sessions)
    mock_user = MagicMock()
    mock_user.username = "bob"
    monkeypatch.setattr(
        "citadel.workflows.login.authenticate",
        AsyncMock(return_value=mock_user),
    )

    response = await workflow.handle(context, "correct-password")
    assert not response.is_error
    assert "Welcome, bob" in response.text

    # Ensure session was marked
    mock_sessions.mark_username.assert_called_with(session_id, "bob")
    mock_sessions.mark_logged_in.assert_called_with(session_id)
    mock_sessions.clear_workflow.assert_called_with(session_id)
