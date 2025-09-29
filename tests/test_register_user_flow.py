import pytest
from unittest.mock import AsyncMock, MagicMock

from citadel.workflows.register_user import RegisterUserWorkflow
from citadel.workflows.types import WorkflowResponse
from citadel.commands.responses import CommandResponse
from citadel.user.user import UserStatus


@pytest.fixture
def mock_db():
    async def execute(query, params):
        if query.strip().lower().startswith("select"):
            if "FROM users WHERE username = ?" in query:
                return []  # Simulate username not taken
            return []
        return None  # Simulate insert/update
    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


@pytest.fixture
def mock_config():
    return {
        "bbs": {
            "registration": {
                "terms_required": True,
                "terms": "To register with this system, you must agree to the following conditions:\n1. Be kind.\n2. No illegal content."
            }
        }
    }


@pytest.fixture
def mock_sessions():
    mgr = MagicMock()
    mgr.create_session = AsyncMock(return_value="session123")
    mgr.set_workflow = MagicMock()
    mgr.clear_workflow = MagicMock()
    return mgr


@pytest.fixture
def processor(mock_config, mock_db, mock_sessions):
    class MockProcessor:
        config = mock_config
        db = mock_db
        sessions = mock_sessions
    return MockProcessor()


@pytest.fixture
def workflow():
    return RegisterUserWorkflow()


@pytest.mark.asyncio
async def test_full_registration_flow(processor, workflow):
    wf_state = {"step": 1, "data": {}}
    session_id = "anon-session"

    # Step 1: Username
    response = WorkflowResponse(workflow="register_user", step=1, response="newuser")
    result = await workflow.handle(processor, session_id, None, response, wf_state)
    assert isinstance(result, CommandResponse)
    assert result.code == "workflow_prompt"
    assert wf_state["step"] == 2
    assert wf_state["data"]["username"] == "newuser"
    assert wf_state["data"]["provisional_session_id"] == "session123"

    # Step 2: Display Name
    response = WorkflowResponse(workflow="register_user", step=2, response="Alice")
    result = await workflow.handle(processor, "session123", None, response, wf_state)
    assert result.code == "workflow_prompt"
    assert wf_state["step"] == 3
    assert wf_state["data"]["display_name"] == "Alice"

    # Step 3: Password
    response = WorkflowResponse(workflow="register_user", step=3, response="securepass")
    result = await workflow.handle(processor, "session123", None, response, wf_state)
    assert result.code == "workflow_prompt"
    assert wf_state["step"] == 4

    # Step 4: Terms Agreement
    response = WorkflowResponse(workflow="register_user", step=4, response="yes")
    result = await workflow.handle(processor, "session123", None, response, wf_state)
    assert result.code == "workflow_prompt"
    assert wf_state["step"] == 5
    assert wf_state["data"]["agreed"] is True

    # Step 5: Intro
    response = WorkflowResponse(workflow="register_user", step=5, response="I'm excited to join!")
    result = await workflow.handle(processor, "session123", None, response, wf_state)
    assert result.code == "workflow_prompt"
    assert wf_state["step"] == 6
    assert wf_state["data"]["intro"] == "I'm excited to join!"

    # Step 6: Finalize
    response = WorkflowResponse(workflow="register_user", step=6, response="yes")
    result = await workflow.handle(processor, "session123", None, response, wf_state)
    assert result.code == "registration_submitted"
    processor.sessions.clear_workflow.assert_called_once_with("session123")

