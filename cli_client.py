#!/usr/bin/env python3
"""
Standalone CLI client for mesh-citadel BBS.

This acts as the "remote mesh node" client that connects to the BBS
via Unix socket. It handles local commands (like /login, /create)
and passes BBS commands through to the server.
"""
import argparse
import asyncio
import logging
import readline
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class MeshCitadelCLI:
    """
    CLI client that connects to mesh-citadel BBS via Unix socket.

    Handles terminal interaction and local commands, while passing
    BBS commands to the remote server.
    """

    def __init__(self, socket_path: Path, node_id: Optional[str] = None):
        self.socket_path = socket_path
        self.node_id = node_id
        self.session_id = None
        self.reader = None
        self.writer = None
        self.socket_connected = False
        self.logged_in = False
        self.welcome = ""
        self.in_workflow = False

        # Configure readline for better CLI experience
        self._setup_readline()
        print("startup complete")

    def _setup_readline(self):
        """Configure readline for better CLI experience."""
        # Enable history
        readline.set_history_length(1000)

        # Set up tab completion for local commands
        readline.set_completer(self._complete_command)
        readline.parse_and_bind("tab: complete")

        # Enable emacs-style line editing (default, but explicit)
        readline.parse_and_bind("set editing-mode emacs")

        # Load command history if it exists
        history_file = Path.home() / ".mesh_citadel_history"
        try:
            readline.read_history_file(str(history_file))
        except FileNotFoundError:
            pass  # No history file yet, that's fine
        except (OSError, PermissionError) as e:
            log.warning(f"Could not load history file: {e}")

        # Save history file path for later
        self.history_file = history_file

    def _complete_command(self, text, state):
        """Tab completion for CLI commands."""
        local_commands = ['/help', '/connect', '/info', '/quit', '/exit']

        # Filter commands that match the current text
        matches = [cmd for cmd in local_commands if cmd.startswith(text)]

        # Return the appropriate match for the current state
        if state < len(matches):
            return matches[state]
        return None

    async def socket_connect(self) -> bool:
        """Connect to the BBS server via Unix socket."""
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(str(self.socket_path))

            # Read connection acknowledgment
            response = await self.reader.readline()
            if response.strip() == b"CONNECTED":
                self.socket_connected = True
                print("Connected to mesh-citadel BBS")

                # welcome message
                welcome = await self.reader.readline()
                self.welcome = welcome.decode('utf-8').strip()

                return True
            else:
                print(f"Unexpected response from server: {response}")
                return False

        except Exception as e:
            print(f"Failed to connect to BBS server: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the BBS server."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.socket_connected = False
        self.logged_in = False

        # Save command history
        if hasattr(self, 'history_file') and self.history_file:
            try:
                readline.write_history_file(str(self.history_file))
            except (OSError, PermissionError) as e:
                log.warning(f"Could not save history file: {e}")

    async def run(self):
        """Run the CLI client main loop."""
        if not await self.socket_connect():
            return

        try:
            # Handle automatic login if node_id name provided
            if self.node_id:
                await self._auto_connect()

            # Main interaction loop
            await self._interaction_loop()

        finally:
            await self.disconnect()

    async def _auto_connect(self):
        response = await self.bbs_connect()
        print(response)

    async def _interaction_loop(self):
        """Main interaction loop for CLI commands."""
        print("\nWelcome to mesh-citadel CLI")
        print("Type '/help' for local commands or 'help' for BBS commands")

        while self.socket_connected:
            try:
                # Get user input with appropriate prompt
                command = input(self._get_prompt()).strip()
                if not command:
                    continue

                # Process command with clean separation of concerns
                if not await self._process_command(command):
                    break  # Exit requested

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except EOFError:
                break
            except Exception as e:
                print(f"Error: {e}")

    def _get_prompt(self) -> str:
        """Get the appropriate prompt based on current state."""
        if self.in_workflow:
            return f"workflow:{self.node_id or 'guest'}> "
        elif self.logged_in:
            return f"command:{self.node_id}> "
        else:
            return "logged_out:guest> "

    async def _process_command(self, command: str) -> bool:
        """
        Process a user command with clean separation of concerns.
        Returns False if exit is requested, True otherwise.
        """
        # 1. Always handle slash commands first (they're always local)
        if command.startswith('/'):
            return await self._handle_local_command(command)

        # 2. Route non-slash commands based on current state
        if self.in_workflow:
            # In workflow mode - send directly to server
            response = await self._send_command(command)
            print(response)
            self._check_login_completion(response)
        elif self.logged_in:
            # Logged in - send BBS command to server
            response = await self._send_command(command)
            print(response)
        else:
            # Not connected/logged in - require connection first
            print("You must connect first. Use '/connect <node_id>'")

        return True

    def _check_login_completion(self, response: str):
        """Check if login workflow just completed successfully."""
        if (not self.in_workflow and  # Just exited workflow mode
            "Welcome" in response and "logged in" in response):
            self.logged_in = True

    async def _handle_local_command(self, command: str) -> bool:
        """
        Handle local CLI commands (starting with /).
        Returns False if exit is requested.
        """
        parts = command[1:].split()
        if not parts:
            return True

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd == 'help':
            print("Local CLI commands:")
            print("  /help             - Show this help")
            print("  /connect <node_id>   - Connect to BBS as a node_id")
            print("  /info             - Connection information")
            print("  /quit             - Exit CLI")
            print("\nFor BBS commands, type them directly after connecting")

        elif cmd == 'connect':
            if not args:
                print("Usage: /connect <node_id>")
                return True

            self.node_id = args[0]
            response = await self.bbs_connect()
            print(self.welcome)
            print(response)

            # Provide user feedback based on resulting state
            if self.in_workflow:
                print("(Entering login workflow - type your username)")
            elif response and "error" not in response.lower():
                print("(Connected - type 'help' for BBS commands)")
            else:
                print("(Connection may have failed - check server status)")

        elif cmd == 'info':
            print(f'Node ID:           {self.node_id}')
            print(f'Session ID:        {self.session_id}')
            print(f'In workflow:       {self.in_workflow}')
            print(f'Logged in:         {self.logged_in}')
            print(f'Socket connected:  {self.socket_connected}')
            # print out connection info
            # * node id
            # * session id
            # * username
            # * last activity time
        elif cmd in ['quit', 'exit']:
            print("Goodbye!")
            return False

        else:
            print(f"Unknown local command: /{cmd}")
            print("Type '/help' for available commands")

        return True

    async def _send_command(self, command: str) -> str:
        """Send a command to the BBS server and return the full response."""
        try:
            # Send command
            self.writer.write(f"{command}\n".encode('utf-8'))
            await self.writer.drain()

            # Read all response lines until a short pause
            lines = []
            while True:
                try:
                    line = await asyncio.wait_for(self.reader.readline(), timeout=0.2)
                    if not line:
                        break
                    decoded = line.decode('utf-8').strip()
                    if decoded.startswith('SESSION_ID:'):
                        self.session_id = decoded.split(': ', 1)[1]
                    elif decoded.startswith('INPUT_MODE:'):
                        mode = decoded.split(': ', 1)[1]
                        self.in_workflow = (mode == 'WORKFLOW')
                    else:
                        lines.append(decoded)
                except asyncio.TimeoutError:
                    break

            return "\n".join(lines)

        except Exception as e:
            return f"Communication error: {e}"

    async def bbs_connect(self) -> None:
        response = await self._send_command(f"__workflow:login:{self.node_id}")
        return response


async def main():
    """Main entry point for CLI client."""
    parser = argparse.ArgumentParser(description="mesh-citadel CLI client")
    parser.add_argument(
        '--socket',
        default='/tmp/mesh-citadel-cli.sock',
        help='Unix socket path for BBS server (default: /tmp/mesh-citadel-cli.sock)'
    )
    parser.add_argument(
        '--node',
        help='Node name to login as automatically'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Check if socket exists
    socket_path = Path(args.socket)
    if not socket_path.exists():
        print(f"BBS server socket not found at {socket_path}")
        print("Make sure the mesh-citadel server is running")
        sys.exit(1)

    # Run CLI client
    cli = MeshCitadelCLI(socket_path, args.node)
    await cli.run()


if __name__ == "__main__":
    asyncio.run(main())
