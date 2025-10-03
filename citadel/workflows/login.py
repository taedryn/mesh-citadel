from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.commands.responses import CommandResponse, ErrorResponse
from citadel.session.state import WorkflowState
from citadel.user.user import User


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
            return CommandResponse(
                success=True,
                code="prompt_username",
                text="Enter your username:"
            )

        elif step == 2:
            # Store username and prompt for password
            data["username"] = command.text.strip()

            if data["username"].lower() == "new":
                processor.sessions.set_workflow(
                    session_id,
                    WorkflowState(kind="register_user", step=1, data={}))
                return CommandResponse(
                    success=True,
                    code="register_user",
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
                return CommandResponse(
                    success=False,
                    code="unknown_user",
                    text=(f"User '{data['username']}' not found. Try again or "
                    "type 'new' to register as a new user.\nEnter your "
                    "username:")
                )

            processor.sessions.set_workflow(
                session_id,
                WorkflowState(kind=self.kind, step=3, data=data)
            )
            return CommandResponse(
                success=True,
                code="prompt_password",
                text="Enter your password:"
            )

        elif step == 3:
            # Attempt authentication
            username = data.get("username")
            password = command.text.strip()

            user = await processor.auth.authenticate(username, password)
            if not user:
                attempts = data.get("attempts", 0) + 1
                data["attempts"] = attempts

                if attempts >= 3:
                    processor.sessions.clear_workflow(session_id)
                    return ErrorResponse(
                        code="login_blocked",
                        text="Too many failed login attempts. Please try again later."
                    )

                processor.sessions.set_workflow(
                    session_id,
                    WorkflowState(kind=self.kind, step=2, data=data)
                )
                return CommandResponse(
                    success=False,
                    code="login_failed",
                    text="Login failed. Try again.\nEnter your username:"
                )

            processor.sessions.mark_username(session_id, username)
            processor.sessions.mark_logged_in(session_id)
            processor.sessions.clear_workflow(session_id)
            return CommandResponse(
                success=True,
                code="login_success",
                text=f"Welcome, {username}! You are now logged in."
            )

        return ErrorResponse(
            code="invalid_login_step",
            text=f"Invalid login step: {step}"
        )

