from datetime import datetime, timedelta, UTC
import logging
import secrets
import threading

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.room.room import SystemRoomIDs
from citadel.session.state import SessionState, WorkflowState

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class SessionManager:
    def __init__(self, config: "Config", db: DatabaseManager):
        self.timeout = timedelta(seconds=config.auth["session_timeout"])
        self.db = db
        self.sessions = {}  # session_id -> (SessionState, last_active: datetime)
        self.lock = threading.Lock()
        self.notification_callback = None  # Will be set by transport layer
        self._start_sweeper()

    def create_session_state(self, username: str) -> SessionState:
        return SessionState(username=username,
                            current_room=SystemRoomIDs.LOBBY_ID)

    async def create_session(self, username: str) -> str:
        if not await self._user_exists(username):
            raise ValueError(f"Username '{username}' does not exist")

        session_id = secrets.token_urlsafe(24)
        now = datetime.now(UTC)
        state = self.create_session_state(username)
        with self.lock:
            self.sessions[session_id] = (state, now)
        log.info(f"Session created for username='{username}'")
        return session_id

    def validate_session(self, session_id: str) -> SessionState | None:
        with self.lock:
            data = self.sessions.get(session_id)
            if not data:
                return None
            state, _ = data
            return state

    def touch_session(self, session_id: str) -> bool:
        now = datetime.now(UTC)
        with self.lock:
            if session_id not in self.sessions:
                return False
            state, _ = self.sessions[session_id]
            self.sessions[session_id] = (state, now)
            return True

    def expire_session(self, session_id: str) -> bool:
        with self.lock:
            if session_id in self.sessions:
                username, _ = self.sessions[session_id]
                del self.sessions[session_id]
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

    def get_username(self, session_id: str) -> str | None:
        state = self.validate_session(session_id)
        return state.username if state else None

    def get_current_room(self, session_id: str) -> str | None:
        state = self.validate_session(session_id)
        return state.current_room if state else None

    def set_current_room(self, session_id: str, room: str) -> None:
        state = self.validate_session(session_id)
        if state:
            state.current_room = room

    def get_workflow(self, session_id: str) -> WorkflowState | None:
        state = self.validate_session(session_id)
        return state.workflow if state else None

    def set_workflow(self, session_id: str, wf: WorkflowState) -> None:
        state = self.validate_session(session_id)
        if state:
            state.workflow = wf

    def clear_workflow(self, session_id: str) -> None:
        state = self.validate_session(session_id)
        if state:
            state.workflow = None

    def set_notification_callback(self, callback):
        """Set callback function for sending logout notifications.
        Callback should accept (username: str, message: str) -> None"""
        self.notification_callback = callback

    # --- helpers for working with the pre-login state ---

    def create_provisional_session(self) -> str:
        """Create a session not yet tied to a user."""
        session_id = secrets.token_urlsafe(24)
        state = SessionState(username=None, current_room=None, logged_in=False)
        with self.lock:
            self.sessions[session_id] = (state, datetime.now(UTC))
        log.info(f"Provisional session created: {session_id}")
        return session_id

    def mark_username(self, session_id: str, username: str):
        """Bind a username to a session once validated."""
        state = self.validate_session(session_id)
        if state:
            state.username = username
            log.info(f"Username '{username}' bound to session '{session_id}'")

    def mark_logged_in(self, session_id: str):
        """Mark a session as authenticated."""
        state = self.validate_session(session_id)
        if state:
            state.logged_in = True
            log.info(f"Session '{session_id}' marked as logged in")

