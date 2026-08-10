import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from citadel.auth.passwords import authenticate


@pytest.fixture
def mock_user(monkeypatch):
    username_exists_mock = AsyncMock()
    verify_password_mock = AsyncMock()
    get_actual_username_mock = AsyncMock()

    mock_user_instance = MagicMock()
    mock_user_instance.load = AsyncMock()
    # authenticate() calls User.username_exists/get_actual_username/
    # verify_password as classmethod-style calls on `User` itself (not on
    # an instance), so the mocks need to live on the replacement class,
    # not on the real User class -- patching the real class's methods and
    # *then* replacing citadel.user.user.User wholesale (as this fixture
    # used to) shadows those patches entirely.
    mock_user_class = MagicMock(return_value=mock_user_instance)
    mock_user_class.username_exists = username_exists_mock
    mock_user_class.verify_password = verify_password_mock
    mock_user_class.get_actual_username = get_actual_username_mock
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

