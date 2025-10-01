import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.auth.login_handler import LoginHandler


@pytest.fixture
def mock_user(monkeypatch):
    monkeypatch.setattr("citadel.user.user.User.username_exists", AsyncMock())
    monkeypatch.setattr("citadel.user.user.User.verify_password", AsyncMock())
    monkeypatch.setattr("citadel.user.user.User.load", AsyncMock())


@pytest.fixture
def login_handler(mock_user):
    db_mgr = MagicMock()
    return LoginHandler(db_mgr)


@pytest.mark.asyncio
async def test_successful_authentication(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = True
    User.verify_password.return_value = True
    mock_user_obj = MagicMock()
    User.load.return_value = mock_user_obj

    result = await login_handler.authenticate("alice", "correct-password")

    assert result is mock_user_obj


@pytest.mark.asyncio
async def test_failed_password(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = True
    User.verify_password.return_value = False

    result = await login_handler.authenticate("alice", "wrong-password")

    assert result is None


@pytest.mark.asyncio
async def test_unknown_user(login_handler):
    from citadel.user.user import User
    User.username_exists.return_value = False

    result = await login_handler.authenticate("newuser", "irrelevant")

    assert result is None

