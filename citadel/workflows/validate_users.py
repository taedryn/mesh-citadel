# citadel/workflows/validate_users.py

from datetime import datetime
from citadel.auth.permissions import PermissionLevel
from citadel.user.user import User, UserStatus
from citadel.workflows.base import Workflow, WorkflowState
from citadel.workflows.registry import register
from citadel.transport.packets import ToUser
import logging

log = logging.getLogger(__name__)


@register
class ValidateUsersWorkflow(Workflow):
    kind = "validate_users"

    async def start(self, context):
        """Start validation workflow - show commands once and first user."""
        commands_text = "USER VALIDATION\nA=approve R=reject S=skip Q=quit\n\n"
        user_info = await self._show_current_user(context)
        user_info.text = commands_text + user_info.text
        return user_info

    async def handle(self, context, command):
        command = command.strip().lower() if command else ""

        if command in ("a", "approve"):
            return await self._approve_current_user(context)
        elif command in ("r", "reject"):
            return await self._reject_current_user(context)
        elif command in ("s", "skip"):
            return await self._skip_current_user(context)
        elif command in ("q", "quit"):
            context.session_mgr.clear_workflow(context.session_id)
            return ToUser(
                session_id=context.session_id,
                text="Validation session ended."
            )
        else:
            return ToUser(
                session_id=context.session_id,
                text="Invalid command. Use A/R/S/Q.",
                is_error=True,
                error_code="invalid_command"
            )

    async def _show_current_user(self, context):
        """Show current user details concisely."""
        data = context.wf_state.data
        pending_users = data.get("pending_users", [])
        current_index = data.get("current_index", 0)

        if current_index >= len(pending_users):
            context.session_mgr.clear_workflow(context.session_id)
            return ToUser(
                session_id=context.session_id,
                text="All users processed!"
            )

        username = pending_users[current_index]

        try:
            user = User(context.db, username)
            await user.load()
        except RuntimeError:
            # User doesn't exist, skip to next
            data["current_index"] = current_index + 1
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=1, data=data)
            )
            return await self._show_current_user(context)

        # Get validation info and intro text
        validation_info = await context.db.execute(
            "SELECT submitted_at, intro_text FROM pending_validations WHERE username = ?",
            (username,)
        )

        if not validation_info:
            # No validation record, skip
            data["current_index"] = current_index + 1
            context.session_mgr.set_workflow(
                context.session_id,
                WorkflowState(kind=self.kind, step=1, data=data)
            )
            return await self._show_current_user(context)

        submitted_at, intro_text = validation_info[0]
        if not intro_text or intro_text.strip() == "":
            intro_text = "No introduction provided."

        text = f"""User {current_index + 1}/{len(pending_users)}
{username} ({user.display_name})
Submitted: {submitted_at}

Introduction:
{intro_text}"""

        return ToUser(
            session_id=context.session_id,
            text=text,
            hints={"type": "choice", "options": ["a", "r", "s", "q"]}
        )

    async def _approve_current_user(self, context):
        """Approve current user."""
        username = await self._get_current_username(context)
        if not username:
            return await self._show_current_user(context)

        try:
            user = User(context.db, username)
            await user.load()
            # Promote from UNVERIFIED to USER permission level
            await user.set_permission_level(PermissionLevel.USER)

            await context.db.execute(
                "DELETE FROM pending_validations WHERE username = ?", (username,)
            )

            # Get validator info for logging
            validator_state = context.session_mgr.get_session_state(context.session_id)
            validator_username = validator_state.username if validator_state else "unknown"
            log.info(f"User '{username}' validated by '{validator_username}' - promoted to USER level")

            # Move to next user
            await self._advance_to_next_user(context)
            next_user = await self._show_current_user(context)
            next_user.text = f"'{username}' approved!\n\n" + next_user.text
            return next_user

        except Exception as e:
            log.error(f"Failed to approve '{username}': {e}")
            return ToUser(
                session_id=context.session_id,
                text=f"Error approving '{username}': {e}",
                is_error=True
            )

    async def _reject_current_user(self, context):
        """Reject current user."""
        username = await self._get_current_username(context)
        if not username:
            return await self._show_current_user(context)

        try:
            await context.db.execute(
                "DELETE FROM users WHERE username = ? AND status = ?",
                (username, UserStatus.ACTIVE.value)  # Users are now ACTIVE/UNVERIFIED, not PROVISIONAL
            )

            await context.db.execute(
                "DELETE FROM pending_validations WHERE username = ?", (username,)
            )

            # Get validator info for logging
            validator_state = context.session_mgr.get_session_state(context.session_id)
            validator_username = validator_state.username if validator_state else "unknown"
            log.info(f"User '{username}' rejected by '{validator_username}' - account deleted")

            # Move to next user
            await self._advance_to_next_user(context)
            next_user = await self._show_current_user(context)
            next_user.text = f"'{username}' rejected.\n\n" + next_user.text
            return next_user

        except Exception as e:
            log.error(f"Failed to reject '{username}': {e}")
            return ToUser(
                session_id=context.session_id,
                text=f"Error rejecting '{username}': {e}",
                is_error=True
            )

    async def _skip_current_user(self, context):
        """Skip to next user."""
        await self._advance_to_next_user(context)
        return await self._show_current_user(context)

    async def _get_current_username(self, context):
        """Get current user's username."""
        data = context.wf_state.data
        pending_users = data.get("pending_users", [])
        current_index = data.get("current_index", 0)

        if current_index >= len(pending_users):
            return None
        return pending_users[current_index]

    async def _advance_to_next_user(self, context):
        """Advance to next user in the list."""
        data = context.wf_state.data
        data["current_index"] = data.get("current_index", 0) + 1
        context.session_mgr.set_workflow(
            context.session_id,
            WorkflowState(kind=self.kind, step=1, data=data)
        )

    async def cleanup(self, context):
        """Clean up validation workflow when cancelled."""
        pass
