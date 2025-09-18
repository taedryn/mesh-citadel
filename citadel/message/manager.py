import logging
from datetime import datetime, UTC
from typing import Optional

from citadel.user import User  # Assumes User is defined in citadel.user

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class MessageManager:
    def __init__(self, config, db_manager):
        self.db = db_manager

    def post_message(self, sender: str, content: str, recipient: Optional[str] = None) -> int:
        """Creates a new message. Room linkage is handled externally."""
        timestamp = datetime.now(UTC).isoformat()
        query = """
            INSERT INTO messages (sender, recipient, content, timestamp)
            VALUES (?, ?, ?, ?)
        """
        self.db.execute(query, (sender, recipient, content, timestamp))
        msg_id = self.db.execute("SELECT last_insert_rowid()")[0][0]
        log.debug(f"Posted message {msg_id} from sender '{sender}'")
        return msg_id

    def get_message(self, message_id: int, recipient_user: Optional["User"] = None) -> Optional[dict]:
        """Returns message data structure, including blocked status and sender's display name."""
        query = "SELECT id, sender, recipient, content, timestamp FROM messages WHERE id = ?"
        result = self.db.execute(query, (message_id,))
        if not result:
            return None

        msg = dict(zip(["id", "sender", "recipient", "content", "timestamp"], result[0]))
        sender_user = User(self.db, msg["sender"])
        msg["display_name"] = sender_user.display_name or msg["sender"]
        msg["blocked"] = recipient_user.is_blocked(msg["sender"]) if recipient_user else False
        return msg

    def delete_message(self, message_id: int) -> bool:
        """Deletes a message permanently. Room linkage must be cleaned up externally."""
        try:
            self.db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            log.info(f"Deleted message {message_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete message {message_id}: {e}")
            return False

    def get_messages(self, message_ids: list[int], recipient_user: Optional["User"] = None) -> list[dict]:
        """Returns a list of messages by ID, optionally annotated with blocked status and display name."""
        if not message_ids:
            return []

        placeholders = ",".join("?" for _ in message_ids)
        query = f"""
            SELECT id, sender, recipient, content, timestamp
            FROM messages
            WHERE id IN ({placeholders})
            ORDER BY timestamp ASC
        """
        results = self.db.execute(query, tuple(message_ids))
        messages = []
        for row in results:
            msg = dict(zip(["id", "sender", "recipient", "content", "timestamp"], row))
            sender_user = User(self.db, msg["sender"])
            msg["display_name"] = sender_user.display_name or msg["sender"]
            msg["blocked"] = recipient_user.is_blocked(msg["sender"]) if recipient_user else False
            messages.append(msg)
        return messages

    def get_message_summary(self, message_id: int) -> Optional[str]:
        """Returns a truncated summary of the message, accounting for timestamp and display name."""
        query = "SELECT sender, content, timestamp FROM messages WHERE id = ?"
        result = self.db.execute(query, (message_id,))
        if not result:
            return None

        sender, content, timestamp = result[0]
        sender_user = User(self.db, sender)
        display_name = sender_user.display_name or sender

        reserved = len(timestamp) + len(display_name)
        max_summary_len = max(0, 184 - reserved)

        summary = content[:max_summary_len]
        return summary

