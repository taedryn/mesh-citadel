import asyncio
from datetime import datetime, UTC, timedelta
from dateutil.parser import parse as dateparse
import hashlib
import json
import logging
from meshcore import MeshCore, EventType
from serial import SerialException
import time
import traceback
from zoneinfo import ZoneInfo

from citadel.auth.permissions import PermissionLevel
from citadel.commands.processor import CommandProcessor
from citadel.logging_lock import AsyncLoggingLock
from citadel.message.manager import format_timestamp
from citadel.room.room import SystemRoomIDs
from citadel.transport.engines.meshcore.util import MessageDeduplicator, AdvertScheduler
from citadel.transport.packets import FromUser, FromUserType, ToUser
from citadel.transport.parser import TextParser
from citadel.transport.engines.meshcore.contacts import ContactManager
from citadel.workflows.base import WorkflowState, WorkflowContext
from citadel.workflows import registry as workflow_registry

log = logging.getLogger(__name__)


class MeshCoreTransportEngine:
    def __init__(self, session_mgr, config, db):
        self.session_mgr = session_mgr
        self.config = config
        self.mc_config = config.transport.get("meshcore", {})
        self.db = db
        self.command_processor = CommandProcessor(config, db, session_mgr)
        self.dedupe = MessageDeduplicator()
        self.text_parser = TextParser()
        self.contact_manager = None
        self.meshcore = None
        self._running = False
        self.tasks = []
        self.subs = []
        self.listeners = {}
        self._event_loop = None
        self._acks = {}

    #------------------------------------------------------------
    # process lifecycle controls
    #------------------------------------------------------------
    async def start(self):
        try:
            # Store the event loop for later use in threadsafe operations
            self._event_loop = asyncio.get_running_loop()

            await self.start_meshcore()
            self.contact_manager = ContactManager(self.meshcore,
                                                  self.db, self.config)
            await self.contact_manager.start()
            await self._register_event_handlers()
            self._setup_session_notifications()
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

    async def start_meshcore(self):
        mc_config = self.mc_config

        serial_port = mc_config.get("serial_port", "/dev/ttyUSB0")
        baud_rate = mc_config.get("baud_rate", 115200)

        # radio settings default to US Recommended settings, if not
        # otherwise set in the config file
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

        now = int(time.time())
        log.info(f"Setting MeshCore node time to {now}")
        result = await mc.commands.set_time(now)
        from citadel.transport.manager import TransportError
        if result.type == EventType.ERROR:
            log.warning(f"Unable to sync time: {result.payload}")

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
            raise TransportError(f"Unable to set radio parameters: {result.payload}")

        log.info(f"Setting MeshCore TX power to {tx_power} dBm")
        result = await mc.commands.set_tx_power(tx_power)
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to set TX power: {result.payload}")

        log.info(f"Setting MeshCore node name to '{node_name}'")
        result = await mc.commands.set_name(node_name)
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to set node name: {result.payload}")

        if multi_acks:
            log.info(f"Setting MeshCore multi-acks to '{multi_acks}'")
            result = await mc.commands.set_multi_acks(multi_acks)
            if result.type == EventType.ERROR:
                raise TransportError(f"Unable to set multi-acks: {result.payload}")

        log.info("Ensuring contacts")
        result = await mc.ensure_contacts()
        if not result:
            raise(TransportError(f"Unable to ensure contacts: {result.payload}"))
        log.info("Gathering device information")
        result = await mc.commands.send_device_query()
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to get device info: {result.payload}")
        else:
            log.info(f"Self-info returned: {mc.self_info}")
            #info = result.payload
            #log.info(f"Device is running firmware {info['ver']}, built {info['fw_build']}")
            #cm = mc_config.get('contact_manager', {})
            #config_max = cm.get('max_device_contacts', 0)
            #device_max = info['max_contacts']
            #log.info(f"Device can hold {device_max} contacts ({config_max} is configured)")
        self.scheds = []
        # set up adverts, one right now, then every N hours (config.yaml)
        scheduler = AdvertScheduler(self.config, mc)
        self.scheds.append(scheduler)
        self.tasks.append(self._create_monitored_task(scheduler.interval_advert(), f"advert_scheduler_{len(self.scheds)}"))
        self.meshcore = mc

        # Set up the appropriate send method based on what's available
        self._setup_send_method()

    def _setup_send_method(self):
        """Set up the appropriate send method with config applied."""
        # Get configuration values once at startup
        max_attempts = self.mc_config.get("max_retries", 3)
        max_flood_attempts = self.mc_config.get("max_flood_attempts", 3)
        flood_after = self.mc_config.get("flood_after", 2)
        send_timeout = self.mc_config.get("send_timeout", 0)

        # Check if send_msg_with_retry is available
        try:
            # Test if the method exists by accessing it (don't call it)
            _ = self.meshcore.commands.send_msg_with_retry

            # Create a wrapper function with config pre-applied
            async def send_with_retry(node_id, chunk):
                return await self.meshcore.commands.send_msg_with_retry(
                    node_id,
                    chunk,
                    max_attempts=max_attempts,
                    max_flood_attempts=max_flood_attempts,
                    flood_after=flood_after,
                    timeout=send_timeout
                )
            self.send_msg = send_with_retry
            log.info(f"Using send_msg_with_retry with max_attempts={max_attempts}, ack_timeout={self.mc_config.get('ack_timeout', 8)}s")

        except AttributeError:
            # Implement manual retry wrapper
            async def send_with_manual_retry(node_id, chunk):
                result = None
                for attempt in range(max_attempts):
                    try:
                        result = await self.meshcore.commands.send_msg(node_id, chunk)
                        if result and result.type != EventType.ERROR:
                            break
                        log.debug(f"Send attempt {attempt + 1} failed with error: {result.payload if result else 'No result'}")
                    except (OSError, SerialException) as e:
                        log.debug(f"Send attempt {attempt + 1} raised {type(e).__name__}: {e}")
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(1.0)  # Wait 1 second before retry
                return result

            self.send_msg = send_with_manual_retry
            log.debug("send_msg_with_retry not available, using manual retry wrapper")

    def _create_monitored_task(self, coro, name="unnamed"):
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            task.add_done_callback(lambda t: self._handle_task_exception(t, name))
            log.debug(f"Created async task for {name}")
            return task
        except RuntimeError:
            # in a thread — use stored event loop for thread-safe execution
            if self._event_loop is None:
                log.error(f"Cannot run {name} threadsafe: no stored event loop")
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
            log.debug(f"Successfully scheduled {name} for threadsafe execution")
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
                    log.exception(f"Fire-and-forget task '{name}' failed: {exc}")
                else:
                    log.debug(f"Task '{name}' completed successfully")
            else:
                log.debug(f"Task '{name}' completed")
        except Exception as e:
            log.error(f"Error handling task exception for '{name}': {e}")

    async def stop(self):
        if self._running:
            for sched in self.scheds:
                sched.stop()
            for task in self.tasks:
                task.cancel()
                await task
            for listener in self.listeners.values():
                listener.cancel()
                await listener
            for sub in self.subs:
                self.meshcore.unsubscribe(sub)
            if self.meshcore:
                # TODO: figure out exceptions for this
                self.meshcore.stop()
                await self.meshcore.stop_auto_message_fetching()
                await self.meshcore.disconnect()
                log.info("MeshCore transport shut down")
            self._running = False
        else:
            log.warning("MeshCoreTransport.stop() called when already stopped")

    #------------------------------------------------------------
    # communication methods
    #------------------------------------------------------------

    async def send_to_node(self, node_id: str, username: str, message: str | ToUser | list):
        """Send a message to a mesh node via MeshCore. Returns False if
        the message couldn't be sent."""
        # TODO: probably need to handle ToUser packets more intelligently than
        # this
        if isinstance(message, ToUser):
            if message.message:
                log.debug("Formatting BBS message")
                text = self.format_message(message.message)
            else:
                text = message.text
        else:
            text = message
        # Get configured packet size (calculated from MeshCore packet structure)
        max_packet_length = self.mc_config.get("max_packet_size", 140)

        chunks = self._chunk_message(text, max_packet_length)
        inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
        for chunk in chunks:
            sent = await self._send_packet(username, node_id, chunk)
            await asyncio.sleep(inter_packet_delay)
        return sent

    #------------------------------------------------------------
    # communication helpers
    #------------------------------------------------------------

    def format_message(self, message) -> str:
        utc_timestamp = dateparse(message.timestamp)
        timestamp = format_timestamp(self.config, utc_timestamp)
        to_str = ""
        if message.recipient:
            to_str = f" To: {message.recipient}"
        header = f"[{message.id}] From: {message.display_name} ({message.sender}){to_str} - {timestamp}"
        content = "[Message from blocked sender]" if message.blocked else message.content
        return f"{header}\n{content}"

    async def _send_packet(self, username, node_id, chunk) -> bool:
        """Send a single packet to a node. This assumes that the packet
        is a safe size to send. Blocks until the ack has been
        received."""
        log.debug(f'Sending packet to {username} at {node_id}: {len(chunk)} bytes, content: "{chunk[:50]}..."')

        # Use the pre-configured send method
        result = await self.send_msg(node_id, chunk)

        if result and result.type == EventType.ERROR:
            log.error(f"Error sending '{chunk[:50]}...' to {username} at {node_id}! {result.payload}")
            return False
        elif not result:
            log.error(f"Failed to send '{chunk[:50]}...' to {username} at {node_id}")
            return False

        # Wait for ACK with the configured timeout
        exp_ack = result.payload["expected_ack"].hex()
        ack_timeout = self.mc_config.get("ack_timeout", 8)  # Increased from 5 to 8 seconds
        log.debug(f"Waiting for ACK {exp_ack} with timeout {ack_timeout}s")

        ack = await self.get_ack(exp_ack, ack_timeout)

        if ack:
            log.debug(f"✅ ACK received for packet to {node_id}")
            return True

        # Log ACK timeout for debugging (this is normal in mesh communication)
        log.debug(f"❌ ACK timeout ({ack_timeout}s) for packet '{chunk[:30]}...' to {username} at {node_id}")
        return False

    def _chunk_message(self, message, max_packet_length):
        """split the message into appropriately sized chunks.  returns a list
        of strings."""
        if message:
            if isinstance(message, list):
                log.error(f"Don't know how to split '{message}'")
                return ["Oops, check the log"]
            words = message.split(" ")
        else:
            return ""

        approx_chunks = len(message) / max_packet_length
        if approx_chunks >= 10:
            max_packet_length -= len('[xx/xx]')
        else:
            max_packet_length -= len('[x/x]')
        chunks = []
        chunk = []
        chunk_size = 0
        for word in words:
            wordlen = len(word)
            if chunk_size + wordlen + 1 < max_packet_length:
                chunk.append(word)
                chunk_size += wordlen + 1
            else:
                chunks.append(" ".join(chunk))
                chunk = [word]
                chunk_size = wordlen + 1

        if len(chunk) > 0:
            chunks.append(" ".join(chunk))

        if approx_chunks > 1:
            len_chunks = len(chunks)
            for i in range(len_chunks):
                chunks[i] += f'[{i+1}/{len_chunks}]'
        return chunks

    async def get_ack(self, code: str, timeout: int=10) -> bool:
        """Await this function to see if a named ack has been received.
        Returns True or False."""
        i = 0
        while True:
            if i > timeout:
                return False
            if code in self._acks:
                del self._acks[code]
                return True
            await asyncio.sleep(1)
            i += 1

    #------------------------------------------------------------
    # bbs event handlers
    #------------------------------------------------------------

    async def start_bbs_listener(self, session_id):
        if session_id in self.listeners:
            return  # Already listening

        async def listen():
            log.info(f'Starting BBS listener for "{session_id}"')
            while True:
                try:
                    # Check if session still exists (defensive programming)
                    state = self.session_mgr.get_session_state(session_id)
                    if not state:
                        log.info(f'Session {session_id} no longer exists, terminating BBS listener')
                        break

                    log.debug(f'Waiting for BBS msgs for {session_id}')
                    message = await state.msg_queue.get()
                    if isinstance(message, list):
                        log.debug('BBS message is a LIST')
                    else:
                        log.debug('BBS message is NOT a list')
                    log.debug(f'Received BBS msg for {session_id}: {message}')

                    if isinstance(message, list):
                        for msg in message:
                            success = await self.send_to_node(
                                state.node_id,
                                state.username,
                                msg
                            )
                            if not success:
                                reading_msg = False
                                if msg.message:
                                    reading_msg = msg.message.id
                                return await self.disconnect(
                                    session_id,
                                    reading_msg=reading_msg
                                )
                    else:
                        success = await self.send_to_node(
                            state.node_id,
                            state.username,
                            message
                        )
                        if not success:
                            reading_msg = False
                            if message.message:
                                reading_msg = message.message.id
                            return await self.disconnect(
                                session_id,
                                reading_msg=reading_msg
                            )

                except asyncio.CancelledError:
                    log.debug(f'BBS listener for {session_id} cancelled')
                    break
                except Exception as e:
                    log.error(f"Error in listener for {session_id}: {e}")
                    # Check if session still exists before trying to send error
                    if self.session_mgr.get_session_state(session_id):
                        await self.send_to_node(state.node_id,
                                                state.username, f"ERROR: {e}\n")
                    else:
                        log.info(f'Session {session_id} expired during error handling, terminating listener')
                        break

            log.info(f'BBS listener for {session_id} terminated')

        task = self._create_monitored_task(listen(), f"bbs_listener_{session_id}")
        self.listeners[session_id] = task

    #------------------------------------------------------------
    # meshcore event handlers
    #------------------------------------------------------------

    async def _register_event_handlers(self):
        try:
            self.subs.append(self.meshcore.subscribe(
                EventType.CONTACT_MSG_RECV,
                self.safe_handler(self._handle_mc_message)
            ))
            self.subs.append(self.meshcore.subscribe(
                EventType.ADVERTISEMENT,
                self.safe_handler(self.contact_manager.handle_advert)
            ))
            self.subs.append(self.meshcore.subscribe(
                EventType.NEW_CONTACT,
                self.safe_handler(self.contact_manager.handle_advert)
            ))
            self.subs.append(self.meshcore.subscribe(
                EventType.ACK,
                self.safe_handler(self._handle_acks)
            ))
            await self.meshcore.start_auto_message_fetching()
            log.debug("Event subscriptions registered")
        except Exception as e:
            log.error(f"Failed to register handlers: {e}")
            raise

    # with any luck, this will catch whatever is halting the event processing
    # loop.  Search for this "Handler X crashed" string in the log file if
    # the bbs goes silent again.
    def safe_handler(self, handler):
        async def wrapper(*args, **kwargs):
            try:
                await handler(*args, **kwargs)
            except Exception as e:
                log.exception(f"Handler {handler.__name__} crashed: {e}")
        return wrapper

    async def _handle_acks(self, event):
        """Cache received acks in self._acks.  Check for received acks with
        await self.get_ack()."""
        if hasattr(event, 'payload') and 'code' in event.payload:
            code = event.payload['code']
            log.debug(f'Received an ACK with code {code}')
            now = datetime.now(UTC)
            if code in self._acks:
                if (now - self._acks[code]).seconds > 20:
                    self._acks[code] = datetime.now(UTC)
            else:
                self._acks[code] = datetime.now(UTC)
        else:
            log.warning(f'Received an ACK without a code: {result.payload}')

    async def _handle_mc_message(self, event):
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
                        success = await self.send_to_node(
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
                await self.start_bbs_listener(session_id)
        except Exception as e:
            log.exception(f"Session management failed for {node_id}")
            return  # Can't proceed without session

        # Authentication and workflow processing
        try:
            username = await self._node_has_password_cache(node_id)

            wf_state = self.session_mgr.get_workflow(session_id)

            if wf_state:
                packet = FromUser(
                    session_id=session_id,
                    payload_type=FromUserType.WORKFLOW_RESPONSE,
                    payload=text
                )
            elif username:

                await self.touch_password_cache(username, node_id)

                await self.set_cache_username(username, node_id)

                await self.session_mgr.mark_logged_in(session_id, True)
                self.session_mgr.mark_username(session_id, username)

                # Handle welcome back vs. regular command
                if is_new_session:
                    # This is a reconnection after timeout - send welcome back message
                    welcome_msg = f"Welcome back, {username}! You've been automatically logged in."
                    welcome_msg = await self.insert_prompt(session_id, welcome_msg)

                    inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
                    await asyncio.sleep(inter_packet_delay)
                    success = await self.send_to_node(
                        node_id,
                        username,
                        welcome_msg
                    )
                    if not success:
                        log.warning("No ACK when sending welcome back msg")
                        self.disconnect(session_id)

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
                return await self._start_login_workflow(session_id, node_id)
        except Exception as e:
            log.exception(f"Authentication/workflow processing failed for {node_id}")
            try:
                success = await self.send_to_node(
                    node_id,
                    username,
                    "Authentication error. Please try again."
                )
                if not success:
                    log.warning(f"No ACK sending auth error msg to {username}")
                    self.disconnect(session_id)
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
                    success = await self.send_to_node(node_id, username, msg)
                    if not success:
                        self.disconnect(session_id)
            else:
                touser = await self.insert_prompt(session_id, touser)
                success = await self.send_to_node(node_id, username, touser)
                if not success:
                    self.disconnect(session_id)

        except Exception as e:
            log.exception(f"Command processing/response failed for {node_id}")
            try:
                msg = "Command processing error. Please try again."
                success = await self.send_to_node(node_id, username, msg)
                if not success:
                    self.disconnect(session_id)
            except:
                pass


    #------------------------------------------------------------
    # other helper methods
    #------------------------------------------------------------

    async def _start_login_workflow(self, session_id: str, node_id: str):
        """launch the user into the login workflow. this is a temporary
        workaround to use pure DMs, until there's a KISS modem style meshcore
        radio firmware available, which would enable room-server-style login
        prompts."""
        wf_state = WorkflowState(
            kind="login",
            step=1,
            data={}
        )
        self.session_mgr.set_workflow(session_id, wf_state)
        context = WorkflowContext(
            session_id=session_id,
            db=self.db,
            config=self.config,
            session_mgr=self.session_mgr,
            wf_state=wf_state
        )
        handler = workflow_registry.get("login")
        if handler:
            session_state = self.session_mgr.get_session_state(session_id)
            touser_result = await handler.start(context)
            success = await self.send_to_node(session_state.node_id,
                                              session_state.username,
                                              touser_result)
            if not success:
                self.disconnect(session_id)
            return success
        else:
            success = await self.send_to_node(
                node_id,
                "unknown",
                "Error: Login workflow not found"
            )
            if not success:
                self.disconnect(session_id)

    async def _node_has_password_cache(self, node_id: str) -> bool:
        """Check if node has valid password cache. This function forces
        password expiration such that a user must input their password at
        least every 2 weeks."""
        days = self.config.auth.get("password_cache_duration", 14)
        query = "SELECT last_pw_use, username FROM mc_passwd_cache WHERE node_id = ?"
        try:
            result = await self.db.execute(query, (node_id,))
            if result:
                dt = datetime.strptime(result[0][0], "%Y-%m-%d %H:%M:%S")
                two_weeks_ago = datetime.now() - timedelta(days=days)
                if dt < two_weeks_ago:
                    log.debug(f"Password cache for {node_id} is expired")
                    return False # cache is expired
                return result[0][1] # username, cache is valid
            log.debug(f'No passwd cache DB result: "{result}"')
            return False # has no cache at all
        except Exception as e:
            log.exception(f"Uncaught exception checking for password cache for {node_id}: {e}")
            return False

    async def set_cache_username(self, username: str, node_id: str):
        """this must be called after update_password_cache to
        completely cache a node_id's cache entry"""
        query = "UPDATE mc_passwd_cache SET username = ? WHERE node_id = ?"
        await self.db.execute(query, (username, node_id))

    async def touch_password_cache(self, username: str, node_id: str):
        """update this session to have a fresh password cache time.  the
        cache is not valid until set_cache_username is also called."""
        query = """INSERT INTO mc_passwd_cache
            (node_id, last_pw_use) VALUES (?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                last_pw_use = excluded.last_pw_use
        """
        log.debug(f"Updating MeshCore password cache for {username}")

        now = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
        await self.db.execute(query, (node_id, now))

    async def remove_cache_node_id(self, node_id: str):
        """remove a node_id from the password cache.  to be used when the
        user proactively logs out, not when their session expires due
        to inactivity or connectivity errors."""
        query = "DELETE FROM mc_passwd_cache WHERE node_id = ?"
        await self.db.execute(query, (node_id,))
        log.info(f"Removed {node_id} from MC password cache")

    async def disconnect(self, session_id: str, reading_msg: int=None):
        """Disconnect the named session. To be used when messages can't be
        sent, as a way to preserve the user's experience at least a little
        bit."""
        state = self.session_mgr.get_session_state(session_id)
        node_id = state.node_id

        # cancel in-progress workflows
        workflow_state = self.session_mgr.get_workflow(session_id)
        if workflow_state:
            from citadel.workflows import registry as workflow_registry
                                          
            # Call cleanup on the workflow if it has one           
            handler = workflow_registry.get(workflow_state.kind)
            if handler and hasattr(handler, 'cleanup'):
                try:      
                    await handler.cleanup(context)
                except Exception as e:    
                    log.warning(
                        f"Error during workflow cleanup for {workflow_state.kind}: {e}")                 


        if reading_msg:
            # reset last-read message pointer for this room
            room_id = state.current_room
            room = Room(self.db, self.config, room_id)
            await room.load()
            msg_id = await room.get_last_unread_message_id(state.username)
            await room.revert_last_read(username, msg_id)

        # clean up BBS listener
        self._cleanup_bbs_listener(session_id)

        msg = "Signal lost. Disconnecting your session. Send any text to reconnect."
        self.send_to_node(state.node_id, state.username, msg)

        # cancel session
        self.session_mgr.expire_session(session_id)

    def _setup_session_notifications(self):
        """Set up session manager notification callback for logout
        messages and listener cleanup."""
        def handle_session_expiration(session_id: str, message: str):
            """Handle session expiration: send logout notification and cleanup listeners."""
            log.debug(f"Handling session expiration for {session_id}: {message}")

            try:
                state = self.session_mgr.get_session_state(session_id)
                if state and state.node_id:
                    # Send logout notification using threadsafe task creation
                    log.info(f"Sending logout notification to session {session_id}: {message}")
                    task_result = self._create_monitored_task(
                        self.send_to_node(state.node_id, state.username, message),
                        f"logout_notification_{session_id}"
                    )

                    if task_result:
                        log.info(f"Successfully scheduled logout notification for session {session_id}")
                    else:
                        log.error(f"Failed to schedule logout notification for session {session_id}")
                else:
                    log.warning(f"Cannot send logout notification - no state or node_id for session {session_id}")

                # Clean up BBS listener (critical for preventing hangs!)
                self._cleanup_bbs_listener(session_id)

            except Exception as e:
                log.exception(f"Error handling session expiration for {session_id}: {e}")
                # Still try to cleanup listener even if notification fails
                try:
                    self._cleanup_bbs_listener(session_id)
                except Exception as cleanup_error:
                    log.exception(f"Failed to cleanup listener for expired session {session_id}: {cleanup_error}")

        self.session_mgr.set_notification_callback(handle_session_expiration)

    def _cleanup_bbs_listener(self, session_id: str):
        """Cancel and remove BBS listener for a session."""
        if session_id in self.listeners:
            listener_task = self.listeners[session_id]
            log.info(f"Cancelling BBS listener for expired session {session_id}")

            # Cancel the task
            listener_task.cancel()

            # Remove from listeners dict
            del self.listeners[session_id]

            log.info(f"BBS listener cleanup completed for session {session_id}")
        else:
            log.debug(f"No BBS listener found for session {session_id} during cleanup")

    async def insert_prompt(self, session_id, touser):
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
