"""
CLI Transport Engine for mesh-citadel.

Provides a simple Unix socket server that accepts connections from CLI clients.
Acts like a "remote mesh node" interface - can only send/receive text without
knowledge of client state.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from citadel.config import Config
from citadel.session.manager import SessionManager
from citadel.session.state import WorkflowState
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser
from citadel.transport.packets import FromUser, FromUserType, ToUser


logger = logging.getLogger(__name__)


class CLITransportEngine:
    """
    Simple CLI transport engine that provides Unix socket communication.

    This engine accepts connections from standalone CLI clients and passes
    text commands to the BBS command processor. It models the interaction
    between the BBS and remote mesh nodes.
    """

    def __init__(self, socket_path: Path, config: Config, db_manager, session_manager):
        self.socket_path = socket_path
        self.config = config
        self.server = None
        self.session_manager = session_manager
        self.command_processor = CommandProcessor(
            config, db_manager, session_manager)
        self.text_parser = TextParser()
        self._running = False
        self._client_count = 0

    async def start(self) -> None:
        """Start the CLI transport server."""
        if self._running:
            return

        logger.info(f"Starting CLI transport server on {self.socket_path}")

        # Remove existing socket file if it exists
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Start Unix socket server
        self.server = await asyncio.start_unix_server(
            self._handle_client_connection,
            str(self.socket_path)
        )

        self._running = True
        logger.info("CLI transport server started")

    async def stop(self) -> None:
        """Stop the CLI transport server."""
        if not self._running:
            return

        logger.info("Stopping CLI transport server")

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._running = False
        logger.info("CLI transport server stopped")

    async def _handle_client_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a new client connection."""
        self._client_count += 1
        client_id = self._client_count

        logger.info(f"CLI client connected: {client_id}")

        try:
            # Send connection acknowledgment
            writer.write(b"CONNECTED\n")
            await writer.drain()

            # Send welcome message from config
            welcome = self.config.bbs.get(
                "welcome_message", "Welcome to Mesh-Citadel.")
            writer.write(f"{welcome}\n".encode('utf-8'))
            await writer.drain()

            # Handle client session
            await self._handle_client_session(reader, writer, client_id)

        except Exception as e:
            logger.error(f"Error handling CLI client {client_id}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.info(f"CLI client disconnected: {client_id}")

    async def _handle_client_session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_id: int) -> None:
        """Handle the text communication session with a client."""
        session_id = None

        while True:
            try:
                # Read line from client
                data = await reader.readline()
                if not data:
                    break
            except Exception as e:
                import pdb
                pdb.set_trace()
                logger.error(f"Error in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            try:
                line = data.decode('utf-8').strip()
                if not line:
                    continue
            except Exception as e:
                import pdb
                pdb.set_trace()
                logger.error(f"Error in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

                logger.debug(f"Client {client_id} sent: {line}")

            try:
                # Process the command through BBS system
                response, new_session_id, result = await self._process_command(line, session_id, client_id)
                if new_session_id:
                    session_id = new_session_id
            except Exception as e:
                import pdb
                pdb.set_trace()
                logger.error(f"Error in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            try:
                # Response is now a formatted string from _process_command
                response_line = f"{response}\n"
                writer.write(response_line.encode('utf-8'))

                # If a new session was created, send the session_id to the client
                if new_session_id:
                    session_id_line = f"SESSION_ID: {new_session_id}\n"
                    writer.write(session_id_line.encode('utf-8'))

                # Send input mode based on the ToUser packet
                if result:
                    input_mode = self._get_input_mode(result)
                    mode_line = f"INPUT_MODE: {input_mode}\n"
                    writer.write(mode_line.encode('utf-8'))

                await writer.drain()

            except Exception as e:
                logger.error(
                    f"Error sending response to client {client_id}: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            # Session management is now handled by the session manager directly
            # No need to extract session_id from response payload

    async def _process_command(self, command_line: str, session_id: Optional[str], client_id: int) -> tuple[str, Optional[str], Optional[object]]:
        """Process a command through the BBS command system."""
        try:
            # Check if session is in a workflow and route input there
            if session_id:
                workflow_state = self.session_manager.get_workflow(session_id)
                if workflow_state:
                    from citadel.workflows import registry as workflow_registry
                    from citadel.session.state import SessionState

                    handler = workflow_registry.get(workflow_state.kind)
                    if handler:
                        # Get session state
                        session_state = SessionState(
                            username=self.session_manager.get_username(session_id),
                            current_room=None,  # TODO: get from session
                            logged_in=self.session_manager.is_logged_in(session_id)
                        )

                        touser_result = await handler.handle(
                            self.command_processor, session_id, session_state,
                            command_line, workflow_state
                        )
                        response = self._format_response(touser_result)
                        return (response, None, touser_result)

            if command_line.startswith("__workflow:login:"):
                from citadel.workflows import registry as workflow_registry
                from citadel.session.state import SessionState

                nodename = command_line.split(":", 2)[2]
                new_session_id = self.session_manager.create_session()

                # Create workflow state
                wf_state = WorkflowState(kind="login", step=1, data={"nodename": nodename})
                self.session_manager.set_workflow(new_session_id, wf_state)

                # Get workflow handler and call start()
                handler = workflow_registry.get("login")
                if handler:
                    # Create session state for workflow
                    session_state = SessionState(
                        username=None,
                        current_room=None,
                        logged_in=False
                    )

                    touser_result = await handler.start(self.command_processor, new_session_id, session_state, wf_state)
                else:
                    touser_result = ToUser(
                        session_id=new_session_id,
                        text="Error: Login workflow not found",
                        is_error=True,
                        error_code="workflow_not_found"
                    )

                response = self._format_response(touser_result)
                return (response, new_session_id, touser_result)

            # Create appropriate FromUser packet based on context
            if session_id:
                workflow_state = self.session_manager.get_workflow(session_id)
                if workflow_state:
                    # User is in a workflow - check for special commands first
                    stripped_input = command_line.strip().lower()
                    if stripped_input in ['cancel', 'cancel_workflow']:
                        # Allow canceling workflows with special command
                        command = self.text_parser.parse_command(command_line)
                        if command is False:
                            return self._handle_parse_failure(command_line, session_id)

                        packet = FromUser(
                            session_id=session_id,
                            payload_type=FromUserType.COMMAND,
                            payload=command
                        )
                    else:
                        # Treat all other input as workflow response - send raw string
                        packet = FromUser(
                            session_id=session_id,
                            payload_type=FromUserType.WORKFLOW_RESPONSE,
                            payload=command_line.strip()
                        )
                else:
                    # Not in workflow, parse as command
                    command = self.text_parser.parse_command(command_line)
                    if command is False:
                        return self._handle_parse_failure(command_line, session_id)

                    packet = FromUser(
                        session_id=session_id,
                        payload_type=FromUserType.COMMAND,
                        payload=command
                    )
            else:
                # No session, parse as command
                command = self.text_parser.parse_command(command_line)

                # Handle parser failure - command not recognized
                if command is False:
                    return self._handle_parse_failure(command_line, session_id)

                packet = FromUser(
                    session_id="",  # No session yet
                    payload_type=FromUserType.COMMAND,
                    payload=command
                )

            # Process through command processor with new packet interface
            result = await self.command_processor.process(packet)

            # Return the formatted result (no session change for regular commands)
            return (self._format_response(result), None, result)

        except Exception as e:
            logger.error(
                f"Error processing command '{command_line}' for client {client_id}: {e}")
            return (f"ERROR: Command processing failed - {str(e)}", None, None)

    def _format_response(self, response):
        """Format ToUser response(s) for CLI display."""
        if isinstance(response, list):
            # Handle list[ToUser] for multiple items (like messages)
            formatted_lines = []
            for item in response:
                formatted_lines.append(self._format_single_touser(item))
            return "\n".join(formatted_lines)
        else:
            # Handle single ToUser packet
            return self._format_single_touser(response)

    def _format_single_touser(self, touser):
        """Format a single ToUser packet for display."""
        if not hasattr(touser, 'text'):
            # Fallback for non-ToUser responses
            return str(touser)

        # If there's a message field, format it as a BBS message
        if hasattr(touser, 'message') and touser.message:
            return self._format_message(touser.message)

        # Otherwise, just return the text field
        return touser.text if touser.text else ""

    def _get_input_mode(self, touser):
        """Determine input mode from ToUser packet hints."""
        if hasattr(touser, 'hints') and touser.hints:
            if 'workflow' in touser.hints:
                return "WORKFLOW"
        return "COMMAND"

    def _handle_parse_failure(self, command_line: str, session_id: Optional[str]) -> tuple[str, None, ToUser]:
        """Handle command parser failure by returning appropriate error response."""
        error_result = ToUser(
            session_id=session_id or "",
            text=f"Unknown command: {command_line.strip()}. Type H for help.",
            is_error=True,
            error_code="unknown_command"
        )
        return (self._format_response(error_result), None, error_result)

    def _format_message(self, message):
        """Format a MessageResponse object for BBS-style display."""
        # Format: "From: DisplayName (username) - Timestamp\nContent"
        header = f"From: {message.display_name} ({message.sender}) - {message.timestamp}"
        if message.blocked:
            content = "[Message from blocked sender]"
        else:
            content = message.content

        return f"{header}\n{content}"

    @property
    def is_running(self) -> bool:
        """Check if the CLI transport server is running."""
        return self._running
