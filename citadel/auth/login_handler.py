# citadel/auth/login_handler.py

import logging
import time

from citadel.user.user import User
from citadel.commands.responses import CommandResponse, ErrorResponse
from citadel.workflows.types import WorkflowPrompt
from citadel.auth.passwords import verify_password

log = logging.getLogger(__name__)


class LoginHandler:
    def __init__(self, config, db_mgr, session_mgr):
        self.config = config
        self.db = db_mgr
        self.sessions = session_mgr

    async def handle_login(self, transport_info, username_input, password_input):
        username = username_input.strip().lower()

        # Check if user exists
        if not await User.username_exists(self.db, username):
            log.info(f"Unknown username '{username}', starting registration.")
            wf_state = {
                "step": 1,
                "data": {
                    "transport_engine": transport_info.get("engine"),
                    "transport_metadata": transport_info.get("metadata", {})
                }
            }
            self.sessions.set_workflow(None, wf_state)
            return CommandResponse(
                success=True,
                code="workflow_prompt",
                text="Welcome! Let's get you registered.",
                payload=WorkflowPrompt(
                    workflow="register_user",
                    step=1,
                    prompt="Choose a username to begin registration."
                ).__dict__
            )

        # Verify password
        if not await User.verify_password(self.db, username, password_input):
            log.warning(f"Failed login attempt for '{username}'.")
            log.warning("Sleeping 5 seconds to spoil brute-force attacks.")
            time.sleep(5)
            return ErrorResponse(
                code="auth_failed",
                text="Incorrect password. Please try again."
            )

        # Create session
        session_id = await self.sessions.create_session(username)
        log.info(f"User '{username}' authenticated successfully.")
        return CommandResponse(
            success=True,
            code="login_success",
            text=f"Welcome back, {username}.",
            payload={"session_id": session_id}
        )

