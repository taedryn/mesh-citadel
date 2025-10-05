"""
CLI Transport Engine for mesh-citadel.

Provides a simple Unix socket server that accepts connections from CLI clients.
Acts like a "remote mesh node" interface - can only send/receive text without
knowledge of client state.
"""
import asyncio
from datetime import datetime
from dateutil.parser import parse as dateparse
import logging
from pathlib import Path
import traceback
from typing import Dict, Any, Optional

from citadel.config import Config
from citadel.session.manager import SessionManager
from citadel.workflows.base import WorkflowState, WorkflowContext
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser
from citadel.transport.packets import FromUser, FromUserType, ToUser


log = logging.getLogger(__name__)


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

        log.info(f"Starting CLI transport server on {self.socket_path}")

        # Remove existing socket file if it exists
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Start Unix socket server
        self.server = await asyncio.start_unix_server(
            self._handle_client_connection,
            str(self.socket_path)
        )

        self._running = True
        log.info("CLI transport server started")

    async def stop(self) -> None:
        """Stop the CLI transport server."""
        if not self._running:
            return

        log.info("Stopping CLI transport server")

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._running = False
        log.info("CLI transport server stopped")

    async def _handle_client_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a new client connection."""
        self._client_count += 1
        client_id = self._client_count

        log.info(f"CLI client connected: {client_id}")

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
            log.error(f"Error handling CLI client {client_id}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            log.info(f"CLI client disconnected: {client_id}")

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
                log.error(f"Error reading input in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            try:
                line = data.decode('utf-8').strip()
                if not line:
                    continue
            except Exception as e:
                log.error(f"Error decoding data in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

                log.debug(f"Client {client_id} sent: {line}")

            try:
                # Process the command through BBS system
                response, new_session_id, result = await self.process_command(line, session_id, client_id)
                if new_session_id:
                    session_id = new_session_id
            except Exception as e:
                log.error(f"Error processing command in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            try:
                # Response is now a formatted string from process_command
                # A None response is used when entering messages
                if response:
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
                log.error(
                    f"Error sending response to client {client_id}: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

            # Session management is now handled by the session manager directly
            # No need to extract session_id from response payload

    async def process_command(self, command_line: str, session_id: Optional[str], client_id: int) -> tuple[str, Optional[str], Optional[object]]:
        """Process a command through the BBS command system."""

        if session_id:
            result = await self.get_workflow_response(command_line, session_id)
            if result:
                return result

        if command_line.startswith("__workflow:login:"):
            return await self.start_login_workflow(command_line)

        packet = self.build_packet(command_line, session_id)
        if packet is None:
            return self._handle_parse_failure(command_line, session_id)

        result = await self.execute_packet(packet)
        return self.format_result(result)

    async def get_workflow_response(self, command_line: str, session_id: str) -> Optional[tuple[str, Optional[str], Optional[object]]]:
        try:
            wf_state = self.session_manager.get_workflow(session_id)
            if not wf_state:
                return None

            from citadel.workflows import registry as workflow_registry
            handler = workflow_registry.get(wf_state.kind)
            if not handler:
                return ("ERROR: Workflow handler not found", None, None)

            context = WorkflowContext(
                session_id=session_id,
                db=self.command_processor.db,
                config=self.config,
                session_mgr=self.session_manager,
                wf_state=wf_state
            )

            touser_result = await handler.handle(context, command_line)
            response = self._format_response(touser_result)
            return (response, None, touser_result)

        except (KeyError, AttributeError, ValueError) as e:
            log.error(f"Workflow handling failed: {e}")
            traceback.print_exc()
            return ("ERROR: Workflow execution failed", None, None)

    async def start_login_workflow(self, command_line: str) -> tuple[str, Optional[str], Optional[object]]:
        try:
            nodename = command_line.split(":", 2)[2]
            new_session_id = self.session_manager.create_session()
            wf_state = WorkflowState(kind="login", step=1, data={"nodename": nodename})
            self.session_manager.set_workflow(new_session_id, wf_state)

            from citadel.workflows import registry as workflow_registry
            handler = workflow_registry.get("login")
            if not handler:
                touser_result = ToUser(
                    session_id=new_session_id,
                    text="Error: Login workflow not found",
                    is_error=True,
                    error_code="workflow_not_found"
                )
            else:
                context = WorkflowContext(
                    session_id=new_session_id,
                    db=self.command_processor.db,
                    config=self.config,
                    session_mgr=self.session_manager,
                    wf_state=wf_state
                )
                touser_result = await handler.start(context)

            response = self._format_response(touser_result)
            return (response, new_session_id, touser_result)

        except (IndexError, KeyError, AttributeError) as e:
            log.error(f"Login workflow bootstrap failed: {e}")
            traceback.print_exc()
            return ("ERROR: Login workflow failed", None, None)

    def build_packet(self, command_line: str, session_id: Optional[str]) -> Optional[FromUser]:
        try:
            command = self.text_parser.parse_command(command_line)
            log.info(f'parsed command is: {command}')
            if command is False:
                return None

            wf_state = self.session_manager.get_workflow(session_id) if session_id else None
            stripped = command_line.strip()

            if wf_state and stripped.lower() in ['cancel', 'cancel_workflow']:
                return FromUser(
                    session_id=session_id,
                    payload_type=FromUserType.COMMAND,
                    payload=command
                )
            elif wf_state:
                return FromUser(
                    session_id=session_id,
                    payload_type=FromUserType.WORKFLOW_RESPONSE,
                    payload=stripped
                )
            else:
                return FromUser(
                    session_id=session_id or "",
                    payload_type=FromUserType.COMMAND,
                    payload=command
                )

        except (ValueError, AttributeError) as e:
            log.error(f"Packet construction failed: {e}")
            traceback.print_exc()
            return None

    async def execute_packet(self, packet: FromUser) -> Optional[object]:
        try:
            return await self.command_processor.process(packet)
        except RuntimeError as e:
            log.error(f"Command processor runtime error: {e}")
            traceback.print_exc()
            return None
        except Exception as e:
            log.error(f"Command processor failed: {e}")
            traceback.print_exc()
            return None

    def format_result(self, result: Optional[object]) -> tuple[str, Optional[str], Optional[object]]:
        try:
            return (self._format_response(result), None, result)
        except Exception as e:
            log.error(f"Response formatting failed: {e}")
            traceback.print_exc()
            return ("ERROR: Failed to format response", None, None)

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
        timestamp = dateparse(message.timestamp)
        msg_time = timestamp.strftime('%d%b%y %H:%M')
        header = f"[{message.id}] From: {message.display_name} ({message.sender}) - {msg_time}"
        if message.blocked:
            content = "[Message from blocked sender]"
        else:
            content = message.content

        return f"{header}\n{content}"

    @property
    def is_running(self) -> bool:
        """Check if the CLI transport server is running."""
        return self._running
