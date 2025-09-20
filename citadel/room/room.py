import logging

from citadel.user.user import User
from citadel.message.manager import MessageManager
from citadel.message.errors import InvalidContentError
from citadel.room.errors import RoomNotFoundError, PermissionDeniedError
from datetime import datetime, UTC

log = logging.getLogger(__name__)


class Room:
    _room_order = []

    def __init__(self, db, config, identifier: int | str):
        self.db = db
        self.config = config
        self.room_id = self.get_room_id(identifier)
        self.name = None
        self.description = None
        self.read_only = False
        self.permission_level = "user"
        self.next_neighbor = None
        self.prev_neighbor = None
        self._load_metadata()

    def _load_metadata(self):
        result = self.db.execute(
            "SELECT name, description, read_only, permission_level, next_neighbor, prev_neighbor FROM rooms WHERE id = ?",
            (self.room_id,)
        )
        if not result:
            raise RoomNotFoundError(f"Room {self.room_id} does not exist.")
        self.name, self.description, self.read_only, self.permission_level, self.next_neighbor, self.prev_neighbor = result[
            0]

    def get_id_by_name(self, name: str) -> int:
        result = self.db.execute(
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
        if user.permission == "sysop":
            return True
        if self.permission_level == "aide":
            return user.permission in ("aide", "sysop")
        if self.permission_level == "twit":
            return user.permission == "twit"
        return True

    def can_user_post(self, user: User) -> bool:
        if self.read_only:
            return user.permission in ("aide", "sysop")
        return self.can_user_read(user)

    # ------------------------------------------------------------
    # ignore management
    # ------------------------------------------------------------
    def is_ignored_by(self, user: User) -> bool:
        result = self.db.execute(
            "SELECT 1 FROM room_ignores WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        return bool(result)

    def ignore_for_user(self, user: User):
        self.db.execute(
            "INSERT OR IGNORE INTO room_ignores (username, room_id) VALUES (?, ?)",
            (user.username, self.room_id)
        )

    def unignore_for_user(self, user: User):
        self.db.execute(
            "DELETE FROM room_ignores WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )

    # ------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------
    def go_to_next_room(self, user: User, with_unread: bool = True) -> "Room | None":
        current = self.next_neighbor
        while current:
            candidate = Room(self.db, self.config, current)
            if not candidate.can_user_read(user):
                current = candidate.next_neighbor
                continue
            if candidate.is_ignored_by(user):
                current = candidate.next_neighbor
                continue
            if with_unread and not candidate.has_unread_messages(user):
                current = candidate.next_neighbor
                continue
            return candidate
        return None

    def go_to_previous_room(self, user: User) -> "Room | None":
        current = self.prev_neighbor
        while current:
            candidate = Room(self.db, self.config, current)
            if candidate.can_user_read(user) and not candidate.is_ignored_by(user):
                return candidate
            current = candidate.prev_neighbor
        return None

    def has_unread_messages(self, user: User) -> bool:
        newest = self.get_newest_message_id()
        if not newest:
            return False

        pointer = self.db.execute(
            "SELECT last_seen_message_id FROM user_room_state WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        last_seen = pointer[0][0] if pointer else None
        return last_seen != newest

    def get_room_id(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            return identifier

        if isinstance(identifier, str):
            if identifier.isdigit():
                return int(identifier)
            room_id = self.get_id_by_name(identifier)
            if not room_id:
                raise RoomNotFoundError(f"No room named {identifier} found")
            return room_id

        raise RoomNotFoundError("No room matching identifier {identifier} found")
    
    def go_to_room(self, identifier: int | str) -> "Room":
        return Room(self.db, self.config, self.get_room_id(identifier))

    # ------------------------------------------------------------
    # message handling
    # ------------------------------------------------------------
    def get_message_ids(self) -> list[int]:
        rows = self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id",
            (self.room_id,)
        )
        return [row[0] for row in rows]

    def get_oldest_message_id(self) -> int | None:
        result = self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id LIMIT 1",
            (self.room_id,)
        )
        return result[0][0] if result else None

    def get_newest_message_id(self) -> int | None:
        result = self.db.execute(
            "SELECT message_id FROM room_messages WHERE room_id = ? ORDER BY message_id DESC LIMIT 1",
            (self.room_id,)
        )
        return result[0][0] if result else None

    def post_message(self, sender: str, content: str) -> int:
        if not self.can_user_post(User(self.db, sender)):
            raise PermissionDeniedError(
                f"User {sender} cannot post in room {self.name}")

        msg_mgr = MessageManager(self.config, self.db)

        # Prune if needed
        current_count = self.db.execute(
            "SELECT COUNT(*) FROM room_messages WHERE room_id = ?", (self.room_id,)
        )[0][0]
        max_messages = self.config.bbs["max_messages_per_room"]
        if current_count >= max_messages:
            oldest_id = self.get_oldest_message_id()
            if oldest_id:
                msg_mgr.delete_message(oldest_id)

        # Post and link
        msg_id = msg_mgr.post_message(sender, content)
        timestamp = datetime.now(UTC).isoformat()
        self.db.execute(
            "INSERT INTO room_messages (room_id, message_id, timestamp) VALUES (?, ?, ?)",
            (self.room_id, msg_id, timestamp)
        )
        return msg_id

    def get_next_unread_message(self, user: User) -> dict | None:
        pointer = self.db.execute(
            "SELECT last_seen_message_id FROM user_room_state WHERE username = ? AND room_id = ?",
            (user.username, self.room_id)
        )
        last_seen = pointer[0][0] if pointer else None

        message_ids = self.get_message_ids()
        if not message_ids:
            return None

        # First visit
        if last_seen is None:
            self.db.execute(
                "INSERT OR REPLACE INTO user_room_state (username, room_id, last_seen_message_id) VALUES (?, ?, ?)",
                (user.username, self.room_id, message_ids[0])
            )
            last_seen = message_ids[0]

        # Find next unread
        try:
            idx = message_ids.index(last_seen)
            next_id = message_ids[idx + 1]
        except (ValueError, IndexError):
            return None

        msg_mgr = MessageManager(self.config, self.db)
        msg = msg_mgr.get_message(next_id, recipient_user=user)

        # Advance pointer
        self.db.execute(
            "UPDATE user_room_state SET last_seen_message_id = ? WHERE username = ? AND room_id = ?",
            (next_id, user.username, self.room_id)
        )
        return msg

    def skip_to_latest(self, user: User):
        latest_id = self.get_newest_message_id()
        if latest_id:
            self.db.execute(
                "INSERT OR REPLACE INTO user_room_state (username, room_id, last_seen_message_id) VALUES (?, ?, ?)",
                (user.username, self.room_id, latest_id)
            )

    # ------------------------------------------------------------
    # room management
    # ------------------------------------------------------------
    @classmethod
    def insert_room_between(cls, db, config, name: str, description: str, read_only: bool,
                            permission_level: str, prev_id: int, next_id: int) -> int:
        db.execute(
            "INSERT INTO rooms (name, description, read_only, permission_level, prev_neighbor, next_neighbor) VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, read_only, permission_level, prev_id, next_id)
        )
        new_id = db.execute("SELECT last_insert_rowid()")[0][0]
        db.execute("UPDATE rooms SET next_neighbor = ? WHERE id = ?",
                   (new_id, prev_id))
        db.execute("UPDATE rooms SET prev_neighbor = ? WHERE id = ?",
                   (new_id, next_id))
        cls._room_order.clear()
        return new_id

    def delete_room(self, sys_user: str):
        # Log to system events room
        system_room_name = self.config.bbs.get("system_events_room")
        if system_room_name:
            system_room = Room(self.db, self.config, system_room_name)
            system_room.post_message(
                sys_user, f"Room '{self.name}' was deleted.")

        # Delete room and cascade
        self.db.execute("DELETE FROM rooms WHERE id = ?", (self.room_id,))
        Room._room_order.clear()

    @classmethod
    def initialize_room_order(cls, db, config):
        cls._room_order.clear()
        head = db.execute("SELECT id FROM rooms WHERE prev_neighbor IS NULL")
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

            next_row = db.execute(
                "SELECT next_neighbor FROM rooms WHERE id = ?", (current,))
            current = next_row[0][0] if next_row and next_row[0][0] else None

        cls._room_order.extend(chain)

        # Check for orphaned rooms
        all_rooms = set(r[0] for r in db.execute("SELECT id FROM rooms"))
        unreachable = all_rooms - visited
        if unreachable:
            log.warning(f"Orphaned rooms detected: {sorted(unreachable)}")

        # Optional: check for broken links
        for room_id in all_rooms:
            neighbors = db.execute(
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
