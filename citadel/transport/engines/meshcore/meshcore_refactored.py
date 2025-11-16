"""
Refactored MeshCore Transport Engine

Clean orchestration of the separated concerns: authentication, protocol handling,
message routing, and session coordination. Much smaller and focused on coordination
rather than implementation details.
"""

import asyncio
from datetime import datetime, UTC, timedelta
import logging
from meshcore import MeshCore, EventType
from serial import SerialException
import time
import traceback

from citadel.commands.processor import CommandProcessor
from citadel.transport.engines.meshcore.util import MessageDeduplicator, AdvertScheduler, WatchdogFeeder
from citadel.transport.parser import TextParser
from citadel.transport.engines.meshcore.contacts import ContactManager
from citadel.workflows.base import WorkflowState, WorkflowContext
from citadel.workflows import registry as workflow_registry

# Import our new separated components
from citadel.transport.engines.meshcore.node_auth import NodeAuth
from citadel.transport.engines.meshcore.protocol_handler import ProtocolHandler
from citadel.transport.engines.meshcore.message_router import MessageRouter
from citadel.transport.engines.meshcore.session_coordinator import SessionCoordinator

log = logging.getLogger(__name__)


class MeshCoreTransportEngine:
    """Orchestrates MeshCore transport components with clean separation of concerns."""

    def __init__(self, config, db, session_mgr, feed_watchdog=None):
        # Follow config, db convention
        self.config = config
        self.db = db
        self.session_mgr = session_mgr
        self.feed_watchdog = feed_watchdog

        # MeshCore configuration
        self.mc_config = config.transport.get("meshcore", {})

        # Core MeshCore objects
        self.meshcore = None
        self.contact_manager = None

        # Process lifecycle
        self._running = False
        self.tasks = []
        self.subs = []
        self.scheds = []
        self._event_loop = None

        # Initialize components that don't need MeshCore
        self.node_auth = NodeAuth(config, db)
        self.dedupe = None
        self.text_parser = TextParser()
        self.command_processor = CommandProcessor(config, db, session_mgr)

        # These will be initialized in start() after MeshCore is ready
        self.protocol_handler = None
        self.message_router = None
        self.session_coordinator = None

    # ------------------------------------------------------------
    # process lifecycle controls
    # ------------------------------------------------------------

    async def start(self):
        """Start the MeshCore transport engine and all its components."""
        try:
            # Store the event loop for later use in threadsafe operations
            self._event_loop = asyncio.get_running_loop()

            await self.start_watchdog()
            await self.start_dedupe()
            await self.start_meshcore()

            # Initialize protocol handler (now handles send method setup internally)
            self.protocol_handler = ProtocolHandler(
                self.config, self.db, self.meshcore)

            # Initialize message router with all dependencies
            self.message_router = MessageRouter(
                self.config, self.db, self.session_mgr, self.node_auth,
                self.dedupe, self.text_parser, self.command_processor
            )

            # Initialize session coordinator
            self.session_coordinator = SessionCoordinator(
                self.config, self.session_mgr, self._create_monitored_task
            )

            # Wire up the callbacks between components
            self._wire_component_callbacks()

            # Initialize contact manager
            self.contact_manager = ContactManager(
                self.meshcore, self.db, self.config)
            await self.contact_manager.start()

            if self.mc_config.get("contact_manager", {}).get("update_contacts", False):
                log.info("Syncing contacts")
                await self.contact_manager.sync_db_to_node()

            # Set up event handlers and session notifications
            await self._register_event_handlers()
            self.session_coordinator.setup_session_notifications()

            self._running = True
            log.info(f"MeshCore device connected")

        except SerialException as e:
            log.error(f"Serial connection failed: {e}")
            raise
        except OSError as e:
            log.error(f"OS error during connection: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected startup error: {e}")
            traceback.print_exc()
            raise

    def _wire_component_callbacks(self):
        """Wire up the callbacks between separated components."""
        # Message router callbacks
        self.message_router.set_callbacks(
            send_to_node_func=self.protocol_handler.send_to_node,
            disconnect_func=self.disconnect,
            start_bbs_listener_func=self.session_coordinator.start_bbs_listener,
            start_login_workflow_func=self._start_login_workflow
        )

        # Session coordinator callbacks
        self.session_coordinator.set_communication_callbacks(
            send_to_node_func=self.protocol_handler.send_to_node,
            disconnect_func=self.disconnect
        )

    async def start_watchdog(self):
        """Start the watchdog feeder system."""
        scheduler = WatchdogFeeder(self.config, self.feed_watchdog)
        self.scheds.append(scheduler)
        self.tasks.append(
            self._create_monitored_task(
                scheduler.start_feeder(),
                f"watchdog_feeder_{len(self.scheds)}"
            )
        )
        log.info("Started watchdog feeder system")

    async def start_dedupe(self):
        self.dedupe = MessageDeduplicator()
        self.tasks.append(
            self._create_monitored_task(
                self.dedupe.clear_expired(),
                f"dedupe_cleaner_{len(self.scheds)}"
            )
        )
        log.info("Started message deduplication system")

    async def start_meshcore(self):
        """Initialize and start the MeshCore connection."""
        mc_config = self.mc_config

        serial_port = mc_config.get("serial_port", "/dev/ttyUSB0")
        baud_rate = mc_config.get("baud_rate", 115200)

        # Radio settings default to US Recommended settings, if not otherwise set in config
        frequency = mc_config.get("frequency", 910.525)
        bandwidth = mc_config.get("bandwidth", 62.5)
        spreading_factor = mc_config.get("spreading_factor", 7)
        coding_rate = mc_config.get("coding_rate", 5)
        tx_power = mc_config.get("tx_power", 22)
        node_name = mc_config.get("name", "Mesh-Citadel BBS")
        multi_acks = mc_config.get("multi_acks", True)

        log.info(f"Connecting MeshCore transport at {serial_port}")
        debug = False
        if log.getEffectiveLevel() <= logging.DEBUG:
            debug = True
        mc = await MeshCore.create_serial(serial_port, baud_rate, debug=debug)

        # Set node time
        now = int(time.time())
        log.info(f"Setting MeshCore node time to {now}")
        result = await mc.commands.set_time(now)
        from citadel.transport.manager import TransportError
        if result.type == EventType.ERROR:
            log.warning(f"Unable to sync time: {result.payload}")
            log.warning("Consider rebooting node (non-critical)")

        # Configure radio parameters
        log.info(f"Setting MeshCore frequency to {frequency} MHz")
        log.info(f"Setting MeshCore bandwidth to {bandwidth} kHz")
        log.info(f"Setting MeshCore spreading factor to {spreading_factor}")
        log.info(f"Setting MeshCore coding rate to {coding_rate}")
        result = await mc.commands.set_radio(
            frequency,
            bandwidth,
            spreading_factor,
            coding_rate
        )
        if result.type == EventType.ERROR:
            raise TransportError(
                f"Unable to set radio parameters: {result.payload}")

        # Set TX power
        log.info(f"Setting MeshCore TX power to {tx_power} dBm")
        result = await mc.commands.set_tx_power(tx_power)
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to set TX power: {result.payload}")

        # Set node name
        log.info(f"Setting MeshCore node name to '{node_name}'")
        result = await mc.commands.set_name(node_name)
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to set node name: {result.payload}")

        # Configure multi-acks if enabled
        if multi_acks:
            log.info(f"Setting MeshCore multi-acks to '{multi_acks}'")
            result = await mc.commands.set_multi_acks(multi_acks)
            if result.type == EventType.ERROR:
                raise TransportError(
                    f"Unable to set multi-acks: {result.payload}")

        # Ensure contacts
        log.info("Ensuring contacts")
        result = await mc.ensure_contacts()
        if not result:
            raise TransportError(
                f"Unable to ensure contacts: {result.payload}")

        # Set up adverts, one right now, then every N hours (config.yaml)
        scheduler = AdvertScheduler(self.config, mc)
        self.scheds.append(scheduler)
        self.tasks.append(
            self._create_monitored_task(
                scheduler.interval_advert(),
                f"advert_scheduler_{len(self.scheds)}"
            )
        )

        self.meshcore = mc

    async def stop(self):
        """Stop the transport engine and clean up all resources."""
        if not self._running:
            log.warning("MeshCoreTransport.stop() called when already stopped")
            return

        log.info("Stopping MeshCore transport engine...")
        self._running = False

        # Stop schedulers
        for sched in self.scheds:
            sched.stop()

        # Cancel all tasks
        from citadel.transport.manager import TransportError
        for task in self.tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, TransportError):
                pass

        # Shutdown session coordinator (cleans up BBS listeners)
        if self.session_coordinator:
            await self.session_coordinator.shutdown()

        # Unsubscribe from events
        for sub in self.subs:
            if self.meshcore:
                self.meshcore.unsubscribe(sub)

        # Close MeshCore connection
        if self.meshcore:
            # TODO: figure out exceptions for this
            self.meshcore.stop()
            await self.meshcore.stop_auto_message_fetching()
            await self.meshcore.disconnect()

        # Clear all collections
        self.tasks.clear()
        self.subs.clear()
        self.scheds.clear()

        log.info("MeshCore transport shut down")

    # ------------------------------------------------------------
    # Event handling (now much simpler)
    # ------------------------------------------------------------

    async def _register_event_handlers(self):
        """Register event handlers with MeshCore."""
        try:
            # Message handling - delegated to message router
            self.subs.append(self.meshcore.subscribe(
                EventType.CONTACT_MSG_RECV,
                self.safe_handler(self.message_router.handle_mc_message)
            ))

            # Advertisement handling - delegated to contact manager
            self.subs.append(self.meshcore.subscribe(
                EventType.ADVERTISEMENT,
                self.safe_handler(self.contact_manager.handle_advert)
            ))

            # New contact handling - delegated to contact manager
            self.subs.append(self.meshcore.subscribe(
                EventType.NEW_CONTACT,
                self.safe_handler(self.contact_manager.handle_advert)
            ))

            # ACK handling - delegated to protocol handler
            self.subs.append(self.meshcore.subscribe(
                EventType.ACK,
                self.safe_handler(self.protocol_handler.handle_ack)
            ))

            task = await self.meshcore.start_auto_message_fetching()
            log.debug("Event subscriptions registered")

        except Exception as e:
            log.error(f"Failed to register handlers: {e}")
            raise

    def safe_handler(self, handler):
        """Wrap handlers with exception protection."""
        async def wrapper(*args, **kwargs):
            try:
                await handler(*args, **kwargs)
            except Exception as e:
                log.exception(f"Handler {handler.__name__} crashed: {e}")
        return wrapper

    # ------------------------------------------------------------
    # Session management integration
    # ------------------------------------------------------------

    async def disconnect(self, session_id: str, reading_msg: int = None):
        """Disconnect a session and send logout message."""
        try:
            state = self.session_mgr.get_session_state(session_id)
            if not state:
                log.warning(
                    f"Cannot disconnect - no state for session {session_id}")
                return

            # Send logout message
            msg = "Signal lost. Disconnecting your session. Send any text to reconnect."
            await self.protocol_handler.send_to_node(state.node_id, state.username, msg)

            # Expire the session
            self.session_mgr.expire_session(session_id)

        except Exception as e:
            log.exception(f"Error disconnecting session {session_id}: {e}")

    async def _start_login_workflow(self, session_id: str, node_id: str):
        """Start the login workflow for a new node."""
        try:
            # Create workflow state (matching original implementation)
            wf_state = WorkflowState(
                kind="login",
                step=1,
                data={}
            )
            self.session_mgr.set_workflow(session_id, wf_state)

            # Create workflow context
            context = WorkflowContext(
                session_id=session_id,
                db=self.db,
                config=self.config,
                session_mgr=self.session_mgr,
                wf_state=wf_state
            )

            # Get workflow handler from registry
            handler = workflow_registry.get("login")
            if handler:
                session_state = self.session_mgr.get_session_state(session_id)
                touser_result = await handler.start(context)
                success = await self.protocol_handler.send_to_node(
                    session_state.node_id,
                    session_state.username,
                    touser_result
                )
                if not success:
                    await self.disconnect(session_id)
                return success
            else:
                success = await self.protocol_handler.send_to_node(
                    node_id,
                    "unknown",
                    "Error: Login workflow not found"
                )
                if not success:
                    await self.disconnect(session_id)

        except Exception as e:
            log.exception(
                f"Failed to start login workflow for {session_id}: {e}")
            try:
                await self.protocol_handler.send_to_node(
                    node_id, "user", "Login system error. Please try again later."
                )
            except:
                pass

    # ------------------------------------------------------------
    # Task management utilities
    # ------------------------------------------------------------

    def _create_monitored_task(self, coro, name="unnamed"):
        """Create a task with exception monitoring (matches original implementation)."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            task.add_done_callback(
                lambda t: self._handle_task_exception(t, name))
            log.debug(f"Created async task for {name}")
            return task
        except RuntimeError:
            # in a thread — use stored event loop for thread-safe execution
            if self._event_loop is None:
                log.error(
                    f"Cannot run {name} threadsafe: no stored event loop")
                return None

            log.debug(f"Running {name} threadsafe using stored event loop")
            future = asyncio.run_coroutine_threadsafe(coro, self._event_loop)

            # Attach a callback to handle exceptions
            def on_done(fut):
                try:
                    fut.result()
                except Exception as e:
                    self._handle_task_exception(fut, name)
            future.add_done_callback(on_done)
            log.debug(
                f"Successfully scheduled {name} for threadsafe execution")
            return future

    def _handle_task_exception(self, task, name: str):
        """Handle exceptions from fire-and-forget tasks (asyncio.Task
        or concurrent.futures.Future)."""
        try:
            if hasattr(task, 'cancelled') and task.cancelled():
                log.debug(f"Fire-and-forget task '{name}' cancelled")
                return

            if hasattr(task, 'exception'):
                exc = task.exception()
                if exc:
                    log.exception(
                        f"Fire-and-forget task '{name}' failed: {exc}")
                else:
                    log.debug(f"Task '{name}' completed successfully")
            else:
                log.debug(f"Task '{name}' completed")
        except Exception as e:
            log.error(f"Error handling task exception for '{name}': {e}")
