import logging
from datetime import datetime, UTC
from typing import Optional

from citadel.auth.permissions import PermissionLevel

log = logging.getLogger(__name__)

PERMISSIONS = {"unverified", "twit", "user", "aide", "sysop"}


class User:
    def __init__(self, db_manager, username: str):
        self.db = db_manager
        self.username = username
        self._loaded = False

    # this must be called for every User invocation
    async def load(self, force=False):
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

    @classmethod
    async def create(cls, config, db_mgr, username, password_hash,
                     salt, display_name=None):
        query = "INSERT INTO users (username, password_hash, salt, display_name, permission_level) VALUES (?, ?, ?, ?, ?)"
        await db_mgr.execute(query, (username, password_hash, salt,
                                     display_name,
                                     PermissionLevel.UNVERIFIED.value))

    @property
    def display_name(self) -> Optional[str]:
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
        try:
            return PermissionLevel(self._permission_level)
        except ValueError:
            raise RuntimeError('_permission_level not initialized, ensure '
                               'load() has been called on this object')

    async def set_permission_level(self, new_permission_level: PermissionLevel):
        if not isinstance(new_permission_level, PermissionLevel):
            raise ValueError(f"Invalid permission level: {new_permission_level}")
        query = "UPDATE users SET permission_level = ? WHERE username = ?"
        await self.db.execute(query, (new_permission_level.value, self.username))
        self._permission_level = new_permission_level

    @property
    def last_login(self) -> Optional[str]:
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
        try:
            return self._password_hash
        except AttributeError:
            raise RuntimeError('_password_hash not initialized, ensure '
                               'load() has been called on this object')

    @property
    def salt(self) -> bytes:
        try:
            return self._salt
        except AttributeError:
            raise RuntimeError('_salt not initialized, ensure '
                               'load() has been called on this object')

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
