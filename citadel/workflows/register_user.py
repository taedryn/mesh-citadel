# citadel/workflows/register_user.py

from datetime import datetime, UTC
import string

from citadel.auth.passwords import generate_salt, hash_password
from citadel.commands.responses import CommandResponse, ErrorResponse
from citadel.user.user import User, UserStatus
from citadel.workflows.base import Workflow
from citadel.workflows.registry import register
from citadel.workflows.types import WorkflowPrompt


def is_ascii_username(username: str) -> bool:
    return all(c in string.ascii_letters + string.digits + "_-" for c in username)


@register
class RegisterUserWorkflow(Workflow):
    kind = "register_user"

    async def handle(self, processor, session_id, state, command, wf_state):
        db = processor.db

        # Initialize workflow state
        if "step" not in wf_state:
            wf_state["step"] = 1
            wf_state["data"] = {}

        step = wf_state["step"]
        data = wf_state["data"]

        # Cancellation
        if command.flags.get("cancel_workflow"):
            processor.sessions.clear_workflow(session_id)
            return CommandResponse(
                success=True,
                code="workflow_cancelled",
                text="Registration cancelled. Restarting intro..."
            )

        # Step 1: Username
        if step == 1:
            username = command.response
            if not is_ascii_username(username):
                return ErrorResponse(
                    code="invalid_username",
                    text="Usernames are limited to ASCII characters only"
                )
            if not username or len(username) < 3:
                return ErrorResponse(
                    code="invalid_username",
                    text="Username must be at least 3 characters."
                )
            if await User.username_exists(db, username):
                return ErrorResponse(
                    code="username_taken",
                    text=f"'{username}' is already in use. Please try again."
                )

            # Create provisional user immediately with temporary credentials
            temp_salt = generate_salt()
            temp_password_hash = hash_password("temporary", temp_salt)

            await User.create(
                processor.config,
                db,
                username,
                temp_password_hash,
                temp_salt,
                username,  # Use username as initial display name
                UserStatus.PROVISIONAL
            )

            # Create session for the provisional user
            new_session_id = await processor.sessions.create_session(username)

            data["username"] = username
            data["provisional_session_id"] = new_session_id
            wf_state["step"] = 2

            response = CommandResponse(
                success=True,
                code="workflow_prompt",
                payload=WorkflowPrompt(
                    workflow=self.kind,
                    step=2,
                    prompt="Choose a display name."
                ).__dict__
            )
            # Include the new session ID so transport can switch sessions
            response.session_id = new_session_id
            return response

        # Step 2: Display Name
        if step == 2:
            display_name = command.response
            if not display_name:
                return ErrorResponse(
                    code="invalid_display_name",
                    text="Display name cannot be empty."
                )

            # Update the provisional user's display name
            username = data["username"]
            user = User(db, username)
            await user.load()
            await user.set_display_name(display_name)

            data["display_name"] = display_name
            wf_state["step"] = 3
            return CommandResponse(
                success=True,
                code="workflow_prompt",
                payload=WorkflowPrompt(
                    workflow=self.kind,
                    step=3,
                    prompt="Choose a password.",
                    flags={"password": True}
                ).__dict__
            )

        # Step 3: Password
        if step == 3:
            password = command.response
            if not password or len(password) < 6:
                return ErrorResponse(
                    code="invalid_password",
                    text="Password must be at least 6 characters."
                )

            # Update the provisional user's password
            username = data["username"]
            user = User(db, username)
            await user.load()
            new_salt = generate_salt()
            new_password_hash = hash_password(password, new_salt)
            await user.update_password(new_password_hash, new_salt)
            try:
                terms_req = processor.config.bbs["registration"]["terms_required"]
                if terms_req:
                    terms = processor.config.bbs["registration"]["terms"]
                    wf_state["step"] = 4
                    return CommandResponse(
                        success=True,
                        code="workflow_prompt",
                        payload=WorkflowPrompt(
                            workflow=self.kind,
                            step=4,
                            prompt=f"{terms}\nDo you agree to the terms? (yes/no)"
                        ).__dict__
                    )
                else:
                    log.warning("Terms agreement disabled, skipping")
            except KeyError:
                log.warning("No terms specified, skipping terms agreement")
            wf_state["step"] = 5
            return CommandResponse(
                success=True,
                code="workflow_prompt",
                payload=WorkflowPrompt(
                    workflow=self.kind,
                    step=5,
                    prompt=f"Tell us a bit about yourself."
                ).__dict__
            )

        # Step 4: Terms
        if step == 4:
            agree = command.response.lower() if command.response else ""
            if agree not in ("yes", "y"):
                return ErrorResponse(
                    code="terms_not_accepted",
                    text="You must agree to the terms to continue." 
                )   
            data["agreed"] = True
            wf_state["step"] = 5
            return CommandResponse(
                success=True,                                                  
                code="workflow_prompt",                        
                payload=WorkflowPrompt(
                    workflow=self.kind,
                    step=5,                                       
                    prompt="Tell us a bit about yourself."
                ).__dict__ 
            )   

        # Step 5: Intro
        if step == 5:
            intro = command.response
            data["intro"] = intro
            wf_state["step"] = 6
            return CommandResponse(
                success=True,                                                
                code="workflow_prompt",                        
                payload=WorkflowPrompt(
                    workflow=self.kind,
                    step=6,                                       
                    prompt="Submit registration? (yes/no)"           
                ).__dict__ 
            )    

        # Step 6: Finalize
        if step == 6:
            confirm = command.response.lower() if command.response else ""
            if confirm not in ("yes", "y"):
                return ErrorResponse(
                    code="registration_cancelled",
                    text="Registration not submitted."
                )
            # Activate the provisional user by changing status to active
            username = data["username"]
            user = User(db, username)
            await user.load()
            await user.set_status(UserStatus.ACTIVE)

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
            processor.sessions.clear_workflow(session_id)
            return CommandResponse(
                success=True,
                code="registration_submitted",
                text="Your registration has been submitted for validation."
            )

        return ErrorResponse(
            code="invalid_step",
            text=f"Unknown step {step} in workflow {self.kind}"
        )

