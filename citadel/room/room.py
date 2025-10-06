from dataclasses import dataclass
import logging

from citadel.auth.permissions import PermissionLevel
from citadel.user.user import User
from citadel.message.manager import MessageManager
from citadel.message.errors import InvalidContentError
from citadel.room.errors import RoomNotFoundError, PermissionDeniedError
from datetime import datetime, UTC

log = logging.getLogger(__name__)


@dataclass
class SystemRoomIDs:
    # Reserved system room IDs (1-6)
    LOBBY_ID = 1
    MAIL_ID = 2
    AIDES_ID = 3
    SYSOP_ID = 4
    SYSTEM_ID = 5
    TWIT_ID = 6

    @classmethod
    def as_set(cls):
        return {v for k, v in vars(cls).items() if k.endswith("_ID")}


class Room:
    # Set of all system room IDs for easy checking
    SYSTEM_ROOM_IDS = SystemRoomIDs.as_set()

    # Minimum ID for user-created rooms (leaves room for future system rooms)
    MIN_USER_ROOM_ID = 100

    _room_order = []

    @classmethod
    def get_system_room_names(cls, config):
        """Get system room names from config with fallback defaults."""
        room_names = config.bbs.get('room_names', {})
        return {
            SystemRoomIDs.LOBBY_ID: room_names.get('lobby', 'Lobby'),
            SystemRoomIDs.MAIL_ID: room_names.get('mail', 'Mail'),
            SystemRoomIDs.AIDES_ID: room_names.get('aides', 'Aides'),
            SystemRoomIDs.SYSOP_ID: room_names.get('sysop', 'Sysop'),
            SystemRoomIDs.SYSTEM_ID: room_names.get('system', 'System'),
            SystemRoomIDs.TWIT_ID: room_names.get('twit', 'Purgatory'),
        }

    def __init__(self, db, config, identifier: int | str):
        self.db = db
        self.config = config
        self.room_id = identifier
        self.name = None
        self.description = None
        self.read_only = False
        self.permission_level = PermissionLevel.USER
        self.next_neighbor = None
        self.prev_neighbor = None
        self._loaded = False

    # this must be called on every object after instantiation
    async def load(self, force=False):
        if self._loaded and not force:
            return
        self.room_id = await self.get_room_id(self.room_id)
        result = await self.db.execute(
            "SELECT name, description, read_only, permission_level, next_neighbor, prev_neighbor FROM rooms WHERE id = ?",
            (self.room_id,)
        )
        if not result:
            raise RoomNotFoundError(f"Room {self.room_id} does not exist.")
        self.name = result[0][0]
        self.description = result[0][1]
        self.read_only = result[0][2]
        self.permission_level = PermissionLevel(int(result[0][3]))
        self.next_neighbor = result[0][4]
        self.prev_neighbor = result[0][5]
        self._loaded = True

    async def get_id_by_name(self, name: str) -> int:
        result = await self.db.execute(
            "SELECT id FROM rooms WHERE name = ? COLLATE NOCASE",
            (name,)
        )
        if not result:
            raise RoomNotFoundError(f"No room named '{name}' found")
        return result[0][0]

    # ------------------------------------------------------------
    # permission methods
    # ------------------------------------------------------------
    def can_user_read(self, user: User) -> bool:
        if user.permission_level == PermissionLevel.SYSOP:
            return True
        if self.permission_level == PermissionLevel.AIDE:
            answer = user.permission_level >= PermissionLevel.AIDE
            return answer
        if self.permission_level == PermissionLevel.USER:
            answer = user.permission_level >= PermissionLevel.USER
            return answer
        if self.permission_level == PermissionLevel.TWIT:
            return True
        return False

    def can_user_post(self, user: User) -> bool:
        if self.read_only:
            return user.permission_level >= PermissionLevel.AIDE
        return self.can_user_read(user)

    # ------------------------------------------------------------
    # ignore management
    # ------------------------------------------------------------
    async def is_ignored_by(self, user: User) -> bool:
        result = await self.db.execute(
            "SELECT 1 FROM room_ignores WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        return bool(result)

    async def ignore_for_user(self, user: User):
        await self.db.execute(
            "INSERT OR IGNORE INTO room_ignores (username, room_id) VALUES (?, ?)",
            (user.username, self.room_id)
        )

    async def unignore_for_user(self, user: User):
        await self.db.execute(
            "DELETE FROM room_ignores WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )

    # ------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------
    async def go_to_next_room(self, user: User, with_unread: bool = True) -> "Room | None":
        current = self.next_neighbor
        while current:
            candidate = Room(self.db, self.config, current)
            await candidate.load()
            if not candidate.can_user_read(user):
                current = candidate.next_neighbor
                continue
            is_ignored = await candidate.is_ignored_by(user)
            if is_ignored:
                current = candidate.next_neighbor
                continue
            has_unread = await candidate.has_unread_messages(user)
            if with_unread and not has_unread:
                current = candidate.next_neighbor
                continue
            return candidate

        # If no unread rooms found, go to Lobby
        lobby = Room(self.db, self.config, SystemRoomIDs.LOBBY_ID)
        await lobby.load()
        return lobby

    async def go_to_previous_room(self, user: User) -> "Room | None":
        current = self.prev_neighbor
        while current:
            candidate = Room(self.db, self.config, current)
            await candidate.load()
            if candidate.can_user_read(user) and not await candidate.is_ignored_by(user):
                return candidate
            current = candidate.prev_neighbor
        return None

    async def get_last_unread_message_id(self, user: User) -> int:
        last_read = await self.db.execute(
            "SELECT last_seen_message_id FROM user_room_state WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        if not last_read or last_read[0][0] is None:
            return 0
        return last_read[0][0]

    async def has_unread_messages(self, user: User) -> bool:
        newest = await self.get_newest_message_id()
        if not newest:
            return False

        pointer = await self.get_last_unread_message_id(user)
        last_seen = pointer[0][0] if pointer else None
        return last_seen != newest

    async def get_room_id(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            return identifier

        if isinstance(identifier, str):
            if identifier.isdigit():
                return int(identifier)
            room_id = await self.get_id_by_name(identifier)
            if not room_id:
                raise RoomNotFoundError(f"No room named {identifier} found")
            return room_id

        raise RoomNotFoundError(
            f"No room matching identifier {identifier} found")

    async def go_to_room(self, identifier: int | str) -> "Room":
        room_id = await self.get_room_id(identifier)
        room = Room(self.db, self.config, room_id)
        return room

    @classmethod
    async def get_all_visible_rooms(cls, db, config, user):
        """Return rooms the user can read and hasn't ignored."""
        rows = await db.execute("SELECT id FROM rooms ORDER BY id")
        room_ids = [row[0] for row in rows]

        visible_rooms = []
        for room_id in room_ids:
            room = Room(db, config, room_id)
            await room.load()

            readable = room.can_user_read(user)
            ignored = await room.is_ignored_by(user)

            if readable and not ignored:
                visible_rooms.append(room)

        return visible_rooms


    # ------------------------------------------------------------
    # message handling
    # ------------------------------------------------------------
    async def get_message_ids(self) -> list[int]:
        rows = await self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id",
            (self.room_id,)
        )
        return [row[0] for row in rows]

    async def get_unread_message_ids(self, username: str) -> list[int]:
        """ return a list of message ids which have not yet been seen
        by this user """
        user = User(self.db, username)
        await user.load()
        last_read = await self.get_last_unread_message_id(user)
        id_list = await self.db.execute("""
            SELECT message_id FROM room_messages
            WHERE room_id = ?
            AND message_id > ?
            """, (self.room_id, last_read))
        return [msg_id[0] for msg_id in id_list]

    async def get_oldest_message_id(self) -> int | None:
        result = await self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id LIMIT 1",
            (self.room_id,)
        )
        return result[0][0] if result else None

    async def get_newest_message_id(self) -> int | None:
        result = await self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id DESC LIMIT 1",
            (self.room_id,)
        )
        return result[0][0] if result else None

    async def post_message(self, sender: str, content: str, recipient: str = None) -> int:
        user = User(self.db, sender)
        await user.load()
        if not self.can_user_post(user):
            raise PermissionDeniedError(
                f"User {sender} cannot post in room {self.name}")

        msg_mgr = MessageManager(self.config, self.db)

        # Prune if needed
        count_result = await self.db.execute(
            "SELECT COUNT(*) FROM room_messages WHERE room_id = ?", (self.room_id,)
        )
        current_count = count_result[0][0]
        max_messages = self.config.bbs["max_messages_per_room"]
        if current_count >= max_messages:
            oldest_id = await self.get_oldest_message_id()
            if oldest_id:
                await msg_mgr.delete_message(oldest_id)
                await self.db.execute("DELETE FROM room_messages WHERE room_id = ? AND message_id = ?", (self.room_id, oldest_id))

        # Post and link
        msg_id = await msg_mgr.post_message(sender, content, recipient)
        timestamp = datetime.now(UTC).isoformat()
        await self.db.execute(
            "INSERT INTO room_messages (room_id, message_id, timestamp) VALUES (?, ?, ?)",
            (self.room_id, msg_id, timestamp)
        )
        return msg_id

    async def get_next_unread_message(self, user: User) -> dict | None:
        pointer = await self.db.execute(
            "SELECT last_seen_message_id FROM user_room_state WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        last_seen = pointer[0][0] if pointer else None

        message_ids = await self.get_message_ids()
        if not message_ids:
            return None

        # First visit - return the first message without marking it as seen yet
        if last_seen is None:
            first_id = message_ids[0]
            msg_mgr = MessageManager(self.config, self.db)
            msg = await msg_mgr.get_message(first_id, recipient_user=user)

            # Mark this message as seen
            await self.db.execute(
                "INSERT OR REPLACE INTO user_room_state (username, room_id, last_seen_message_id) VALUES (?, ?, ?)",
                (user.username, self.room_id, first_id)
            )
            return msg

        # Find next unread
        try:
            idx = message_ids.index(last_seen)
            next_id = message_ids[idx + 1]
        except (ValueError, IndexError):
            return None

        msg_mgr = MessageManager(self.config, self.db)
        msg = await msg_mgr.get_message(next_id, recipient_user=user)

        # Advance pointer
        await self.db.execute(
            "UPDATE user_room_state SET last_seen_message_id = ? WHERE username = ? AND room_id = ?",
            (next_id, user.username, self.room_id)
        )
        return msg

    async def skip_to_latest(self, user: User):
        latest_id = await self.get_newest_message_id()
        if latest_id:
            await self.db.execute(
                "INSERT OR REPLACE INTO user_room_state (username, room_id, last_seen_message_id) VALUES (?, ?, ?)",
                (user.username, self.room_id, latest_id)
            )

    # ------------------------------------------------------------
    # room management
    # ------------------------------------------------------------
    @classmethod
    async def _get_next_available_room_id(cls, db) -> int:
        """Get the next available room ID >= MIN_USER_ROOM_ID."""
        result = await db.execute("SELECT MAX(id) FROM rooms WHERE id >= ?", (cls.MIN_USER_ROOM_ID,))
        max_id = result[0][0] if result and result[0][0] is not None else cls.MIN_USER_ROOM_ID - 1
        return max_id + 1

    @classmethod
    async def create(cls, db, config, name: str, description: str,
                     read_only: bool, permission_level: PermissionLevel,
                     prev_id: int, next_id: int) -> int:
        # Get next available room ID >= 100
        new_id = await cls._get_next_available_room_id(db)

        await db.execute(
            "INSERT INTO rooms (id, name, description, read_only, permission_level, prev_neighbor, next_neighbor) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id, name, description, read_only,
             permission_level.value, prev_id, next_id)
        )

        # Update room chain links
        if prev_id:
            await db.execute("UPDATE rooms SET next_neighbor = ? WHERE id = ?", (new_id, prev_id))
        if next_id:
            await db.execute("UPDATE rooms SET prev_neighbor = ? WHERE id = ?", (new_id, next_id))

        cls._room_order.clear()
        return new_id

    async def delete_room(self, sys_user: str):
        # Prevent deletion of system rooms
        if self.room_id in self.SYSTEM_ROOM_IDS:
            raise PermissionDeniedError(
                f"Cannot delete system room '{self.name}' (ID: {self.room_id})")

        # Log to system events room (always ID 5)
        try:
            system_room = Room(self.db, self.config, SystemRoomIDs.SYSTEM_ID)
            await system_room.load()
            await system_room.post_message(
                sys_user, f"Room '{self.name}' was deleted.")
        except Exception as e:
            log.warning(
                f"Failed to log room deletion to system events room: {e}")

        # Delete room and cascade
        await self.db.execute("DELETE FROM rooms WHERE id = ?", (self.room_id,))
        Room._room_order.clear()

    @classmethod
    async def initialize_room_order(cls, db, config):
        cls._room_order.clear()
        head = await db.execute("SELECT id FROM rooms WHERE prev_neighbor IS NULL")
        if not head:
            log.warning(
                "No room with prev_neighbor=NULL found. Room chain may be broken.")
            return

        current = head[0][0]
        visited = set()
        chain = []

        while current:
            if current in visited:
                log.warning(
                    f"Cycle detected in room chain at room ID {current}.")
                break
            visited.add(current)
            chain.append(current)

            next_row = await db.execute(
                "SELECT next_neighbor FROM rooms WHERE id = ?", (current,))
            current = next_row[0][0] if next_row and next_row[0][0] else None

        cls._room_order.extend(chain)

        # Check for orphaned rooms
        rooms_result = await db.execute("SELECT id FROM rooms")
        all_rooms = set(r[0] for r in rooms_result)
        unreachable = all_rooms - visited
        if unreachable:
            log.warning(f"Orphaned rooms detected: {sorted(unreachable)}")

        # Optional: check for broken links
        for room_id in all_rooms:
            neighbors = await db.execute(
                "SELECT next_neighbor, prev_neighbor FROM rooms WHERE id = ?",
                (room_id,)
            )
            if neighbors:
                next_id, prev_id = neighbors[0]
                if next_id and next_id not in all_rooms:
                    log.warning(
                        f"Room {room_id} has invalid next_neighbor {next_id}")
                if prev_id and prev_id not in all_rooms:
                    log.warning(
                        f"Room {room_id} has invalid prev_neighbor {prev_id}")
