import asyncio
from datetime import datetime, timedelta, UTC
import logging
import secrets
import threading

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.room.room import SystemRoomIDs
from citadel.session.state import SessionState
from citadel.workflows.base import WorkflowState
from citadel.transport.packets import ToUser

log = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, config: "Config", db: DatabaseManager):
        self.timeout = timedelta(seconds=config.auth["session_timeout"])
        self.db = db
        # session_id -> (SessionState, last_active: datetime)
        self.sessions = {}
        self.lock = threading.Lock()
        self.notification_callback = None  # Will be set by transport layer
        self._start_sweeper()

    def create_session(self, node_id: str=None) -> str:
        """Create a session not yet tied to a user."""
        session_id = secrets.token_urlsafe(24)
        state = SessionState(
            username=None,
            current_room=SystemRoomIDs.LOBBY_ID,
            logged_in=False,
            msg_queue=asyncio.Queue(),
            node_id=node_id
        )
        with self.lock:
            self.sessions[session_id] = (state, datetime.now(UTC))
        log.info(f"Provisional session created: {session_id}")
        return session_id

    def get_session_state(self, session_id: str) -> SessionState | None:
        with self.lock:
            data = self.sessions.get(session_id)
            if not data:
                return None
            state, _ = data
            return state

    def get_session_by_node_id(self, node_id: str) -> str:
        """ retrieve the session_id baseed on node_id """
        for session_id, info in self.sessions.items():
            state = info[0]
            if state.node_id == node_id:
                return session_id
        return None

    def touch_session(self, session_id: str) -> bool:
        now = datetime.now(UTC)
        with self.lock:
            if session_id not in self.sessions:
                return False
            state, _ = self.sessions[session_id]
            self.sessions[session_id] = (state, now)
            return True

    def is_expired(self, session_id: str) -> bool:
        """ check if a session is expired or not """
        timeout = self.config.auth["session_timeout"]
        if session_id in self.sessions:
            _, last_activity = self.sessions[session_id]
            if (datetime.utcnow() - last_activity) > timedelta(seconds=timeout):
                return True # session registered, expired
            return False # session registered, not expired
        return True # session isn't registered

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
            for session_id in expired:
                state, _ = self.sessions[session_id]
                username = state.username
                node_id = state.node_id

                # Send logout notification if transport layer is available
                if self.notification_callback and node_id:
                    try:
                        self.notification_callback(
                            session_id, "You have been logged out due to inactivity. Send any message to reconnect.")
                        log.info(
                            f"Logout notification sent to username='{username}'")
                    except (OSError, RuntimeError) as e:
                        log.warning(
                            f"Failed to send logout notification to '{username}': {e}")

                del self.sessions[session_id]
                log.info(f"Session auto-expired for username='{username}'")

    def _start_sweeper(self):
        def sweep():
            while True:
                threading.Event().wait(60)
                self.sweep_expired_sessions()
        threading.Thread(target=sweep, daemon=True).start()

    # --- Commands for communicating to sessions ---

    async def send_msg(self, session_id: str, message: "ToUser") -> int:
        """ add a message to the outbound message queue.  returns the
        number of items currently in the outbound queue. """
        if not isinstance(message, ToUser):
            raise ValueError("Sent messages must be ToUser type")
        state = self.get_session_state(session_id)
        log.info(f'adding message to queue: {message}')
        await state.msg_queue.put(message)
        return state.msg_queue.qsize()

    # --- New helpers for richer state ---

    def get_username(self, session_id: str) -> str | None:
        state = self.get_session_state(session_id)
        return state.username if state else None

    def get_current_room(self, session_id: str) -> str | None:
        state = self.get_session_state(session_id)
        return state.current_room if state else None

    def set_current_room(self, session_id: str, room: int) -> None:
        state = self.get_session_state(session_id)
        if state:
            state.current_room = room

    def get_workflow(self, session_id: str) -> WorkflowState | None:
        state = self.get_session_state(session_id)
        return state.workflow if state else None

    def set_workflow(self, session_id: str, wf: WorkflowState) -> None:
        state = self.get_session_state(session_id)
        if state:
            state.workflow = wf

    def clear_workflow(self, session_id: str) -> None:
        state = self.get_session_state(session_id)
        if state:
            state.workflow = None

    async def start_login_workflow(self, config, db, session_id: str = None) -> tuple[str, "ToUser | None"]:
        """Start login workflow on existing or new session.

        Args:
            config: Configuration manager
            db: Database manager
            session_id: If provided, reuse this session ID; otherwise create new one

        Returns a tuple of (session_id, login_prompt_touser).
        The login_prompt_touser will be None if the login workflow couldn't be started.

        This is a common pattern used when transitioning users back to login state
        (e.g., after logout, workflow cancellation, etc.)
        """
        from citadel.workflows.base import WorkflowState, WorkflowContext
        from citadel.workflows import registry as workflow_registry
        from citadel.transport.packets import ToUser

        # Use existing session or create new one
        if session_id:
            # Reset existing session to anonymous state
            self.mark_logged_in(session_id, False)
            self.mark_username(session_id, None)
            self.clear_workflow(session_id)
            target_session_id = session_id
        else:
            # Create new session
            target_session_id = self.create_session()

        # Set up login workflow
        login_wf_state = WorkflowState(kind="login", step=1, data={})
        self.set_workflow(target_session_id, login_wf_state)

        # Get the login prompt
        login_handler = workflow_registry.get("login")
        if login_handler:
            try:
                login_context = WorkflowContext(
                    session_id=target_session_id,
                    config=config,
                    db=db,
                    session_mgr=self,
                    wf_state=login_wf_state
                )
                login_prompt = await login_handler.start(login_context)
                login_prompt.session_id = target_session_id
                return target_session_id, login_prompt
            except Exception as e:
                log.warning(f"Failed to start login workflow: {e}")
                return target_session_id, None
        else:
            log.warning("Login workflow handler not found")
            return target_session_id, None

    def set_notification_callback(self, callback):
        """Set callback function for sending logout notifications.
        Callback should accept (session_id: str, message: str) -> None"""
        self.notification_callback = callback

    # --- helpers for working with the pre-login state ---

    def mark_username(self, session_id: str, username: str):
        """Bind a username to a session once validated."""
        state = self.get_session_state(session_id)
        if state:
            state.username = username
            log.info(f"Username '{username}' bound to session '{session_id}'")

    def mark_logged_in(self, session_id: str, logged_in: bool = True):
        """Mark a session as authenticated or unauthenticated."""
        state = self.get_session_state(session_id)
        if state:
            state.logged_in = logged_in
            status = "logged in" if logged_in else "logged out"
            log.info(f"Session '{session_id}' marked as {status}")

    def is_logged_in(self, session_id: str):
        """Return True if the session is logged in"""
        state = self.get_session_state(session_id)
        if state:
            return state.logged_in
        return False
