import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.auth.passwords import authenticate


@pytest.fixture
def mock_user(monkeypatch):
    username_exists_mock = AsyncMock()
    verify_password_mock = AsyncMock()
    get_actual_username_mock = AsyncMock()

    monkeypatch.setattr("citadel.user.user.User.username_exists", username_exists_mock)
    monkeypatch.setattr("citadel.user.user.User.verify_password", verify_password_mock)
    monkeypatch.setattr("citadel.user.user.User.get_actual_username", get_actual_username_mock)

    mock_user_instance = MagicMock()
    mock_user_instance.load = AsyncMock()
    mock_user_class = MagicMock(return_value=mock_user_instance)
    monkeypatch.setattr("citadel.user.user.User", mock_user_class)

    return {
        'instance': mock_user_instance,
        'username_exists': username_exists_mock,
        'verify_password': verify_password_mock,
        'get_actual_username': get_actual_username_mock
    }


@pytest.fixture
def db_mgr():
    return MagicMock()


@pytest.mark.asyncio
async def test_successful_authentication(mock_user, db_mgr):
    mock_user['username_exists'].return_value = True
    mock_user['get_actual_username'].return_value = "alice"
    mock_user['verify_password'].return_value = True

    result = await authenticate(db_mgr, "alice", "correct-password")

    assert result is mock_user['instance']


@pytest.mark.asyncio
async def test_failed_password(mock_user, db_mgr):
    mock_user['username_exists'].return_value = True
    mock_user['get_actual_username'].return_value = "alice"
    mock_user['verify_password'].return_value = False

    result = await authenticate(db_mgr, "alice", "wrong-password")

    assert result is None


@pytest.mark.asyncio
async def test_unknown_user(mock_user, db_mgr):
    mock_user['username_exists'].return_value = False

    result = await authenticate(db_mgr, "newuser", "irrelevant")

    assert result is None

