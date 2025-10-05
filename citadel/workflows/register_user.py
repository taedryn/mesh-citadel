# citadel/workflows/register_user.py

from datetime import datetime, UTC
import logging
import string

from citadel.auth.passwords import generate_salt, hash_password
from citadel.auth.permissions import PermissionLevel
from citadel.transport.packets import ToUser
from citadel.user.user import User, UserStatus
from citadel.workflows.base import Workflow, WorkflowState
from citadel.workflows.registry import register

log = logging.getLogger(__name__)


def is_ascii_username(username: str) -> bool:
    return all(c in string.ascii_letters + string.digits + "_-" for c in username)


@register
class RegisterUserWorkflow(Workflow):
    kind = "register_user"

    async def start(self, context):
        """Start the registration workflow by prompting for username."""
        return ToUser(
            session_id=context.session_id,
            text="Choose a username:",
            hints={"type": "text", "workflow": self.kind, "step": 1}
        )

    async def handle(self, context, command):
        db = context.db

        step = context.wf_state.step
        data = context.wf_state.data

        # Cancellation is handled by transport layer, no need to check here

        # Step 1: Username
        if step == 1:
            username = command.strip() if command else ""
            if not is_ascii_username(username):
                return ToUser(
                    session_id=context.session_id,
                    text="Usernames are limited to ASCII characters only",
                    is_error=True,
                    error_code="invalid_username"
                )
            if not username or len(username) < 3:
                return ToUser(
                    session_id=context.session_id,
                    text="Username must be at least 3 characters.",
                    is_error=True,
                    error_code="invalid_username"
                )
            if await User.username_exists(db, username):
                return ToUser(
                    session_id=context.session_id,
                    text=f"'{username}' is already in use. Please try again.",
                    is_error=True,
                    error_code="username_taken"
                )

            # Create provisional user immediately with temporary credentials
            temp_salt = generate_salt()
            temp_password_hash = hash_password("temporary", temp_salt)

            await User.create(
                context.config,
                db,
                username,
                temp_password_hash,
                temp_salt,
                username,  # Use username as initial display name
                UserStatus.PROVISIONAL
            )

            # Update existing session with the new username
            context.session_mgr.mark_username(context.session_id, username)

            data["username"] = username
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=2, data=data)
            )

            return ToUser(
                session_id=context.session_id,
                text="Choose a display name.",
                hints={"type": "text", "workflow": self.kind, "step": 2}
            )

        # Step 2: Display Name
        if step == 2:
            display_name = command
            if not display_name:
                return ToUser(
                    session_id=context.session_id,
                    text="Display name cannot be empty.",
                    is_error=True,
                    error_code="invalid_display_name"
                )

            # Update the provisional user's display name
            username = data["username"]
            user = User(db, username)
            await user.load()
            await user.set_display_name(display_name)

            data["display_name"] = display_name
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=3, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Choose a password.",
                hints={"type": "password", "workflow": self.kind, "step": 3}
            )

        # Step 3: Password
        if step == 3:
            password = command
            if not password or len(password) < 6:
                return ToUser(
                    session_id=context.session_id,
                    text="Password must be at least 6 characters.",
                    is_error=True,
                    error_code="invalid_password"
                )

            # Update the provisional user's password
            username = data["username"]
            user = User(db, username)
            await user.load()
            new_salt = generate_salt()
            new_password_hash = hash_password(password, new_salt)
            await user.update_password(new_password_hash, new_salt)
            try:
                terms_req = context.config.bbs["registration"]["terms_required"]
                if terms_req:
                    terms = context.config.bbs["registration"]["terms"]
                    context.session_mgr.set_workflow(
                        context.session_id,
                        WorkflowState(kind=self.kind, step=4, data=data)
                    )
                    return ToUser(
                        session_id=context.session_id,
                        text=f"{terms}\nDo you agree to the terms?",
                        hints={"type": "choice", "options": [
                            "yes", "no"], "workflow": self.kind, "step": 4}
                    )
                else:
                    log.warning("Terms agreement disabled, skipping")
            except KeyError:
                log.warning("No terms configured, skipping terms agreement")
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=5, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Tell us a bit about yourself.",
                hints={"type": "text", "workflow": self.kind, "step": 5}
            )

        # Step 4: Terms
        if step == 4:
            agree = command.lower() if command else ""
            if agree not in ("yes", "y"):
                return ToUser(
                    session_id=context.session_id,
                    text="You must agree to the terms to continue.",
                    is_error=True,
                    error_code="terms_not_accepted"
                )
            data["agreed"] = True
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=5, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Tell us a bit about yourself.",
                hints={"type": "text", "workflow": self.kind, "step": 5}
            )

        # Step 5: Intro
        if step == 5:
            intro = command
            data["intro"] = intro
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=6, data=data)
            )
            return ToUser(
                session_id=context.session_id,
                text="Submit registration?",
                hints={"type": "choice", "options": [
                    "yes", "no"], "workflow": self.kind, "step": 6}
            )

        # Step 6: Finalize
        if step == 6:
            confirm = command.lower() if command else ""
            if confirm not in ("yes", "y"):
                return ToUser(
                    session_id=context.session_id,
                    text="Registration not submitted.",
                    is_error=True,
                    error_code="registration_cancelled"
                )
            # Activate the provisional user by changing status to active
            username = data["username"]
            user = User(db, username)
            await user.load()
            await user.set_status(UserStatus.ACTIVE)

            # Mark session as fully logged in
            context.session_mgr.mark_logged_in(context.session_id)

            user_count = await User.get_user_count(db)
            print(f"[DEBUG] user count: {user_count}")
            if user_count == 1: # single provisional user entry created
                await user.set_permission_level(PermissionLevel.SYSOP)
                context.session_mgr.clear_workflow(context.session_id)
                return ToUser(
                    session_id=context.session_id,
                    text="Registering you as the Sysop, my first user"
                )
            else:
                # TODO: update transport information
                await db.execute(
                    "INSERT INTO pending_validations "
                    "(username, submitted_at, transport_engine, transport_metadata) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        username,
                        datetime.now(UTC).isoformat(),
                        "unknown",
                        "{}"
                    )
                )
            context.session_mgr.clear_workflow(context.session_id)
            return ToUser(
                session_id=context.session_id,
                text="Your registration has been submitted for validation."
            )

        return ToUser(
            session_id=context.session_id,
            text=f"Unknown step {step} in workflow {self.kind}",
            is_error=True,
            error_code="invalid_step"
        )

    async def cleanup(self, context):
        """Clean up registration workflow when cancelled.

        Removes any provisional user created during registration and
        resets session to anonymous state.
        """
        step = context.wf_state.step
        data = context.wf_state.data

        # If we created a provisional user (step >= 1), remove it
        if step >= 1 and "username" in data:
            username = data["username"]

            # Check if user exists and is provisional
            user = User(context.db, username)
            try:
                await user.load()
            except RuntimeError:
                # User doesn't exist - nothing to clean up
                return

            if user.status == UserStatus.PROVISIONAL:
                try:
                    await context.db.execute(
                        "DELETE FROM users WHERE username = ? AND status = ?",
                        (username, UserStatus.PROVISIONAL.value)
                    )
                    log.info(f"Deleted provisional user '{username}' during workflow cancellation")
                except RuntimeError as e:
                    log.error(f"Failed to delete provisional user '{username}': {e}")
            else:
                log.warning(f"User '{username}' was not provisional during cleanup (status: {user.status})")
                log.warning(f"'{username}' not cleaned up")

            # Reset session to anonymous state
            context.session_mgr.mark_username(context.session_id, None)
            log.info(f"Reset session '{context.session_id}' to anonymous state")
