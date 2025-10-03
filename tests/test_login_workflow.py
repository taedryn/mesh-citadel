import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.workflows.login import LoginWorkflow
from citadel.session.state import WorkflowState
from citadel.transport.packets import ToUser


@pytest.fixture
def mock_processor(monkeypatch):
    # Mock the auth handler
    mock_auth = MagicMock()
    mock_auth.authenticate = AsyncMock()

    # Mock the session manager
    mock_sessions = MagicMock()
    mock_sessions.mark_username = MagicMock()
    mock_sessions.mark_logged_in = MagicMock()
    mock_sessions.clear_workflow = MagicMock()
    mock_sessions.set_workflow = MagicMock()

    # Attach to processor
    processor = MagicMock()
    processor.auth = mock_auth
    processor.sessions = mock_sessions
    processor.db = AsyncMock()
    return processor


@pytest.mark.asyncio
async def test_login_workflow_happy_path(mock_processor):
    workflow = LoginWorkflow()
    session_id = "session123"
    wf_state = WorkflowState(kind="login", step=1, data={})

    # Step 1: prompt for username
    command = MagicMock()
    command.name = None
    command.text = ""
    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert isinstance(response, ToUser)
    assert not response.is_error
    assert not response.is_error
    assert response.text == "Enter your username:"
    assert 'type' in response.hints and response.hints['type'] == 'text'

    # Step 2: provide username
    wf_state = WorkflowState(kind="login", step=2, data={})
    command.text = "bob"
    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert not response.is_error
    assert response.text == "Enter your password:"
    assert 'type' in response.hints and response.hints['type'] == 'password'

    # Step 3: provide password
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob"})
    command.text = "correct-password"
    mock_user = MagicMock()
    mock_user.username = "bob"
    mock_processor.auth.authenticate.return_value = mock_user

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert not response.is_error
    assert "Welcome, bob" in response.text

    # Ensure session was marked
    mock_processor.sessions.mark_username.assert_called_with(session_id, "bob")
    mock_processor.sessions.mark_logged_in.assert_called_with(session_id)
    mock_processor.sessions.clear_workflow.assert_called_with(session_id)

