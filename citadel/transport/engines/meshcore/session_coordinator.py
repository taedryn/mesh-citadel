"""
MeshCore Session Coordinator

Manages BBS message listeners for active sessions and handles session lifecycle coordination.
Extracted from the main transport engine for better separation of concerns.
"""

import asyncio
import logging
from typing import Dict, Callable, Awaitable

log = logging.getLogger(__name__)


class SessionCoordinator:
    """Manages BBS listeners and session lifecycle coordination."""

    def __init__(self, config, session_mgr, create_monitored_task_func):
        self.config = config
        self.session_mgr = session_mgr
        self._create_monitored_task = create_monitored_task_func
        # Derive mc_config from main config
        self.mc_config = config.transport.get("meshcore", {})
        self.listeners: Dict[str, asyncio.Task] = {}
        self._send_to_node_func = None  # Will be set by parent
        self._disconnect_func = None    # Will be set by parent

    def set_communication_callbacks(self, send_to_node_func: Callable, disconnect_func: Callable):
        """Set callbacks for node communication and disconnection."""
        self._send_to_node_func = send_to_node_func
        self._disconnect_func = disconnect_func

    async def start_bbs_listener(self, session_id: str):
        """Start a BBS listener for a session if one doesn't already exist."""
        if session_id in self.listeners:
            return  # Already listening

        async def listen():
            log.info(f'Starting BBS listener for "{session_id}"')
            while True:
                try:
                    # Check if session still exists (defensive programming)
                    state = self.session_mgr.get_session_state(session_id)
                    if not state:
                        log.info(
                            f'Session {session_id} no longer exists, terminating BBS listener')
                        break

                    log.debug(f'Waiting for BBS msgs for {session_id}')
                    message = await state.msg_queue.get()
                    if isinstance(message, list):
                        log.debug('BBS message is a LIST')
                    else:
                        log.debug('BBS message is NOT a list')
                    log.debug(f'Received BBS msg for {session_id}: {message}')

                    # Add inter_packet_delay before sending messages
                    inter_packet_delay = self.mc_config.get(
                        "inter_packet_delay", 0.5)
                    await asyncio.sleep(inter_packet_delay)

                    if isinstance(message, list):
                        for msg in message:
                            success = await self._send_to_node_func(
                                state.node_id,
                                state.username,
                                msg
                            )
                            if not success:
                                reading_msg = False
                                if msg.message:
                                    reading_msg = msg.message.id
                                log.debug(f"Disconnecting in list message context")
                                log.debug(f"Trying to send: {msg}")
                                return await self._disconnect_func(
                                    session_id,
                                    reading_msg=reading_msg
                                )
                    else:
                        success = await self._send_to_node_func(
                            state.node_id,
                            state.username,
                            message
                        )
                        if not success:
                            reading_msg = False
                            if message.message:
                                reading_msg = message.message.id
                            log.debug("Disconnecting in single message context")
                            log.debug(f"Trying to send: {message}")
                            return await self._disconnect_func(
                                session_id,
                                reading_msg=reading_msg
                            )

                except asyncio.CancelledError:
                    log.debug(f'BBS listener for {session_id} cancelled')
                    break
                except (ConnectionError, TimeoutError, OSError) as e:
                    # Network/connection errors - recoverable, continue after brief pause
                    log.warning(
                        f"Network error in BBS listener for {session_id}: {e}, retrying in 2s")
                    await asyncio.sleep(2)
                    continue
                except (AttributeError, TypeError, ValueError) as e:
                    # Data/serialization errors - log and skip this message
                    log.error(
                        f"Data error in BBS listener for {session_id}: {e}, skipping message")
                    continue
                except MemoryError as e:
                    # Resource exhaustion - critical, terminate and signal restart needed
                    log.critical(
                        f"Memory error in BBS listener for {session_id}: {e}, terminating")
                    # TODO: Signal system restart needed
                    break
                except Exception as e:
                    # Unexpected error - log details and attempt graceful recovery
                    log.exception(
                        f"Unexpected error in BBS listener for {session_id}: {e}")

                    # Check if session still exists before trying to send error
                    try:
                        current_state = self.session_mgr.get_session_state(
                            session_id)
                        if current_state:
                            await self._send_to_node_func(current_state.node_id,
                                                          current_state.username, f"System error occurred. Please try again.\n")
                        else:
                            log.info(
                                f'Session {session_id} expired during error handling, terminating listener')
                            break
                    except Exception as recovery_error:
                        log.exception(
                            f"Failed to send error message for {session_id}: {recovery_error}")
                        # If we can't even send an error message, terminate listener
                        break

                    # Brief pause before continuing to prevent tight error loops
                    await asyncio.sleep(1)

            log.info(f'BBS listener for {session_id} terminated')

        task = self._create_monitored_task(
            listen(), f"bbs_listener_{session_id}")
        self.listeners[session_id] = task

    def cleanup_bbs_listener(self, session_id: str):
        """Cancel and remove BBS listener for a session."""
        if session_id in self.listeners:
            listener_task = self.listeners[session_id]
            log.info(
                f"Cancelling BBS listener for expired session {session_id}")

            # Cancel the task
            listener_task.cancel()

            # Remove from listeners dict
            del self.listeners[session_id]

            log.info(
                f"BBS listener cleanup completed for session {session_id}")
        else:
            log.debug(
                f"No BBS listener found for session {session_id} during cleanup")

    async def shutdown(self):
        """Shutdown all BBS listeners cleanly."""
        if not self.listeners:
            log.debug("No BBS listeners to shutdown")
            return

        log.info(f"Shutting down {len(self.listeners)} BBS listeners")

        # Cancel all listener tasks
        for session_id, task in self.listeners.items():
            log.debug(f"Cancelling BBS listener for session {session_id}")
            task.cancel()

        # Wait for all tasks to complete cancellation
        if self.listeners:
            try:
                await asyncio.gather(*self.listeners.values(), return_exceptions=True)
            except Exception as e:
                log.warning(f"Exception during BBS listener shutdown: {e}")

        # Clear the listeners dict
        self.listeners.clear()
        log.info("All BBS listeners shut down")

    def setup_session_notifications(self):
        """Set up session manager notification callback for logout
        messages and listener cleanup."""
        def handle_session_expiration(session_id: str, message: str):
            """Handle session expiration: send logout notification and cleanup listeners."""
            log.debug(
                f"Handling session expiration for {session_id}: {message}")

            try:
                state = self.session_mgr.get_session_state(session_id)
                if state and state.node_id:
                    # Send logout notification using threadsafe task creation
                    log.info(
                        f"Sending logout notification to session {session_id}: {message}")
                    task_result = self._create_monitored_task(
                        self._send_to_node_func(
                            state.node_id, state.username, message),
                        f"logout_notification_{session_id}"
                    )

                    if task_result:
                        log.info(
                            f"Successfully scheduled logout notification for session {session_id}")
                    else:
                        log.error(
                            f"Failed to schedule logout notification for session {session_id}")
                else:
                    log.warning(
                        f"Cannot send logout notification - no state or node_id for session {session_id}")

                # Clean up BBS listener (critical for preventing hangs!)
                self.cleanup_bbs_listener(session_id)

            except Exception as e:
                log.exception(
                    f"Error handling session expiration for {session_id}: {e}")
                # Still try to cleanup listener even if notification fails
                try:
                    self.cleanup_bbs_listener(session_id)
                except Exception as cleanup_error:
                    log.exception(
                        f"Failed to cleanup listener for expired session {session_id}: {cleanup_error}")

        self.session_mgr.set_notification_callback(handle_session_expiration)

    def get_active_listeners(self) -> Dict[str, asyncio.Task]:
        """Get a copy of the active listeners dict for monitoring/debugging."""
        return self.listeners.copy()
