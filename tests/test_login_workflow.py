import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.workflows.login import LoginWorkflow
from citadel.session.state import WorkflowState
from citadel.workflows.types import WorkflowResponse
from citadel.commands.responses import CommandResponse


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
    assert isinstance(response, CommandResponse)
    assert response.text == "Enter your username:"
    assert response.code == "prompt_username"

    # Step 2: provide username
    wf_state = WorkflowState(kind="login", step=2, data={})
    command.text = "bob"
    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert response.text == "Enter your password:"
    assert response.code == "prompt_password"

    # Step 3: provide password
    wf_state = WorkflowState(kind="login", step=3, data={"username": "bob"})
    command.text = "correct-password"
    mock_user = MagicMock()
    mock_user.username = "bob"
    mock_processor.auth.authenticate.return_value = mock_user

    response = await workflow.handle(mock_processor, session_id, None, command, wf_state)
    assert response.success is True
    assert response.code == "login_success"
    assert "Welcome, bob" in response.text

    # Ensure session was marked
    mock_processor.sessions.mark_username.assert_called_with(session_id, "bob")
    mock_processor.sessions.mark_logged_in.assert_called_with(session_id)
    mock_processor.sessions.clear_workflow.assert_called_with(session_id)

