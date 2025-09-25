from datetime import datetime, timedelta, UTC
import logging
import secrets
import threading

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.session.state import SessionState, WorkflowState

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class SessionManager:
    def __init__(self, config: "Config", db: DatabaseManager):
        self.timeout = timedelta(seconds=config.auth["session_timeout"])
        self.db = db
        self.sessions = {}  # token -> (SessionState, last_active: datetime)
        self.lock = threading.Lock()
        self.notification_callback = None  # Will be set by transport layer
        self._start_sweeper()

    def create_session_state(self, username: str) -> SessionState:
        return SessionState(username=username, current_room="Lobby")

    async def create_session(self, username: str) -> str:
        if not await self._user_exists(username):
            raise ValueError(f"Username '{username}' does not exist")

        token = secrets.token_urlsafe(24)
        now = datetime.now(UTC)
        state = self.create_session_state(username)
        with self.lock:
            self.sessions[token] = (state, now)
        log.info(f"Session created for username='{username}'")
        return token

    def validate_session(self, token: str) -> SessionState | None:
        with self.lock:
            data = self.sessions.get(token)
            if not data:
                return None
            state, _ = data
            return state

    def touch_session(self, token: str) -> bool:
        now = datetime.now(UTC)
        with self.lock:
            if token not in self.sessions:
                return False
            state, _ = self.sessions[token]
            self.sessions[token] = (state, now)
            return True

    def expire_session(self, token: str) -> bool:
        with self.lock:
            if token in self.sessions:
                username, _ = self.sessions[token]
                del self.sessions[token]
                log.info(f"Session manually expired for username='{username}'")
                return True
            return False

    def sweep_expired_sessions(self):
        now = datetime.now(UTC)
        with self.lock:
            expired = [t for t, (_, ts) in self.sessions.items()
                       if now - ts > self.timeout]
            for t in expired:
                state, _ = self.sessions[t]
                username = state.username

                # Send logout notification if transport layer is available
                if self.notification_callback:
                    try:
                        self.notification_callback(
                            username, "You have been logged out due to inactivity.")
                        log.info(
                            f"Logout notification sent to username='{username}'")
                    except (OSError, RuntimeError) as e:
                        log.warning(
                            f"Failed to send logout notification to '{username}': {e}")

                del self.sessions[t]
                log.info(f"Session auto-expired for username='{username}'")

    def _start_sweeper(self):
        def sweep():
            while True:
                threading.Event().wait(60)
                self.sweep_expired_sessions()
        threading.Thread(target=sweep, daemon=True).start()

    async def _user_exists(self, username: str) -> bool:
        try:
            result = await self.db.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,))
            return bool(result)
        except RuntimeError as e:
            log.warning(
                f"Database error while checking username existence: {e}")
            return False

    # --- New helpers for richer state ---

    def get_username(self, token: str) -> str | None:
        state = self.validate_session(token)
        return state.username if state else None

    def get_current_room(self, token: str) -> str | None:
        state = self.validate_session(token)
        return state.current_room if state else None

    def set_current_room(self, token: str, room: str) -> None:
        state = self.validate_session(token)
        if state:
            state.current_room = room

    def get_workflow(self, token: str) -> WorkflowState | None:
        state = self.validate_session(token)
        return state.workflow if state else None

    def set_workflow(self, token: str, wf: WorkflowState) -> None:
        state = self.validate_session(token)
        if state:
            state.workflow = wf

    def clear_workflow(self, token: str) -> None:
        state = self.validate_session(token)
        if state:
            state.workflow = None

    def set_notification_callback(self, callback):
        """Set callback function for sending logout notifications.
        Callback should accept (username: str, message: str) -> None"""
        self.notification_callback = callback
