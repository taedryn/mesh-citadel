import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.auth.login_handler import LoginHandler
from citadel.commands.responses import CommandResponse, ErrorResponse


@pytest.fixture
def mock_user(monkeypatch):
    monkeypatch.setattr("citadel.user.user.User.username_exists", AsyncMock())
    monkeypatch.setattr("citadel.user.user.User.verify_password", AsyncMock())
    monkeypatch.setattr("citadel.user.user.User.create", AsyncMock())


@pytest.fixture
def login_handler(mock_user):
    config = {}
    db_mgr = MagicMock()
    session_mgr = MagicMock()
    session_mgr.create_session = AsyncMock(return_value="session123")
    session_mgr.set_workflow = MagicMock()
    return LoginHandler(config, db_mgr, session_mgr)


@pytest.mark.asyncio
async def test_successful_login(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = True
    User.verify_password.return_value = True

    result = await login_handler.handle_login(
        transport_info={},
        username_input="alice",
        password_input="correct-password"
    )

    assert isinstance(result, CommandResponse)
    assert result.success is True
    assert result.code == "login_success"
    assert result.payload["session_id"] == "session123"


@pytest.mark.asyncio
async def test_failed_password(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = True
    User.verify_password.return_value = False

    result = await login_handler.handle_login(
        transport_info={},
        username_input="alice",
        password_input="wrong-password"
    )

    assert isinstance(result, ErrorResponse)
    assert result.code == "auth_failed"
    assert "Incorrect password" in result.text


@pytest.mark.asyncio
async def test_unknown_user_triggers_registration(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = False

    result = await login_handler.handle_login(
        transport_info={"engine": "telnet", "metadata": {"ip": "1.2.3.4"}},
        username_input="newuser",
        password_input="irrelevant"
    )

    assert isinstance(result, CommandResponse)
    assert result.code == "workflow_prompt"
    assert result.payload["workflow"] == "register_user"
    assert result.payload["step"] == 1
    assert "Choose a username" in result.payload["prompt"]

