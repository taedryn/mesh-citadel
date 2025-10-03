import pytest
from citadel.auth.checker import is_allowed, permission_denied, PermissionLevel
from citadel.commands.responses import ErrorResponse
from citadel.room.room import SystemRoomIDs
from citadel.transport.packets import ToUser


class DummyUser:
    def __init__(self, level):
        self.permission_level = level
        self.username = "testuser"


class DummyRoom:
    def __init__(self, can_read=True, can_post=True, room_id=0):
        self.name = "Lobby"
        self.room_id = room_id
        self._can_read = can_read
        self._can_post = can_post

    def can_user_read(self, user):
        return self._can_read

    def can_user_post(self, user):
        return self._can_post

# ------------------------------------------------------------
# Permission level checks
# ------------------------------------------------------------


def test_user_can_post():
    user = DummyUser(PermissionLevel.USER)
    room = DummyRoom()
    assert is_allowed("enter_message", user, room)


def test_twit_cannot_post():
    user = DummyUser(PermissionLevel.TWIT)
    room = DummyRoom()
    assert not is_allowed("enter_message", user, room)


def test_twit_can_read():
    user = DummyUser(PermissionLevel.TWIT)
    room = DummyRoom()
    room.room_id = SystemRoomIDs.TWIT_ID
    assert is_allowed("read_messages", user, room)


def test_twit_can_post_in_twit():
    user = DummyUser(PermissionLevel.TWIT)
    room = DummyRoom()
    room.room_id = SystemRoomIDs.TWIT_ID
    assert is_allowed("enter_message", user, room)


def test_sysop_can_do_anything():
    user = DummyUser(PermissionLevel.SYSOP)
    room = DummyRoom()
    assert is_allowed("enter_message", user, room)
    assert is_allowed("read_messages", user, room)
    # assuming delete requires aide/sysop
    assert is_allowed("delete_message", user, room)

# ------------------------------------------------------------
# Room-specific checks
# ------------------------------------------------------------


def test_room_blocks_posting():
    user = DummyUser(PermissionLevel.USER)
    room = DummyRoom(can_post=False)
    assert not is_allowed("enter_message", user, room)


def test_room_blocks_reading():
    user = DummyUser(PermissionLevel.USER)
    room = DummyRoom(can_read=False)
    assert not is_allowed("read_messages", user, room)

# ------------------------------------------------------------
# Unknown action
# ------------------------------------------------------------


def test_unknown_action_denied():
    user = DummyUser(PermissionLevel.USER)
    assert not is_allowed("dance", user)

# ------------------------------------------------------------
# Error response helper
# ------------------------------------------------------------


def test_permission_denied_response():
    user = DummyUser(PermissionLevel.TWIT)
    room = DummyRoom()
    resp = permission_denied("enter_message", user, room)
    assert isinstance(resp, ToUser)
    assert resp.is_error
    assert resp.error_code == "permission_denied"
    assert "do not have permission" in resp.text
