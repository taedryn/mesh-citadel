import logging
from datetime import datetime, UTC
from dateutil.parser import parse as dateparse
from typing import Optional
from zoneinfo import ZoneInfo

from citadel.user.user import User
from citadel.message.errors import InvalidRecipientError, InvalidContentError

log = logging.getLogger(__name__)



def format_timestamp(config, utc_timestamp):
    if isinstance(utc_timestamp, str):
        utc_timestamp = dateparse(utc_timestamp)
    elif isinstance(utc_timestamp, int):
        utc_timestamp = datetime.fromtimestamp(utc_timestamp)

    tz = config.bbs.get('timezone', 'UTC')
    date_fmt = config.bbs.get('date_format', '%d%b%y $H:$M')
    timestamp = utc_timestamp.astimezone(ZoneInfo(tz)).strftime(date_fmt)
    return timestamp


class MessageManager:
    def __init__(self, config, db_manager):
        self.db = db_manager
        self.config = config

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

    async def get_message(self, message_id: int, recipient_user: "User") -> dict:
        """Returns message data structure, including blocked status and
        sender's display name.

        For private messages (with recipient), only returns the message
        if recipient_user is the sender or recipient. No admin override
        for private message privacy.  """
        query = """
            SELECT id, sender, recipient, content, timestamp
            FROM messages
            WHERE id = ?
        """
        result = await self.db.execute(query, (message_id,))
        if not result:
            return None

        msg = dict(
            zip(
                ["id", "sender", "recipient", "content", "timestamp"],
                result[0]
            )
        )

        # Privacy check for private messages
        if msg["recipient"]:
            # Private message - only sender and recipient can read
            is_sender = msg['sender'] == recipient_user.username
            is_recipient = msg['recipient'] == recipient_user.username
            if not (is_sender or is_recipient):
                return {}

        sender_user = User(self.db, msg["sender"])
        await sender_user.load()
        msg["display_name"] = sender_user.display_name or msg["sender"]

        is_blocked = await recipient_user.is_blocked(msg["sender"])
        msg["blocked"] = is_blocked

        return msg

    async def delete_message(self, message_id: int) -> bool:
        """Deletes a message permanently. Message contents are
        intentionally not preserved. Deleted means deleted. Room linkage
        must be cleaned up externally."""
        try:
            await self.db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            log.info(f"Deleted message {message_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete message {message_id}: {e}")
            return False

    async def get_message_summary(self, message_id: int, recipient_user: "User", msg_len: int=0) -> str:
        """returns the first msg_len characters of a message (which
        includes the sender and timestamp), as a string."""
        query = """
            SELECT sender, recipient, content, timestamp
            FROM messages
            WHERE id = ?
        """
        result = await self.db.execute(query, (message_id,))
        if not result:
            return ""

        sender, recipient, content, utc_timestamp = result[0]
        timestamp = format_timestamp(self.config, utc_timestamp)
        sender_user = User(self.db, sender)
        await sender_user.load()
        try:
            display_name = sender_user.display_name
        except RuntimeError:
            display_name = sender

        header = f'{display_name} {timestamp}: '
        is_blocked = await recipient_user.is_blocked(sender)
        if recipient_user and is_blocked:
            content = '[blocked]'
        content = header + content

        if msg_len:
            max_summary_len = msg_len
        else:
            mc_config = self.config.transport.get("meshcore", {})
            max_summary_len = mc_config["max_packet_size"]

        summary = content[:max_summary_len]
        return summary
