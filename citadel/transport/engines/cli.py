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

class CLITransportEngine:
    def __init__(self, socket_path: Path, config: Config, 
                 db_manager: DatabaseManager, session_manager: SessionManager):
        self.socket_path = socket_path
        self.config = config
        self.db_manager = db_manager
        self.session_manager = session_manager
        self.command_processor = CommandProcessor(config, db_manager,
                                                  session_manager)
        self.text_parser = TextParser()
        self._client_count = 0
        self._running = False
        self.server = None

    async def start(self) -> None:
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
        return self._running

    async def _handle_client_connection(self, reader, writer):
        self._client_count += 1
        client_id = self._client_count
        log.info(f"CLI client connected: {client_id}")
        self.send_line(writer, b"CONNECTED\n")
        await writer.drain()
        await self._handle_client_session(reader, writer, client_id)

    async def _handle_client_session(self, reader, writer, client_id):
        session_id = None
        listener_task = None

        log.info(f"Starting CLI user listener for '{session_id}'")

        while True:
            try:
                data = await reader.readline()
                if not data:
                    break
                line = data.decode("utf-8").strip()
                if not line:
                    continue
            except (asyncio.IncompleteReadError, UnicodeDecodeError):
                self.send_line(writer, b"ERROR: Invalid input\n")
                await writer.drain()
                continue

            response, new_session_id, result = await self.process_command(
                line,
                session_id,
                client_id
            )

            if new_session_id and new_session_id != session_id:
                session_id = new_session_id
                self.send_line(writer, f"SESSION_ID: {session_id}\n".encode("utf-8"))
                self.send_line(writer, b"CONNECTED\n")
                await writer.drain()
                listener_task = asyncio.create_task(
                    self._listen_for_messages(
                        writer,
                        session_id
                    )
                )

            if response:
                self.send_line(writer, f"{response}\n".encode("utf-8"))
            if result:
                # Send authoritative session state instead of inferred input mode
                session_state = self._get_session_state_line(session_id)
                self.send_line(writer, f"{session_state}\n".encode("utf-8"))

                # Send standard prompt if appropriate
                prompt = await self._get_standard_prompt(session_id, result)
                if prompt:
                    self.send_line(writer, f"{prompt}\n".encode("utf-8"))
            await writer.drain()

        if listener_task:
            listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await listener_task

    async def _listen_for_messages(self, writer, session_id):
        log.info(f'Starting CLI BBS message listener for "{session_id}"')
        state = self.session_manager.get_session_state(session_id)
        while True:
            try:
                message = await state.msg_queue.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.send_line(writer, f"ERROR: {e}\n".encode("utf-8"))
                await writer.drain()
                continue

            formatted = self._format_single_touser(message)
            self.send_line(writer, f"{formatted}\n".encode("utf-8"))

            # Send authoritative session state for every message
            session_state = self._get_session_state_line(session_id)
            self.send_line(writer, f"{session_state}\n".encode("utf-8"))
            if message.is_error:
                self.send_line(writer, f"ERROR: {message.error_code or 'Unknown error'}\n".encode("utf-8"))
            await writer.drain()

    async def process_command(self, command_line, session_id, client_id):
        if session_id and self.session_manager.get_workflow(session_id):
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

    async def get_workflow_response(self, command_line, session_id):
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
        return (self._format_response(touser_result), None, touser_result)

    async def start_login_workflow(self, command_line):
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
        return (self._format_response(touser_result), new_session_id, touser_result)

    def build_packet(self, command_line, session_id):
        command = self.text_parser.parse_command(command_line)
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

    def send_line(self, writer, message):
        writer.write(message)

    async def execute_packet(self, packet):
        return await self.command_processor.process(packet)

    def format_result(self, result):
        return (self._format_response(result), None, result)

    def _handle_parse_failure(self, command_line, session_id):
        error_result = ToUser(
            session_id=session_id or "",
            text=f"Unknown command: {command_line.strip()}. Type H for help.",
            is_error=True,
            error_code="unknown_command"
        )
        return (self._format_response(error_result), None, error_result)

    def _format_response(self, response):
        if isinstance(response, list):
            return "\n".join([self._format_single_touser(item) for item in response])
        return self._format_single_touser(response)

    def _format_single_touser(self, touser):
        if not touser or not isinstance(touser, ToUser):
            return ""
        if touser.message:
            return self._format_message(touser.message)
        return touser.text or ""

    def _format_message(self, message):
        timestamp = dateparse(message.timestamp).strftime('%d%b%y %H:%M')
        header = f"[{message.id}] From: {message.display_name} ({message.sender}) - {timestamp}"
        content = "[Message from blocked sender]" if message.blocked else message.content
        return f"{header}\n{content}"

    def _get_input_mode(self, touser):
        if touser.hints and "workflow" in touser.hints:
            return "WORKFLOW"
        return "COMMAND"

    def _get_session_state_line(self, session_id: Optional[str]) -> str:
        """Get current session state as control line for client."""
        if not session_id:
            return "SESSION_STATE: logged_in=false,in_workflow=false,username="

        logged_in = self.session_manager.is_logged_in(session_id)
        username = self.session_manager.get_username(session_id) or ""
        workflow_state = self.session_manager.get_workflow(session_id)
        in_workflow = workflow_state is not None

        return f"SESSION_STATE: logged_in={str(logged_in).lower()},in_workflow={str(in_workflow).lower()},username={username}"

    async def _get_standard_prompt(self, session_id: Optional[str], result) -> Optional[str]:
        """Generate standard command prompt if appropriate.

        Returns prompt if:
        - User is logged in
        - No active workflow
        - Result hints suggest prompting (prompt_next=True) OR no workflow hints
        """
        if not session_id:
            return None

        # Check if user is logged in
        if not self.session_manager.is_logged_in(session_id):
            return None

        # Check if user has active workflow
        if self.session_manager.get_workflow(session_id):
            return None

        # Check result hints - only prompt if explicitly requested or no workflow hints
        if hasattr(result, 'hints') and isinstance(result.hints, dict):
            # If workflow-related hints exist but no prompt_next, don't prompt
            workflow_hints = any(key in result.hints for key in ['type', 'workflow', 'step'])
            if workflow_hints and not result.hints.get('prompt_next', False):
                return None

        # Get current room for prompt
        session_state = self.session_manager.get_session_state(session_id)
        if not session_state or not session_state.current_room:
            return "What now? (H for help)"

        # Get room name
        from citadel.room.room import Room
        try:
            room = Room(self.db_manager, self.config, session_state.current_room)
            await room.load()
            room_name = room.name
        except Exception:
            room_name = f"Room {session_state.current_room}"

        return f"In {room_name}. What now? (H for help)"

