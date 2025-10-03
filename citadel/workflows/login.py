import logging

from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.transport.packets import ToUser
from citadel.session.state import WorkflowState
from citadel.user.user import User

log = logging.getLogger(__name__)


@register
class LoginWorkflow(Workflow):
    kind = "login"

    async def handle(self, processor, session_id, state, command, wf_state):
        step = wf_state.step
        data = wf_state.data

        if step == 1:
            # Prompt for username
            processor.sessions.set_workflow(
                session_id,
                WorkflowState(kind=self.kind, step=2, data=data)
            )
            return ToUser(
                session_id=session_id,
                text="Enter your username:",
                hints={"type": "text", "workflow": self.kind, "step": 2}
            )

        elif step == 2:
            # Store username and prompt for password
            data["username"] = command.strip()

            if data["username"].lower() == "new":
                processor.sessions.set_workflow(
                    session_id,
                    WorkflowState(kind="register_user", step=1, data={}))
                return ToUser(
                    session_id=session_id,
                    text="Starting new user registration"
                )

            user_exists = await User.username_exists(processor.db,
                                                     data["username"])
            if not user_exists:
                processor.sessions.set_workflow(
                    session_id,
                    WorkflowState(
                        kind=self.kind,
                        step=2,
                        data={}
                    )
                )
                return ToUser(
                    session_id=session_id,
                    text=(f"User '{data['username']}' not found. Try again or "
                        "type 'new' to register as a new user.\nEnter your "
                        "username:"),
                    hints={"type": "text", "workflow": self.kind, "step": 2},
                    is_error=True,
                    error_code="invalid_username"
                )

            processor.sessions.set_workflow(
                session_id,
                WorkflowState(kind=self.kind, step=3, data=data)
            )
            return ToUser(
                session_id=session_id,
                text="Enter your password:",
                hints={"type": "password", "workflow": self.kind, "step": 3}
            )

        elif step == 3:
            # Attempt authentication
            username = data.get("username")
            password = command

            user = await processor.auth.authenticate(username, password)
            if not user:
                attempts = data.get("attempts", 0) + 1
                data["attempts"] = attempts

                if attempts >= 3:
                    processor.sessions.clear_workflow(session_id)
                    return ToUser(
                        session_id=session_id,
                        text="Too many failed login attempts. Please try again later.",
                        is_error=True,
                        error_code="login_blocked"
                    )

                processor.sessions.set_workflow(
                    session_id,
                    WorkflowState(kind=self.kind, step=2, data=data)
                )
                return ToUser(
                    session_id=session_id,
                    text="Login failed. Try again.\nEnter your username:",
                    hints={"type": "text", "workflow": self.kind, "step": 2},
                    is_error=True,
                    error_code="login_failed"
                )

            processor.sessions.mark_username(session_id, username)
            processor.sessions.mark_logged_in(session_id)
            processor.sessions.clear_workflow(session_id)
            return ToUser(
                session_id=session_id,
                text=f"Welcome, {username}! You are now logged in."
            )

        return ToUser(
            session_id=session_id,
            text=f"Invalid login step: {step}",
            is_error=True,
            error_code="invalid_login_step"
        )

    async def cleanup(self, processor, session_id, wf_state):
        """Clean up login workflow when cancelled.

        Resets session to anonymous state if username was bound during login attempt.
        """
        data = wf_state.data

        # If username was bound to session during login, reset to anonymous
        if "username" in data:
            processor.sessions.mark_username(session_id, None)
            log.info(f"Reset session '{session_id}' to anonymous state after login cancellation")
