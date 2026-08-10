import pytest
from unittest.mock import AsyncMock, MagicMock

from citadel.room.room import SystemRoomIDs
from citadel.session.state import SessionState
from citadel.workflows.login import LoginWorkflow
from citadel.workflows.base import WorkflowContext, WorkflowState
from citadel.user.user import User
from citadel.transport.packets import ToUser


@pytest.fixture
def mock_sessions():
    sessions = MagicMock()
    sessions.mark_username = MagicMock()
    sessions.mark_logged_in = AsyncMock()
    sessions.clear_workflow = MagicMock()
    sessions.set_workflow = MagicMock()
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
async def test_unknown_user_triggers_retry(mock_sessions, monkeypatch):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=2, data={})
    context = make_context(session_id, wf_state, mock_sessions)

    monkeypatch.setattr(
        "citadel.workflows.login.User.username_exists",
        AsyncMock(return_value=None),
    )

    response = await workflow.handle(context, "ghost")
    assert isinstance(response, ToUser)
    assert "not found" in response.text


@pytest.mark.asyncio
async def test_new_user_triggers_registration(mock_sessions, monkeypatch):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=2, data={})
    context = make_context(session_id, wf_state, mock_sessions)

    # Registering isn't what's under test here -- just confirm login
    # correctly hands off to the register_user workflow instead of
    # treating "new" as a literal username.
    fake_register_response = ToUser(session_id=session_id, text="Register: enter a username")
    fake_register_workflow = MagicMock()
    fake_register_workflow.start = AsyncMock(return_value=fake_register_response)
    monkeypatch.setattr(
        "citadel.workflows.registry.get",
        lambda kind: fake_register_workflow if kind == "register_user" else None,
    )

    response = await workflow.handle(context, "new")
    assert response is fake_register_response
    mock_sessions.set_workflow.assert_called_with(
        session_id, WorkflowState(kind="register_user", step=1, data={})
    )


@pytest.mark.asyncio
async def test_failed_password_triggers_retry(mock_sessions, monkeypatch):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob"})
    context = make_context(session_id, wf_state, mock_sessions)

    monkeypatch.setattr(
        "citadel.workflows.login.authenticate",
        AsyncMock(return_value=None),
    )

    response = await workflow.handle(context, "wrong-password")
    assert isinstance(response, ToUser)
    assert "Login failed" in response.text


@pytest.mark.asyncio
async def test_login_blocked_after_three_attempts(mock_sessions, monkeypatch):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(
        kind="login", step=3, data={"username": "bob", "attempts": 2})
    context = make_context(session_id, wf_state, mock_sessions)

    monkeypatch.setattr(
        "citadel.workflows.login.authenticate",
        AsyncMock(return_value=None),
    )

    response = await workflow.handle(context, "still-wrong")
    assert isinstance(response, ToUser)
    assert response.is_error
    assert response.error_code == "login_blocked"
    assert "Too many failed login attempts" in response.text


@pytest.mark.asyncio
async def test_invalid_step_returns_error(mock_sessions):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=99, data={})
    context = make_context(session_id, wf_state, mock_sessions)

    response = await workflow.handle(context, "anything")
    assert isinstance(response, ToUser)
    assert response.is_error
    assert response.error_code == "invalid_login_step"
