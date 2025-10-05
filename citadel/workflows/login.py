import logging

from citadel.auth.passwords import authenticate
from citadel.room.room import Room
from citadel.transport.packets import ToUser
from citadel.user.user import User
from citadel.workflows.base import WorkflowState, Workflow
from citadel.workflows.registry import register

log = logging.getLogger(__name__)


@register
class LoginWorkflow(Workflow):
    kind = "login"

    async def handle(self, context, command):
        step = context.wf_state.step
        data = context.wf_state.data

        if step == 1:
            # Prompt for username (called on workflow start or with command=None)
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=2, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Enter your username:",
                hints={"type": "text", "workflow": self.kind, "step": 2}
            )

        elif step == 2:
            # Store username and prompt for password
            data["username"] = command.strip()

            if data["username"].lower() == "new":
                from citadel.workflows import registry as workflow_registry

                # Clear current workflow and start registration workflow
                context.session_mgr.set_workflow(
                    context.session_id,
                    WorkflowState(kind="register_user", step=1, data={}))

                # Get registration workflow and call start()
                handler = workflow_registry.get("register_user")
                if handler:
                    session_state = context.session_mgr.get_session_state(context.session_id)
                    return await handler.start(context)
                else:
                    return ToUser(
                        session_id=context.session_id,
                        text="Error: Registration workflow not found",
                        is_error=True,
                        error_code="workflow_not_found"
                    )

            user_exists = await User.username_exists(context.db,
                                                     data["username"])
            if not user_exists:
                context.session_mgr.set_workflow(
                    context.session_id,
                    WorkflowState(
                        kind=self.kind,
                        step=2,
                        data={}
                    )
                )
                return ToUser(
                    session_id=context.session_id,
                    text=(f"User '{data['username']}' not found. Try again or "
                        "type 'new' to register as a new user.\nEnter your "
                        "username:"),
                    hints={"type": "text", "workflow": self.kind, "step": 2},
                    is_error=True,
                    error_code="invalid_username"
                )

            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=3, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Enter your password:",
                hints={"type": "password", "workflow": self.kind, "step": 3}
            )

        elif step == 3:
            # Attempt authentication
            username = data.get("username")
            password = command

            user = await authenticate(context.db, username, password)
            if not user:
                attempts = data.get("attempts", 0) + 1
                data["attempts"] = attempts

                if attempts >= 3:
                    context.session_mgr.clear_workflow(context.session_id)
                    return ToUser(
                        session_id=context.session_id,
                        text="Too many failed login attempts. Please try again later.",
                        is_error=True,
                        error_code="login_blocked"
                    )

                context.session_mgr.set_workflow(
                    context.session_id,
                    WorkflowState(kind=self.kind, step=2, data=data)
                )
                return ToUser(
                    session_id=context.session_id,
                    text="Login failed. Try again.\nEnter your username:",
                    hints={"type": "text", "workflow": self.kind, "step": 2},
                    is_error=True,
                    error_code="login_failed"
                )

            context.session_mgr.mark_username(context.session_id, username)
            context.session_mgr.mark_logged_in(context.session_id)
            context.session_mgr.clear_workflow(context.session_id)
            state = context.session_mgr.get_session_state(context.session_id)
            room = Room(context.db, context.config, state.current_room)
            await room.load()
            return ToUser(
                session_id=context.session_id,
                text=(f"Welcome, {username}! You are now logged in.\n"
                    f"Current room: {room.name}")
            )

        return ToUser(
            session_id=context.session_id,
            text=f"Invalid login step: {step}",
            is_error=True,
            error_code="invalid_login_step"
        )

    async def cleanup(self, context):
        """Clean up login workflow when cancelled.

        Resets session to anonymous state if username was bound during login attempt.
        """
        data = context.wf_state.data

        # If username was bound to session during login, reset to anonymous
        if "username" in data:
            context.session_mgr.mark_username(context.session_id, None)
            log.info(f"Reset session '{context.session_id}' to anonymous state after login cancellation")
