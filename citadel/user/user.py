import logging
from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from citadel.auth.passwords import verify_password
from citadel.auth.permissions import PermissionLevel

log = logging.getLogger(__name__)


class UserStatus(str, Enum):
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    BANNED = "banned"
    SUSPENDED = "suspended"


log = logging.getLogger(__name__)

PERMISSIONS = {"unverified", "twit", "user", "aide", "sysop"}


class User:
    def __init__(self, db_manager, username: str):
        self.db = db_manager
        self.username = username
        self._loaded = False

    # this must be called for every User invocation
    async def load(self, force=False):
        if self.username == "citadel":
            return self._load_citadel()
        if self._loaded and not force:
            return
        query = "SELECT * FROM users WHERE username = ?"
        result = await self.db.execute(query, (self.username,))
        if not result:
            raise RuntimeError(f"User '{self.username}' not found.")
        self._row_to_fields(result[0])
        self._loaded = True

    def _row_to_fields(self, row: tuple):
        self.id = row[0]
        self._username = row[1]
        self._password_hash = row[2]
        self._salt = row[3]
        self._display_name = row[4]
        self._last_login = row[5]
        self._permission_level = row[6]
        self._status = row[7]

    def _load_citadel(self):
        self.id = 0
        self._username = "citadel"
        self._password_hash = "*"
        self._salt = "*"
        self._display_name = "Citadel System"
        self._last_login = datetime.now(UTC)
        self._permission_level = PermissionLevel.SYSOP
        self._status = UserStatus.ACTIVE
        self._loaded = True

    # ------------------------------------------------------------
    # class methods
    # ------------------------------------------------------------

    @classmethod
    async def create(cls, config, db_mgr, username, password_hash,
                     salt, display_name=None, status=UserStatus.PROVISIONAL):
        query = "INSERT OR IGNORE INTO users (username, password_hash, salt, display_name, permission_level, status) VALUES (?, ?, ?, ?, ?, ?)"
        await db_mgr.execute(query, (username, password_hash, salt,
                                     display_name,
                                     PermissionLevel.UNVERIFIED.value,
                                     status.value))

    @classmethod
    async def username_exists(cls, db_mgr, test_username: str) -> str:
        """Check if username exists (case-insensitive)."""
        query = "SELECT username FROM users WHERE LOWER(username) = LOWER(?)"
        result = await db_mgr.execute(query, (test_username,))
        if result:
            return result[0][0]
        else:
            return None

    @classmethod
    async def get_actual_username(cls, db_mgr, username_input: str) -> Optional[str]:
        """Get the actual stored username for case-insensitive input."""
        query = "SELECT username FROM users WHERE LOWER(username) = LOWER(?)"
        result = await db_mgr.execute(query, (username_input,))
        if not result:
            return None
        return result[0][0]

    @classmethod
    async def verify_password(cls, db_mgr, username: str, submitted_password: str) -> bool:
        """Verify password for username (case-insensitive lookup)."""
        query = "SELECT password_hash, salt FROM users WHERE LOWER(username) = LOWER(?)"
        result = await db_mgr.execute(query, (username,))
        if not result:
            return False
        stored_hash, salt = result[0]
        return verify_password(submitted_password, salt, stored_hash)

    @classmethod
    async def get_user_count(cls, db_mgr) -> int:
        """Count the users currently in the system and return the
        number"""
        query = "SELECT count(username) from users"
        result = await db_mgr.execute(query, [])
        if not result:
            return 0
        count = result[0][0]
        return count

    # ------------------------------------------------------------
    # getters and setters
    # ------------------------------------------------------------

    @property
    def display_name(self) -> Optional[str]:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return self._display_name
        except AttributeError:
            raise RuntimeError('_display_name not initialized, ensure '
                               'load() has been called on this object')

    async def set_display_name(self, new_name: str):
        query = "UPDATE users SET display_name = ? WHERE username = ?"
        await self.db.execute(query, (new_name, self.username))
        self._display_name = new_name

    @property
    def permission_level(self) -> PermissionLevel:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return PermissionLevel(self._permission_level)
        except ValueError:
            raise RuntimeError('_permission_level not initialized, ensure '
                               'load() has been called on this object')

    async def set_permission_level(self, new_permission_level: PermissionLevel):
        if not isinstance(new_permission_level, PermissionLevel):
            raise ValueError(
                f"Invalid permission level: {new_permission_level}")
        query = "UPDATE users SET permission_level = ? WHERE username = ?"
        await self.db.execute(query, (new_permission_level.value, self.username))
        self._permission_level = new_permission_level

    @property
    def status(self) -> UserStatus:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return UserStatus(self._status)
        except (AttributeError, ValueError):
            raise RuntimeError('_status not initialized or invalid, ensure '
                               'load() has been called on this object')

    async def set_status(self, new_status: UserStatus):
        if not isinstance(new_status, UserStatus):
            raise ValueError(
                f"Invalid status: {new_status}. Must be a UserStatus enum value")
        query = "UPDATE users SET status = ? WHERE username = ?"
        await self.db.execute(query, (new_status.value, self.username))
        self._status = new_status.value

    @property
    def last_login(self) -> Optional[str]:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return self._last_login
        except AttributeError:
            raise RuntimeError('_last_login not initialized, ensure '
                               'load() has been called on this object')

    async def set_last_login(self, timestamp: Optional[datetime | str]):
        if timestamp == "now":
            timestamp = datetime.now(UTC)
        elif isinstance(timestamp, str):
            raise ValueError("Use 'now' or a datetime object for last_login.")
        query = "UPDATE users SET last_login = ? WHERE username = ?"
        await self.db.execute(query, (timestamp.isoformat(), self.username))
        self._last_login = timestamp.isoformat()

    @property
    def password_hash(self) -> str:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return self._password_hash
        except AttributeError:
            raise RuntimeError('_password_hash not initialized, ensure '
                               'load() has been called on this object')

    @property
    def salt(self) -> bytes:
        if not self._loaded:
            raise RuntimeError('Call .load() on this object first')
        try:
            return self._salt
        except AttributeError:
            raise RuntimeError('_salt not initialized, ensure '
                               'load() has been called on this object')

    # ------------------------------------------------------------
    # methods
    # ------------------------------------------------------------

    async def update_password(self, new_hash: str, new_salt: bytes):
        query = "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?"
        await self.db.execute(query, (new_hash, new_salt, self.username))
        self._password_hash = new_hash
        self._salt = new_salt

    async def block_user(self, target_username: str):
        query = "INSERT OR IGNORE INTO user_blocks (blocker, blocked) VALUES (?, ?)"
        await self.db.execute(query, (self.username, target_username))
        log.info(f"{self.username} blocked {target_username}")

    async def unblock_user(self, target_username: str):
        query = "DELETE FROM user_blocks WHERE blocker = ? AND blocked = ?"
        await self.db.execute(query, (self.username, target_username))
        log.info(f"{self.username} unblocked {target_username}")

    async def is_blocked(self, sender_username: str) -> bool:
        query = "SELECT 1 FROM user_blocks WHERE blocker = ? AND blocked = ?"
        result = await self.db.execute(query, (self.username, sender_username))
        return bool(result)
