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
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser


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
        self.command_processor = CommandProcessor(config, db_manager, session_manager)
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
        session = None

        while True:
            try:
                # Read line from client
                data = await reader.readline()
                if not data:
                    break

                line = data.decode('utf-8').strip()
                if not line:
                    continue

                logger.debug(f"Client {client_id} sent: {line}")

                # Process the command through BBS system
                response = await self._process_command(line, session, client_id)

                # Send response back to client
                response_line = f"{response}\n"
                writer.write(response_line.encode('utf-8'))
                await writer.drain()

                # Update session if command result includes session info
                if hasattr(response, 'session'):
                    session = response.session

            except Exception as e:
                logger.error(f"Error in client {client_id} session: {e}")
                error_msg = f"ERROR: {str(e)}\n"
                writer.write(error_msg.encode('utf-8'))
                await writer.drain()

    async def _process_command(self, command_line: str, session: Optional[Any], client_id: int) -> str:
        """Process a command through the BBS command system."""
        try:
            # Parse the command
            command = self.text_parser.parse(command_line)

            # Process through command processor
            result = await self.command_processor.process_command(command, session)

            # Return the result message
            return result.message

        except Exception as e:
            logger.error(f"Error processing command '{command_line}' for client {client_id}: {e}")
            return f"ERROR: Command processing failed - {str(e)}"

    @property
    def is_running(self) -> bool:
        """Check if the CLI transport server is running."""
        return self._running