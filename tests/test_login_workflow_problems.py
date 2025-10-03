import pytest
from unittest.mock import AsyncMock, MagicMock

from citadel.workflows.login import LoginWorkflow
from citadel.session.state import WorkflowState
from citadel.user.user import User
from citadel.transport.packets import FromUser, FromUserType, ToUser


@pytest.fixture
def mock_processor(monkeypatch):
    # Mock login handler
    mock_auth = MagicMock()
    mock_auth.authenticate = AsyncMock()

    # Mock session manager
    mock_sessions = MagicMock()
    mock_sessions.mark_username = MagicMock()
    mock_sessions.mark_logged_in = MagicMock()
    mock_sessions.clear_workflow = MagicMock()
    mock_sessions.set_workflow = MagicMock()

    # Assemble processor
    processor = MagicMock()
    processor.auth = mock_auth
    processor.sessions = mock_sessions
    processor.db = MagicMock()
    return processor


@pytest.mark.asyncio
async def test_unknown_user_triggers_retry(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=2, data={})
    command = MagicMock()
    command.text = "ghost"

    User.username_exists = AsyncMock(return_value=False)

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert "not found" in response.text


@pytest.mark.asyncio
async def test_new_user_triggers_registration(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=2, data={})
    command = MagicMock()
    command.text = "new"

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert "to register as a new user" in response.text


@pytest.mark.asyncio
async def test_failed_password_triggers_retry(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob"})
    command = MagicMock()
    command.text = "wrong-password"

    mock_processor.auth.authenticate.return_value = None

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert "Login failed" in response.text


@pytest.mark.asyncio
async def test_login_blocked_after_three_attempts(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob", "attempts": 2})
    command = MagicMock()
    command.text = "still-wrong"

    mock_processor.auth.authenticate.return_value = None

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert response.is_error
    assert response.error_code == "login_blocked"
    assert "Too many failed login attempts" in response.text


@pytest.mark.asyncio
async def test_invalid_step_returns_error(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=99, data={})
    command = MagicMock()
    command.text = "anything"

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert response.is_error
    assert response.error_code == "invalid_login_step"

