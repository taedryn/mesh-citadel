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
import sys
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class MeshCitadelCLI:
    """
    CLI client that connects to mesh-citadel BBS via Unix socket.

    Handles terminal interaction and local commands, while passing
    BBS commands to the remote server.
    """

    def __init__(self, socket_path: Path, node_name: Optional[str] = None):
        self.socket_path = socket_path
        self.node_name = node_name
        self.reader = None
        self.writer = None
        self.connected = False
        self.logged_in = False

    async def connect(self) -> bool:
        """Connect to the BBS server via Unix socket."""
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(str(self.socket_path))

            # Read connection acknowledgment
            response = await self.reader.readline()
            if response.strip() == b"CONNECTED":
                self.connected = True
                print("Connected to mesh-citadel BBS")
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
        self.connected = False
        self.logged_in = False

    async def run(self):
        """Run the CLI client main loop."""
        if not await self.connect():
            return

        try:
            # Handle automatic login if node name provided
            if self.node_name:
                await self._auto_login()

            # Main interaction loop
            await self._interaction_loop()

        finally:
            await self.disconnect()

    async def _auto_login(self):
        """Attempt automatic login with provided node name."""
        print(f"Attempting to login as {self.node_name}...")

        # Try login first
        response = await self._send_command(f"user login {self.node_name}")
        if "success" in response.lower() or "logged in" in response.lower():
            self.logged_in = True
            print(f"Logged in as {self.node_name}")
        else:
            # Login failed, ask if user wants to create account
            create = input(f"Node {self.node_name} not found. Create new node? (y/n): ").lower()
            if create == 'y':
                response = await self._send_command(f"user create {self.node_name}")
                if "success" in response.lower() or "created" in response.lower():
                    self.logged_in = True
                    print(f"Created and logged in as {self.node_name}")
                else:
                    print(f"Failed to create node: {response}")

    async def _interaction_loop(self):
        """Main interaction loop for CLI commands."""
        print("\nWelcome to mesh-citadel CLI")
        print("Type '/help' for local commands or 'help' for BBS commands")

        while self.connected:
            try:
                # Show appropriate prompt
                if self.logged_in:
                    prompt = f"{self.node_name}> "
                else:
                    prompt = "guest> "

                command = input(prompt).strip()
                if not command:
                    continue

                # Handle local CLI commands
                if command.startswith('/'):
                    if not await self._handle_local_command(command):
                        break  # Exit requested
                else:
                    # Handle BBS commands
                    if not self.logged_in and not command.startswith('user'):
                        print("You must log in first. Use '/login <nodename>' or '/create <nodename>'")
                        continue

                    response = await self._send_command(command)
                    print(response)

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except EOFError:
                break
            except Exception as e:
                print(f"Error: {e}")

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
            print("  /help           - Show this help")
            print("  /login <node>   - Login as existing node")
            print("  /create <node>  - Create new node")
            print("  /quit or /exit  - Exit CLI")
            print("\nFor BBS commands, type 'help' (without /)")

        elif cmd == 'login':
            if not args:
                print("Usage: /login <nodename>")
                return True

            nodename = args[0]
            response = await self._send_command(f"user login {nodename}")
            if "success" in response.lower() or "logged in" in response.lower():
                self.logged_in = True
                self.node_name = nodename
                print(f"Logged in as {nodename}")
            else:
                print(f"Login failed: {response}")

        elif cmd == 'create':
            if not args:
                print("Usage: /create <nodename>")
                return True

            nodename = args[0]
            response = await self._send_command(f"user create {nodename}")
            if "success" in response.lower() or "created" in response.lower():
                self.logged_in = True
                self.node_name = nodename
                print(f"Created and logged in as {nodename}")
            else:
                print(f"Failed to create node: {response}")

        elif cmd in ['quit', 'exit']:
            print("Goodbye!")
            return False

        else:
            print(f"Unknown local command: /{cmd}")
            print("Type '/help' for available commands")

        return True

    async def _send_command(self, command: str) -> str:
        """Send a command to the BBS server and return the response."""
        try:
            # Send command
            self.writer.write(f"{command}\n".encode('utf-8'))
            await self.writer.drain()

            # Read response
            response = await self.reader.readline()
            return response.decode('utf-8').strip()

        except Exception as e:
            return f"Communication error: {e}"


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