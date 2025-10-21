import asyncio
import os
import logging
from pathlib import Path
from contextlib import suppress
from dateutil.parser import parse as dateparse
from typing import Optional

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.transport.packets import FromUser, FromUserType, ToUser
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser
from citadel.session.manager import SessionManager
from citadel.workflows.base import WorkflowContext, WorkflowState
from citadel.workflows import registry as workflow_registry

log = logging.getLogger(__name__)


class CLIFormatter:
    """Handles all CLI-specific formatting logic."""

    def __init__(self, db_manager, config):
        self.db_manager = db_manager
        self.config = config

    def format_response(self, response):
        """Format a response for CLI output."""
        if isinstance(response, list):
            return "\n".join([self._format_single_touser(item) for item in response])
        return self._format_single_touser(response)

    def _format_single_touser(self, touser):
        """Format a single ToUser object."""
        if not touser or not isinstance(touser, ToUser):
            return ""
        if touser.message:
            return self._format_message(touser.message)
        return touser.text or ""

    def _format_message(self, message):
        """Format a BBS message for CLI display."""
        timestamp = dateparse(message.timestamp).strftime('%d%b%y %H:%M')
        header = f"[{message.id}] From: {message.display_name} ({message.sender}) - {timestamp}"
        content = "[Message from blocked sender]" if message.blocked else message.content
        return f"{header}\n{content}"

    def format_session_state(self, session_id: Optional[str], session_manager) -> str:
        """Get current session state as control line for client."""
        if not session_id:
            return "SESSION_STATE: logged_in=false,in_workflow=false,username="

        logged_in = session_manager.is_logged_in(session_id)
        username = session_manager.get_username(session_id) or ""
        workflow_state = session_manager.get_workflow(session_id)
        in_workflow = workflow_state is not None

        return f"SESSION_STATE: logged_in={str(logged_in).lower()},in_workflow={str(in_workflow).lower()},username={username}"

    async def format_prompt(self, session_id: Optional[str], result, session_manager) -> Optional[str]:
        """Generate standard command prompt if appropriate."""
        if not session_id:
            return None

        # Check if user is logged in
        if not session_manager.is_logged_in(session_id):
            return None

        # Check if user has active workflow
        if session_manager.get_workflow(session_id):
            return None

        # Check result hints - only prompt if explicitly requested or no workflow hints
        if hasattr(result, 'hints') and isinstance(result.hints, dict):
            # If workflow-related hints exist but no prompt_next, don't prompt
            workflow_hints = any(key in result.hints for key in [
                                 'type', 'workflow', 'step'])
            if workflow_hints and not result.hints.get('prompt_next', False):
                return None

        # Get current room for prompt
        session_state = session_manager.get_session_state(session_id)
        if not session_state or not session_state.current_room:
            return "What now? (H for help)"

        # Get room name
        from citadel.room.room import Room
        try:
            room = Room(self.db_manager, self.config,
                        session_state.current_room)
            await room.load()
            room_name = room.name
        except Exception:
            room_name = f"Room {session_state.current_room}"

        return f"In {room_name}. What now? (H for help)"


class CommandRouter:
    """Handles routing of commands to appropriate handlers."""

    def __init__(self, text_parser, session_manager, command_processor, config, db_manager):
        self.text_parser = text_parser
        self.session_manager = session_manager
        self.command_processor = command_processor
        self.config = config
        self.db_manager = db_manager

    async def route_command(self, command_line: str, session_id: Optional[str], client_id: int):
        """Route a command to the appropriate handler.

        Returns: (response, new_session_id, result)
        """
        # Check for active workflow first
        if session_id and self.session_manager.get_workflow(session_id):
            return await self._handle_workflow_response(command_line, session_id)

        # Check for login workflow start
        if command_line.startswith("__workflow:login:"):
            return await self._start_login_workflow(command_line)

        # Handle regular commands
        packet = self._build_packet(command_line, session_id)
        if packet is None:
            return self._handle_parse_failure(command_line, session_id)

        result = await self.command_processor.process(packet)
        return (result, None, result)

    async def _handle_workflow_response(self, command_line: str, session_id: str):
        """Handle response within an active workflow."""
        wf_state = self.session_manager.get_workflow(session_id)
        if not wf_state:
            return (None, None, None)

        handler = workflow_registry.get(wf_state.kind)
        context = WorkflowContext(
            session_id=session_id,
            config=self.config,
            db=self.db_manager,
            session_mgr=self.session_manager,
            wf_state=wf_state,
        )
        touser_result = await handler.handle(context, command_line)
        return (touser_result, None, touser_result)

    async def _start_login_workflow(self, command_line: str):
        """Start a new login workflow."""
        try:
            nodename = command_line.split(":", 2)[2]
        except IndexError:
            nodename = "default"

        new_session_id = self.session_manager.create_session()
        wf_state = WorkflowState(
            kind="login",
            step=1,
            data={}
        )
        self.session_manager.set_workflow(new_session_id, wf_state)
        handler = workflow_registry.get("login")
        context = WorkflowContext(
            session_id=new_session_id,
            config=self.config,
            db=self.db_manager,
            session_mgr=self.session_manager,
            wf_state=wf_state,
        )
        touser_result = await handler.start(context)
        return (touser_result, new_session_id, touser_result)

    def _build_packet(self, command_line: str, session_id: Optional[str]) -> Optional[FromUser]:
        """Build a FromUser packet from command line input."""
        command = self.text_parser.parse_command(command_line)
        if command is None:
            return None

        wf_state = self.session_manager.get_workflow(session_id)

        if wf_state and command_line.strip().lower() in ["cancel", "cancel_workflow"]:
            return FromUser(
                session_id=session_id,
                payload_type=FromUserType.COMMAND,
                payload=command
            )
        elif wf_state:
            return FromUser(
                session_id=session_id,
                payload_type=FromUserType.WORKFLOW_RESPONSE,
                payload=command_line.strip()
            )
        else:
            return FromUser(
                session_id=session_id or "",
                payload_type=FromUserType.COMMAND,
                payload=command
            )

    def _handle_parse_failure(self, command_line: str, session_id: Optional[str]):
        """Handle command parsing failures."""
        error_result = ToUser(
            session_id=session_id or "",
            text=f"Unknown command: {command_line.strip()}. Type H for help.",
            is_error=True,
            error_code="unknown_command"
        )
        return (error_result, None, error_result)


class CLIProtocolHandler:
    """Handles CLI protocol-specific logic."""

    def __init__(self, command_router, formatter, session_manager):
        self.command_router = command_router
        self.formatter = formatter
        self.session_manager = session_manager

    async def handle_client_session(self, reader, writer, client_id: int):
        """Handle a complete client session."""
        session_id = None
        listener_task = None

        log.info(f"Starting CLI user session for client {client_id}")

        try:
            while True:
                try:
                    data = await reader.readline()
                    if not data:
                        break
                    line = data.decode("utf-8").strip()
                    if not line:
                        continue
                except (asyncio.IncompleteReadError, UnicodeDecodeError):
                    self._send_line(writer, b"ERROR: Invalid input\n")
                    await writer.drain()
                    continue

                # Route the command
                response, new_session_id, result = await self.command_router.route_command(
                    line, session_id, client_id
                )

                # Handle session changes
                if new_session_id and new_session_id != session_id:
                    session_id = new_session_id
                    self._send_line(writer, f"SESSION_ID: {session_id}\n".encode("utf-8"))
                    self._send_line(writer, b"CONNECTED\n")
                    await writer.drain()

                    # Start message listener for new session
                    if listener_task:
                        listener_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await listener_task

                    listener_task = asyncio.create_task(
                        self._listen_for_messages(writer, session_id)
                    )

                # Send response
                if response:
                    formatted_response = self.formatter.format_response(response)
                    self._send_line(writer, f"{formatted_response}\n".encode("utf-8"))

                if result:
                    # Send session state
                    session_state = self.formatter.format_session_state(session_id, self.session_manager)
                    self._send_line(writer, f"{session_state}\n".encode("utf-8"))

                    # Send prompt if appropriate
                    prompt = await self.formatter.format_prompt(session_id, result, self.session_manager)
                    if prompt:
                        self._send_line(writer, f"{prompt}\n".encode("utf-8"))

                await writer.drain()

        finally:
            if listener_task:
                listener_task.cancel()
                with suppress(asyncio.CancelledError):
                    await listener_task

    async def _listen_for_messages(self, writer, session_id: str):
        """Listen for incoming messages and forward to client."""
        log.info(f'Starting CLI BBS message listener for "{session_id}"')
        state = self.session_manager.get_session_state(session_id)

        while True:
            try:
                message = await state.msg_queue.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._send_line(writer, f"ERROR: {e}\n".encode("utf-8"))
                await writer.drain()
                continue

            # Format and send message
            formatted = self.formatter.format_response(message)
            self._send_line(writer, f"{formatted}\n".encode("utf-8"))

            # Send session state
            session_state = self.formatter.format_session_state(session_id, self.session_manager)
            self._send_line(writer, f"{session_state}\n".encode("utf-8"))

            if message.is_error:
                self._send_line(
                    writer, f"ERROR: {message.error_code or 'Unknown error'}\n".encode("utf-8"))

            await writer.drain()

    def _send_line(self, writer, message):
        """Send a line to the client."""
        writer.write(message)


class CLITransportEngine:
    """Simplified transport engine focused only on network concerns."""

    def __init__(self, socket_path: Path, config: Config,
                 db_manager: DatabaseManager, session_manager: SessionManager):
        self.socket_path = socket_path
        self.config = config
        self.db_manager = db_manager
        self.session_manager = session_manager

        # Create components
        self.formatter = CLIFormatter(db_manager, config)
        self.command_router = CommandRouter(
            TextParser(),
            session_manager,
            CommandProcessor(config, db_manager, session_manager),
            config,
            db_manager
        )
        self.protocol_handler = CLIProtocolHandler(
            self.command_router,
            self.formatter,
            session_manager
        )

        self._client_count = 0
        self._running = False
        self.server = None

    async def start(self) -> None:
        """Start the transport engine."""
        if self._running:
            return
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.server = await asyncio.start_unix_server(
            self._handle_client_connection, str(self.socket_path)
        )
        log.info("CLI transport engine started")
        self._running = True

    async def stop(self) -> None:
        """Stop the transport engine."""
        if not self._running:
            return
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.socket_path.exists():
            self.socket_path.unlink()
        log.info("CLI transport engine stopped")
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if the engine is running."""
        return self._running

    async def _handle_client_connection(self, reader, writer):
        """Handle a new client connection."""
        self._client_count += 1
        client_id = self._client_count
        log.info(f"CLI client connected: {client_id}")

        # Send initial connection message
        writer.write(b"CONNECTED\n")
        await writer.drain()

        # Delegate to protocol handler
        await self.protocol_handler.handle_client_session(reader, writer, client_id)