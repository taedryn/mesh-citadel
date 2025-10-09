import logging
from datetime import datetime, UTC
from typing import Optional

from citadel.user.user import User
from citadel.message.errors import InvalidRecipientError, InvalidContentError

log = logging.getLogger(__name__)


class MessageManager:
    def __init__(self, config, db_manager):
        self.db = db_manager

    async def post_message(self, sender: str, content: str, recipient: Optional[str] = None) -> int:
        if not content or not isinstance(content, str) or content.strip() == "":
            raise InvalidContentError("Message content is empty or invalid.")

        if recipient:
            result = await self.db.execute(
                "SELECT 1 FROM users WHERE username = ?", (recipient,))
            if not result:
                raise InvalidRecipientError(
                    f"Recipient '{recipient}' does not exist.")

        timestamp = datetime.now(UTC).isoformat()
        query = """
            INSERT INTO messages (sender, recipient, content, timestamp)
            VALUES (?, ?, ?, ?)
        """
        await self.db.execute(query, (sender, recipient, content, timestamp))
        msg_result = await self.db.execute("SELECT last_insert_rowid()")
        msg_id = msg_result[0][0]
        log.debug(f"Posted message {msg_id} from sender '{sender}'")
        return msg_id

    async def get_message(self, message_id: int, recipient_user: Optional["User"] = None) -> Optional[dict]:
        """Returns message data structure, including blocked status and sender's display name.

        For private messages (with recipient), only returns the message if recipient_user
        is the sender or recipient. No admin override for private message privacy.
        """
        query = "SELECT id, sender, recipient, content, timestamp FROM messages WHERE id = ?"
        result = await self.db.execute(query, (message_id,))
        if not result:
            return None

        msg = dict(
            zip(["id", "sender", "recipient", "content", "timestamp"], result[0]))

        # Privacy check for private messages
        if msg["recipient"] and recipient_user:
            # Private message - only sender and recipient can read
            user_can_read = (
                msg["sender"] == recipient_user.username or  # Sender can read
                # Recipient can read
                msg["recipient"] == recipient_user.username
            )
            if not user_can_read:
                return None  # User not authorized to read this private message

        sender_user = User(self.db, msg["sender"])
        await sender_user.load()
        msg["display_name"] = sender_user.display_name or msg["sender"]
        msg["blocked"] = await recipient_user.is_blocked(msg['sender']) if recipient_user else False
        return msg

    async def delete_message(self, message_id: int) -> bool:
        """Deletes a message permanently. Room linkage must be cleaned up externally."""
        try:
            await self.db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            log.info(f"Deleted message {message_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete message {message_id}: {e}")
            return False

    async def get_messages(self, message_ids: list[int], recipient_user: Optional["User"] = None) -> list[dict]:
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
        results = await self.db.execute(query, tuple(message_ids))
        messages = []
        for row in results:
            msg = dict(
                zip(["id", "sender", "recipient", "content", "timestamp"], row))
            sender_user = User(self.db, msg["sender"])
            await sender_user.load()
            try:
                msg["display_name"] = sender_user.display_name
            except RuntimeError:
                msg["display_name"] = msg["sender"]
            is_blocked = await recipient_user.is_blocked(msg["sender"])
            msg["blocked"] = is_blocked if recipient_user else False
            messages.append(msg)
        return messages

    async def get_message_summary(self, message_id: int) -> Optional[str]:
        """Returns a truncated summary of the message, accounting for timestamp and display name."""
        query = "SELECT sender, content, timestamp FROM messages WHERE id = ?"
        result = await self.db.execute(query, (message_id,))
        if not result:
            return None

        sender, content, timestamp = result[0]
        sender_user = User(self.db, sender)
        await sender_user.load()
        try:
            display_name = sender_user.display_name
        except RuntimeError:
            display_name = sender

        reserved = len(timestamp) + len(display_name)
        max_summary_len = max(0, 184 - reserved)

        summary = content[:max_summary_len]
        return summary
