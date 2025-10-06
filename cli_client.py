#!/usr/bin/env python3
"""
Async CLI client for mesh-citadel BBS using prompt_toolkit.
This replaces the synchronous cli_client.py with a modern async architecture.
"""

import asyncio
import sys
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.containers import WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style


class AsyncMeshCitadelCLI:
    def __init__(self, socket_path: Path, node_id: str = None):
        self.socket_path = socket_path
        self.node_id = node_id

        # Connection state
        self.socket_connected = False
        self.reader = None
        self.writer = None
        self.session_id = None

        # BBS state (will be updated by SESSION_STATE messages)
        self.logged_in = False
        self.in_workflow = False
        self.username = ""
        self.password_mode = False  # True when current workflow input should be masked

        # Create UI components
        self._setup_ui()

    def _setup_ui(self):
        """Create the prompt_toolkit UI layout."""

        # Message display area (top, scrollable, read-only, not focusable)
        self.message_area = TextArea(
            text="Welcome to mesh-citadel CLI (async version)\n"
                 "Type '/help' for local commands\n\n",
            read_only=True,
            focusable=False,  # Prevent focus from going here
            scrollbar=True,
            wrap_lines=True,
        )

        # Status bar showing connection and session state
        self.status_control = FormattedTextControl(
            text=self._get_status_text
        )

        # Command input area (minimal prompt, just a cursor)
        self.input_area = TextArea(
            height=1,
            prompt="> ",  # Minimal prompt like meshcore
            multiline=False,
            wrap_lines=False,
            password=False,  # Will be toggled for password input
        )

        # Create layout with message area, status bar, and input
        root_container = HSplit([
            # Main message area (expandable)
            self.message_area,

            # Separator line
            Window(height=1, char='-', style="class:separator"),

            # Status bar (connection info)
            Window(content=self.status_control, height=1, style="class:status-bar"),

            # Input area with minimal prompt
            self.input_area,
        ])

        # Create key bindings
        self.kb = self._create_key_bindings()

        # Create application
        self.app = Application(
            layout=Layout(root_container),
            key_bindings=self.kb,
            style=self._get_style(),
            full_screen=True,
        )

        # Set focus to input area
        self.app.layout.focus(self.input_area)

    def _create_key_bindings(self):
        """Create key bindings for the application."""
        kb = KeyBindings()

        @kb.add('enter')
        def handle_enter(event):
            """Handle command submission on Enter."""
            command = self.input_area.text.strip()
            if command:
                # Add command to message area as feedback (mask if password mode)
                if self.password_mode:
                    masked_command = '*' * len(command)
                    self._add_message(f"> {masked_command}")
                else:
                    self._add_message(f"> {command}")

                # Clear input
                self.input_area.text = ""

                # Process command asynchronously
                asyncio.create_task(self._process_user_command(command))

        @kb.add('c-c')
        def handle_ctrl_c(event):
            """Handle Ctrl+C to exit."""
            event.app.exit()

        @kb.add('c-d')
        def handle_ctrl_d(event):
            """Handle Ctrl+D to exit."""
            event.app.exit()

        return kb

    def _get_style(self):
        """Create the application style."""
        return Style.from_dict({
            'status-bar': 'reverse bold',
            'separator': '#888888',
        })

    def _get_status_text(self):
        """Get current status bar text (replaces /info command)."""
        # Connection status
        conn_status = "Conn" if self.socket_connected else "No conn"

        # Authentication and mode
        if self.logged_in:
            auth_status = f"User: {self.username or self.node_id or 'unknown'}"
        else:
            auth_status = "Not logged in"

        mode_status = "Workflow" if self.in_workflow else "Command"

        # Session info
        session_info = f"SID: {self.session_id or 'none'}"

        # Build status line
        if self.socket_connected:
            return f"{conn_status} | {auth_status} | {mode_status} | {session_info}"
        else:
            return f"{conn_status} | Socket: {self.socket_path} | Use '/connect <node>' to begin"

    def _add_message(self, text: str):
        """Add a message to the display area."""
        current_text = self.message_area.text
        self.message_area.text = current_text + text + "\n"

        # Auto-scroll to bottom
        self.message_area.buffer.cursor_position = len(self.message_area.text)

    def _update_ui(self):
        """Update UI elements that depend on state."""
        # Status control updates automatically via the callable
        # Force a refresh of the application
        if hasattr(self, 'app'):
            self.app.invalidate()

    def _set_password_mode(self, enabled: bool):
        """Enable or disable password masking in input area."""
        self.password_mode = enabled
        self.input_area.password = enabled

    async def _process_user_command(self, command: str):
        """Process a user command."""
        if command.startswith('/'):
            await self._handle_local_command(command)
        else:
            # Send BBS command to server
            await self._send_bbs_command(command)

    async def _handle_local_command(self, command: str):
        """Handle local slash commands."""
        parts = command[1:].split()
        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd == 'help':
            self._add_message("Local CLI commands:")
            self._add_message("  /help             - Show this help")
            self._add_message("  /connect <node>   - Connect to BBS as node")
            self._add_message("  /disconnect       - Disconnect from BBS")
            self._add_message("  /info             - Show detailed connection info")
            self._add_message("  /quit             - Exit CLI")
            self._add_message("")
            self._add_message("Connection status is always shown in the status bar below.")
            self._add_message("After connecting, type BBS commands directly (no / prefix).")
            self._add_message("")

        elif cmd == 'info':
            # Detailed info (beyond what's in status bar)
            self._add_message("=== Connection Information ===")
            self._add_message(f"Socket path: {self.socket_path}")
            self._add_message(f"Socket exists: {self.socket_path.exists()}")
            self._add_message(f"Socket connected: {self.socket_connected}")
            self._add_message(f"Node ID: {self.node_id or 'none'}")
            self._add_message(f"Session ID: {self.session_id or 'none'}")
            self._add_message(f"Username: {self.username or 'none'}")
            self._add_message(f"Logged in: {self.logged_in}")
            self._add_message(f"In workflow: {self.in_workflow}")
            self._add_message("")

        elif cmd in ['connect', 'c', 'conn']:
            if not args:
                self._add_message("Usage: /connect <node_id>")
                self._add_message("")
                return

            await self._connect_to_bbs(args[0])

        elif cmd in ['disconnect', 'd']:
            await self._disconnect_from_bbs()

        elif cmd in ['quit', 'q']:
            self._add_message("Goodbye!")
            self.app.exit()

        else:
            self._add_message(f"Unknown local command: /{cmd}")
            self._add_message("Type '/help' for available commands")
            self._add_message("")

    async def _connect_to_bbs(self, node_id: str):
        """Connect to the BBS server."""
        if self.socket_connected:
            self._add_message("Already connected. Use /disconnect first.")
            self._add_message("")
            return

        self.node_id = node_id
        self._add_message(f"Connecting to BBS as '{node_id}'...")

        # Connect to Unix socket
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(str(self.socket_path))
        except (ConnectionRefusedError, FileNotFoundError):
            self._add_message("Connection failed: BBS server not running or socket not found")
            self._add_message("")
            return
        except OSError as e:
            self._add_message(f"Connection failed: {e}")
            self._add_message("")
            return

        # Send initial connection message
        try:
            self.writer.write(b"CONNECTED\n")
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._add_message("Connection failed: Server closed connection")
            self._add_message("")
            await self._cleanup_connection()
            return

        # Connection established - start message listener to handle all server messages
        self.socket_connected = True
        self._update_ui()

        # Start message listener task (it will handle welcome message and everything else)
        self.listener_task = asyncio.create_task(self._message_listener())

        # Automatically start login workflow
        login_command = f"__workflow:login:{node_id}"
        try:
            self.writer.write(f"{login_command}\n".encode('utf-8'))
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._add_message("Connection lost while starting login")
            await self._disconnect_from_bbs()
            return

        self._add_message("")

    async def _disconnect_from_bbs(self):
        """Disconnect from the BBS server."""
        if self.socket_connected:
            self._add_message("Disconnecting...")
            await self._cleanup_connection()
            self._add_message("Disconnected.")
        else:
            self._add_message("Not connected")
        self._add_message("")

    async def _cleanup_connection(self):
        """Clean up connection resources and reset state."""
        self.socket_connected = False

        # Cancel message listener task
        if hasattr(self, 'listener_task') and not self.listener_task.done():
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass

        # Close writer
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except OSError:
                pass  # Already closed
            finally:
                self.writer = None
                self.reader = None

        # Reset session state
        self.session_id = None
        self.logged_in = False
        self.in_workflow = False
        self.username = ""
        self._set_password_mode(False)  # Disable password mode
        self._update_ui()

    async def _send_bbs_command(self, command: str):
        """Send a command to the BBS server."""
        if not self.socket_connected or not self.writer:
            self._add_message("Not connected to BBS")
            self._add_message("")
            return

        try:
            self.writer.write(f"{command}\n".encode('utf-8'))
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._add_message("Connection lost")
            await self._disconnect_from_bbs()

    def _parse_session_state(self, state_data: str):
        """Parse session state from server and update client state."""
        # Parse: "logged_in=true,in_workflow=false,username=bar"
        try:
            for pair in state_data.split(','):
                key, value = pair.split('=', 1)
                if key == 'logged_in':
                    self.logged_in = (value == 'true')
                elif key == 'in_workflow':
                    self.in_workflow = (value == 'true')
                elif key == 'username':
                    # Update username from server
                    if value and value != self.username:
                        self.username = value
        except ValueError:
            self._add_message(f"Invalid session state format: {state_data}")
            return

        # Update UI to reflect new state
        self._update_ui()

    def _detect_password_prompt(self, message: str):
        """Detect if a message is asking for password input and enable masking."""
        # Look for common password prompt patterns
        message_lower = message.lower()
        password_indicators = [
            "enter your password",
            "password:",
            "choose a password",
            "new password",
            "current password"
        ]

        is_password = any(indicator in message_lower for indicator in password_indicators)

        # Enable password mode only for password prompts, disable for anything else
        self._set_password_mode(is_password)

    async def _message_listener(self):
        """Listen for incoming messages from the server."""
        while self.socket_connected and self.reader:
            try:
                line = await self.reader.readline()
            except (ConnectionResetError, asyncio.IncompleteReadError):
                # Connection closed by server
                break
            except asyncio.CancelledError:
                break

            if not line:
                # EOF - connection closed
                break

            try:
                decoded = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                self._add_message("Received invalid text from server")
                continue

            # Handle control messages
            if decoded.startswith('SESSION_ID:'):
                try:
                    self.session_id = decoded.split(': ', 1)[1]
                    self._update_ui()
                except IndexError:
                    self._add_message("Invalid SESSION_ID format")

            elif decoded.startswith('SESSION_STATE:'):
                try:
                    state_data = decoded.split(': ', 1)[1]
                    self._parse_session_state(state_data)
                except IndexError:
                    self._add_message("Invalid SESSION_STATE format")

            elif decoded.startswith('ERROR:'):
                try:
                    error_msg = decoded.split(': ', 1)[1]
                    self._add_message(f"Error: {error_msg}")
                except IndexError:
                    self._add_message("Error: Unknown error")

            else:
                # Regular message - display it
                if decoded:  # Don't show empty lines
                    self._add_message(decoded)

                    # Check if this is a password prompt
                    if self.in_workflow:
                        self._detect_password_prompt(decoded)

        # Connection lost
        if self.socket_connected:
            self._add_message("Connection lost")
            await self._disconnect_from_bbs()

    async def run(self):
        """Run the async CLI application."""
        try:
            # Just run the UI - connection and message listener are started on-demand
            await self.app.run_async()

        except KeyboardInterrupt:
            pass
        finally:
            # Clean up any active connections
            await self._cleanup_connection()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="mesh-citadel async CLI client")
    parser.add_argument("--socket", "-s",
                       default="/tmp/mesh-citadel-cli.sock",
                       help="Path to BBS server socket")
    parser.add_argument("--node", "-n",
                       help="Node ID for automatic connection")
    parser.add_argument("--verbose", "-v",
                       action="store_true",
                       help="Enable verbose logging")

    args = parser.parse_args()

    # Check if socket exists
    socket_path = Path(args.socket)
    if not socket_path.exists():
        print(f"BBS server socket not found at {socket_path}")
        print("Make sure the mesh-citadel server is running")
        print("You can still test the UI, but connection features won't work")
        print()

    # Run CLI client
    cli = AsyncMeshCitadelCLI(socket_path, args.node)
    await cli.run()


if __name__ == "__main__":
    asyncio.run(main())
