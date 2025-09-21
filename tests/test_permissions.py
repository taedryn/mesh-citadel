import pytest
from citadel.auth.checker import is_allowed, permission_denied, PermissionLevel
from citadel.commands.responses import ErrorResponse

class DummyUser:
    def __init__(self, level):
        self.permission_level = level
        self.username = "testuser"

class DummyRoom:
    def __init__(self, can_read=True, can_post=True):
        self.name = "Lobby"
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
    assert is_allowed("post", user, room)

def test_twit_cannot_post():
    user = DummyUser(PermissionLevel.TWIT)
    room = DummyRoom()
    assert not is_allowed("post", user, room)

def test_unverified_can_read():
    user = DummyUser(PermissionLevel.UNVERIFIED)
    room = DummyRoom()
    assert is_allowed("read", user, room)

def test_sysop_can_do_anything():
    user = DummyUser(PermissionLevel.SYSOP)
    room = DummyRoom()
    assert is_allowed("post", user, room)
    assert is_allowed("read", user, room)
    assert is_allowed("delete", user, room)  # assuming delete requires aide/sysop

# ------------------------------------------------------------
# Room-specific checks
# ------------------------------------------------------------
def test_room_blocks_posting():
    user = DummyUser(PermissionLevel.USER)
    room = DummyRoom(can_post=False)
    assert not is_allowed("post", user, room)

def test_room_blocks_reading():
    user = DummyUser(PermissionLevel.USER)
    room = DummyRoom(can_read=False)
    assert not is_allowed("read", user, room)

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
    resp = permission_denied("post", user, room)
    assert isinstance(resp, ErrorResponse)
    assert resp.code == "permission_denied"
    assert "post" in resp.text

