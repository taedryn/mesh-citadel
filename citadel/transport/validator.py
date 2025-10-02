# citadel/transport/validator.py

import logging
from typing import Optional

from citadel.commands.base import BaseCommand
from citadel.commands.responses import ErrorResponse
from citadel.session.manager import SessionManager
from citadel.transport.packets import FromUser, FromUserType, ToUser

log = logging.getLogger(__name__)


class InputValidator:
    """Validates FromUser packets against expected session state."""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def validate(self, packet: FromUser) -> Optional[ToUser]:
        """
        Validate a FromUser packet against session expectations.

        Returns:
            None if validation passes
            ToUser error packet if validation fails
        """
        # Validate session exists
        session_state = self.session_manager.validate_session(packet.session_id)
        if not session_state:
            log.error(f"Input validator: Invalid session ID {packet.session_id}")
            return ToUser(
                session_id=packet.session_id,
                text="Session expired or invalid.",
                is_error=True,
                error_code="invalid_session"
            )

        # Determine expected input type based on session state
        expected_type = self._get_expected_input_type(session_state)

        # Validate payload type matches expectation
        if packet.payload_type != expected_type:
            workflow_info = session_state.workflow.kind if session_state.workflow else 'None'
            log.error(
                f"Transport error: Expected {expected_type} but received {packet.payload_type}. "
                f"Session: {packet.session_id}, Workflow: {workflow_info}"
            )
            return ToUser(
                session_id=packet.session_id,
                text=f"Internal error: Transport sent {packet.payload_type} but session expects {expected_type}.",
                is_error=True,
                error_code="transport_error"
            )

        # Validate payload structure matches type
        validation_error = self._validate_payload_structure(packet.payload_type, packet.payload)
        if validation_error:
            log.error(
                f"Transport error: Invalid payload structure for {packet.payload_type}. "
                f"Session: {packet.session_id}, Error: {validation_error}"
            )
            return ToUser(
                session_id=packet.session_id,
                text=f"Internal error: Invalid {packet.payload_type} format from transport.",
                is_error=True,
                error_code="transport_error"
            )

        return None  # Validation passed

    def _get_expected_input_type(self, session_state) -> FromUserType:
        """Determine what type of input this session expects."""
        if session_state.workflow:
            return FromUserType.WORKFLOW_RESPONSE
        else:
            return FromUserType.COMMAND

    def _validate_payload_structure(self, payload_type: FromUserType, payload: Any) -> Optional[str]:
        """
        Validate that payload has correct structure for its declared type.

        Returns:
            None if valid
            Error message string if invalid
        """
        if payload_type == FromUserType.COMMAND:
            if not isinstance(payload, BaseCommand):
                return f"Expected BaseCommand object, got {type(payload)}"

        elif payload_type == FromUserType.WORKFLOW_RESPONSE:
            if not isinstance(payload, str):
                return f"Expected string response, got {type(payload)}"
            # Note: Empty workflow responses might be valid in some contexts

        else:
            return f"Unknown payload type: {payload_type}"

        return None  # Valid