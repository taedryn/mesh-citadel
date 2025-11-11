"""
MeshCore Message Router

Handles incoming MeshCore events, routing them through authentication, session management,
and command processing. Extracted from the main transport engine for better separation of concerns.
"""

import asyncio
import logging
from typing import Callable, Awaitable

from citadel.transport.packets import FromUser, FromUserType, ToUser
from citadel.auth.permissions import PermissionLevel
from citadel.room.room import SystemRoomIDs

log = logging.getLogger(__name__)


class MessageRouter:
    """Routes incoming MeshCore messages through the processing pipeline."""

    def __init__(self, config, db, session_mgr, node_auth, dedupe, text_parser, command_processor):
        self.config = config
        self.db = db
        self.session_mgr = session_mgr
        self.node_auth = node_auth
        self.dedupe = dedupe
        self.text_parser = text_parser
        self.command_processor = command_processor
        # Derive mc_config from main config
        self.mc_config = config.transport.get("meshcore", {})

        # Callbacks set by parent
        self._send_to_node_func = None
        self._disconnect_func = None
        self._start_bbs_listener_func = None
        self._start_login_workflow_func = None

    def set_callbacks(self, send_to_node_func: Callable, disconnect_func: Callable,
                     start_bbs_listener_func: Callable, start_login_workflow_func: Callable):
        """Set callbacks for communication and workflow management."""
        self._send_to_node_func = send_to_node_func
        self._disconnect_func = disconnect_func
        self._start_bbs_listener_func = start_bbs_listener_func
        self._start_login_workflow_func = start_login_workflow_func

    async def handle_mc_message(self, event):
        """Handle incoming messages with comprehensive exception protection."""
        try:
            log.debug(f"Received message event: {event}")
            await self._process_mc_message_safe(event)
        except Exception as e:
            log.exception(f"CRITICAL: Message handler exception - event subscription preserved: {e}")
            # Don't re-raise - that would break the subscription
            # Try to send error message if we can extract basic info
            try:
                if hasattr(event, 'payload') and isinstance(event.payload, dict) and 'pubkey_prefix' in event.payload:
                    node_id = event.payload['pubkey_prefix']
                    session_id = self.session_mgr.get_session_by_node_id(node_id)
                    if session_id:
                        state = self.session_mgr.get_session_state(session_id)
                        success = await self._send_to_node_func(
                            node_id,
                            state.username,
                            "System temporarily unavailable. Please try later."
                        )
                        if success:
                            log.info(f"Sent error message to node {node_id}")
                        else:
                            log.warning(f"Unable to send system down msg to {node_id} (failed to get ACK)")
            except Exception as recovery_error:
                log.exception(f"Failed to send error message to user: {recovery_error}")

    async def _process_mc_message_safe(self, event):
        """The actual message processing logic, separated for better error handling."""
        # Extract and validate event data
        try:
            data = event.payload
            node_id = data['pubkey_prefix']
            text = data['text']
        except (KeyError, AttributeError, TypeError) as e:
            log.error(f"Malformed message event - missing required fields: {e}")
            return

        # Check for duplicates with error handling
        try:
            if await self.dedupe.is_duplicate(node_id, text):
                log.debug(f'Duplicate message from {node_id}, skipping')
                return
        except Exception as e:
            log.warning(f"Deduplication check failed for {node_id}: {e} - continuing with processing")

        # Session management with error handling
        try:
            session_id = self.session_mgr.get_session_by_node_id(node_id)
            is_new_session = (session_id is None)
            if is_new_session:
                session_id = self.session_mgr.create_session(node_id)
                await self._start_bbs_listener_func(session_id)
        except Exception as e:
            log.exception(f"Session management failed for {node_id}")
            return  # Can't proceed without session

        # Authentication and workflow processing
        try:
            username = await self.node_auth.node_has_password_cache(node_id)

            wf_state = self.session_mgr.get_workflow(session_id)

            if wf_state:
                packet = FromUser(
                    session_id=session_id,
                    payload_type=FromUserType.WORKFLOW_RESPONSE,
                    payload=text
                )
            elif username:

                await self.node_auth.touch_password_cache(username, node_id)

                await self.node_auth.set_cache_username(username, node_id)

                await self.session_mgr.mark_logged_in(session_id, True)
                self.session_mgr.mark_username(session_id, username)

                # Handle welcome back vs. regular command
                if is_new_session:
                    # This is a reconnection after timeout - send welcome back message
                    welcome_msg = f"Welcome back, {username}! You've been automatically logged in."
                    welcome_msg = await self.insert_prompt(session_id, welcome_msg)

                    inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
                    await asyncio.sleep(inter_packet_delay)
                    success = await self._send_to_node_func(
                        node_id,
                        username,
                        welcome_msg
                    )
                    if not success:
                        log.warning("No ACK when sending welcome back msg")
                        await self._disconnect_func(session_id)

                    # For welcome back, we send them to the lobby with a prompt
                    # Any text they sent is ignored - this was just to reconnect
                    return

                # Process their command normally (existing session)
                command = self.text_parser.parse_command(text)

                packet = FromUser(
                    session_id=session_id,
                    payload_type=FromUserType.COMMAND,
                    payload=command
                )
            else:
                log.info(f'No pw cache found for {node_id}, sending to login')
                return await self._start_login_workflow_func(session_id, node_id)
        except Exception as e:
            log.exception(f"Authentication/workflow processing failed for {node_id}")
            try:
                success = await self._send_to_node_func(
                    node_id,
                    username if 'username' in locals() else "user",
                    "Authentication error. Please try again."
                )
                if not success:
                    log.warning(f"No ACK sending auth error msg")
                    await self._disconnect_func(session_id)
            except:
                pass
            return

        # Command processing and response
        try:
            touser = await self.command_processor.process(packet)

            # pause the bbs just a moment before sending the command response
            inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
            await asyncio.sleep(inter_packet_delay)

            if isinstance(touser, list):
                last_msg = len(touser) - 1
                for i, msg in enumerate(touser):
                    if i == last_msg:
                        msg = await self.insert_prompt(session_id, msg)
                    success = await self._send_to_node_func(node_id, username, msg)
                    if not success:
                        await self._disconnect_func(session_id)
            else:
                touser = await self.insert_prompt(session_id, touser)
                success = await self._send_to_node_func(node_id, username, touser)
                if not success:
                    await self._disconnect_func(session_id)

        except Exception as e:
            log.exception(f"Command processing/response failed for {node_id}")
            try:
                msg = "Command processing error. Please try again."
                success = await self._send_to_node_func(node_id, username, msg)
                if not success:
                    await self._disconnect_func(session_id)
            except:
                pass

    async def insert_prompt(self, session_id: str, touser) -> str:
        """Insert UI prompts and notifications into responses."""
        if self.session_mgr.get_workflow(session_id):
            return touser

        session_state = self.session_mgr.get_session_state(session_id)
        prompt = []
        if not session_state or not session_state.current_room:
            prompt = ["What now? (H for help)"]
        else:
            # sort out notifications. first, pending validations
            from citadel.user.user import User
            user = User(self.db, session_state.username)
            await user.load()
            query = "SELECT COUNT(*) FROM pending_validations"
            result = await self.db.execute(query, [])
            count = result[0][0]
            if count and user.permission_level >= PermissionLevel.AIDE:
                if count == 1:
                    vword = "validation"
                    isword = "is"
                else:
                    vword = "validations"
                    isword = "are"
                prompt.append(f"* There {isword} {count} {vword} to review")

            # next, notify of new mail
            from citadel.room.room import Room
            mail = Room(self.db, self.config, SystemRoomIDs.MAIL_ID)
            await mail.load()
            has_mail = await mail.has_unread_messages(session_state.username)
            if has_mail:
                prompt.append("* You have unread mail")

            # Get room name
            try:
                room = Room(self.db, self.config, session_state.current_room)
                await room.load()
                room_name = room.name
            except Exception:
                room_name = f"Room {session_state.current_room}"
            prompt.append(f"In {room_name}. What now? (H for help)")
        prompt_str = "\n".join(prompt)

        if isinstance(touser, ToUser):
            if touser.message:
                touser.message.content += f'\n{prompt_str}'
            else:
                touser.text += f'\n{prompt_str}'
        elif isinstance(touser, str):
            touser += f'\n{prompt_str}'

        return touser