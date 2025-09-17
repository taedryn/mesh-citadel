import threading
import secrets
import logging
from datetime import datetime, timedelta
from config import Config
from citadel.db.manager import DatabaseManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SessionManager:
    def __init__(self, config: Config, db: DatabaseManager):
        self.timeout = timedelta(seconds=config.auth["session_timeout"])
        self.db = db
        self.sessions = {}  # token -> (username, last_active: datetime)
        self.lock = threading.Lock()
        self._start_sweeper()

    def create_session(self, username: str) -> str:
        if not self._user_exists(username):
            raise ValueError(f"Username '{username}' does not exist")

        token = secrets.token_urlsafe(24)
        now = datetime.utcnow()
        with self.lock:
            self.sessions[token] = (username, now)
        logger.info(f"Session created for username='{username}'")
        return token

    def validate_session(self, token: str) -> str | None:
        with self.lock:
            data = self.sessions.get(token)
            if not data:
                return None
            username, _ = data
            return username  # Always valid until sweeper expires it

    def touch_session(self, token: str) -> bool:
        now = datetime.utcnow()
        with self.lock:
            if token not in self.sessions:
                return False
            username, _ = self.sessions[token]
            self.sessions[token] = (username, now)
            return True

    def expire_session(self, token: str) -> bool:
        with self.lock:
            if token in self.sessions:
                username, _ = self.sessions[token]
                del self.sessions[token]
                logger.info(f"Session manually expired for username='{username}'")
                return True
            return False

    def _start_sweeper(self):
        def sweep():
            while True:
                threading.Event().wait(60)
                now = datetime.utcnow()
                with self.lock:
                    expired = [t for t, (_, ts) in self.sessions.items() if now - ts > self.timeout]
                    for t in expired:
                        username, _ = self.sessions[t]
                        del self.sessions[t]
                        logger.info(f"Session auto-expired for username='{username}'")
                        # TODO: Send logout announcement to user via message router or transport layer
        threading.Thread(target=sweep, daemon=True).start()

    def _user_exists(self, username: str) -> bool:
        try:
            result = self.db.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            return bool(result)
        except RuntimeError as e:
            logger.warning(f"Database error while checking username existence: {e}")
            return False

