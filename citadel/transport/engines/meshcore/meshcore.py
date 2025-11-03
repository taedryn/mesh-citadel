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

from citadel.commands.processor import CommandProcessor
from citadel.message.manager import format_timestamp
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

    #------------------------------------------------------------
    # process lifecycle controls
    #------------------------------------------------------------
    async def start(self):
        try:
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
            raise TransportError(f"Unable to sync time: {result.payload}")

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
        self.tasks.append(asyncio.create_task(scheduler.interval_advert()))
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

    async def send_to_node(self, session_id: str, message: str | ToUser | list):
        """Send a message to a mesh node via MeshCore. """
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
        node_id = self.session_mgr.get_session_state(session_id).node_id

        packets = self._chunk_message(text, max_packet_length)
        inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
        for packet in packets:
            sent = await self._send_packet(node_id, packet)
            await asyncio.sleep(inter_packet_delay)

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

    async def _send_packet(self, node_id, chunk) -> bool:
        """Send a single packet to a node. This assumes that the packet
        is a safe size to send. Blocks until the ack has been
        received."""
        log.debug(f'Sending packet to {node_id}: {len(chunk)} bytes, content: "{chunk[:50]}..."')

        # Use the pre-configured send method
        result = await self.send_msg(node_id, chunk)

        if result and result.type == EventType.ERROR:
            log.error(f"Unable to send '{chunk[:50]}...' to '{node_id}'! {result.payload}")
            return False
        elif not result:
            log.error(f"No result from send command for '{chunk[:50]}...' to '{node_id}'")
            return False

        # Wait for ACK with the configured timeout
        exp_ack = result.payload["expected_ack"].hex()
        ack_timeout = self.mc_config.get("ack_timeout", 8)  # Increased from 5 to 8 seconds
        log.debug(f"Waiting for ACK {exp_ack} with timeout {ack_timeout}s")

        ack = await self.meshcore.wait_for_event(
            EventType.ACK,
            attribute_filters={"code": exp_ack},
            timeout=ack_timeout
        )

        if ack:
            log.debug(f"✅ ACK received for packet to {node_id}")
            return True

        # Log ACK timeout for debugging (this is normal in mesh communication)
        log.debug(f"❌ ACK timeout ({ack_timeout}s) for packet '{chunk[:30]}...' to {node_id}")
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

    #------------------------------------------------------------
    # bbs event handlers
    #------------------------------------------------------------

    async def start_bbs_listener(self, session_id):
        if session_id in self.listeners:
            return  # Already listening

        async def listen():
            state = self.session_mgr.get_session_state(session_id)
            log.info(f'Starting BBS listener for "{session_id}"')
            while True:
                try:
                    log.debug(f'Waiting for BBS msgs for {session_id}')
                    message = await state.msg_queue.get()
                    if isinstance(message, list):
                        log.debug('BBS message is a LIST')
                    else:
                        log.debug('BBS message is NOT a list')
                    log.debug(f'Received BBS msg for {session_id}: {message}')
                    if isinstance(message, list):
                        for msg in message:
                            await self.send_to_node(session_id, msg)
                    else:
                        await self.send_to_node(session_id, message)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error(f"Error in listener for {session_id}: {e}")
                    await self.send_to_node(session_id, f"ERROR: {e}\n")

        task = asyncio.create_task(listen())
        self.listeners[session_id] = task

    #------------------------------------------------------------
    # meshcore event handlers
    #------------------------------------------------------------

    async def _register_event_handlers(self):
        try:
            self.subs.append(self.meshcore.subscribe(
                EventType.CONTACT_MSG_RECV,
                self._handle_mc_message
            ))
            self.subs.append(self.meshcore.subscribe(
                EventType.ADVERTISEMENT,
                self.contact_manager.handle_advert
            ))
            self.subs.append(self.meshcore.subscribe(
                EventType.NEW_CONTACT,
                self.contact_manager.handle_advert
            ))
            await self.meshcore.start_auto_message_fetching()
            log.debug("Event subscriptions registered")
        except Exception as e:
            log.error(f"Failed to register handlers: {e}")
            raise

    async def _handle_mc_message(self, event):
        log.debug(f"Received message event: {event}")
        data = event.payload
        node_id = data['pubkey_prefix']
        text = data['text']
        if await self.dedupe.is_duplicate(node_id, text):
            log.debug(f'Oops, {node_id}: {text} is a dupe, skipping')
            return

        session_id = self.session_mgr.get_session_by_node_id(node_id)
        if not session_id:
            session_id = self.session_mgr.create_session(node_id)
            await self.start_bbs_listener(session_id)
            
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
            self.session_mgr.mark_logged_in(session_id, True)
            self.session_mgr.mark_username(session_id, username)
            command = self.text_parser.parse_command(text)
            packet = FromUser(
                session_id=session_id,
                payload_type=FromUserType.COMMAND,
                payload=command
            )
        else:
            log.debug(f'No pw cache found for {node_id}, sending to login')
            return await self._start_login_workflow(session_id, node_id) 
        touser = await self.command_processor.process(packet)
        # pause the bbs just a moment before sending the command response
        inter_packet_delay = self.mc_config.get("inter_packet_delay", 0.5)
        await asyncio.sleep(inter_packet_delay)
        if isinstance(touser, list):
            last_msg = len(touser) - 1
            for i, msg in enumerate(touser):
                if i == last_msg:
                    msg = await self.insert_prompt(session_id, msg)
                await self.send_to_node(session_id, msg)
        else:
            touser = await self.insert_prompt(session_id, touser)
            await self.send_to_node(session_id, touser)


    async def _handle_mc_advert(self, event):
        log.debug(f"Received advert packet: {event}")
        try:
            pubkey = event.payload['public_key']
            node_id = pubkey[:16]

            await self.db.execute(
                """
                INSERT INTO mc_adverts (node_id, public_key, last_heard)
                VALUES (?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    public_key = excluded.public_key,
                    last_heard = excluded.last_heard
                """,
                (
                    node_id,
                    pubkey,
                    datetime.now(UTC).isoformat(),
                )
            )
            log.info(f"Updated advert for node {node_id}")
        except KeyError as e:
            log.error(f"Missing required field in advert from {node_id}: {e}")
        except (TypeError, ValueError) as e:
            log.error(f"Invalid advert data format from {node_id}: {e}")

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
            await self.send_to_node(session_id, "Sending you to login")
            touser_result = await handler.start(context)
            return await self.send_to_node(session_id, touser_result)
        else:
            return await self.send_to_node(
                session_id,
                "Error: Login workflow not found"
            )

    async def _node_has_password_cache(self, node_id: str) -> bool:
        """Check if node has valid password cache. This function forces
        password expiration such that a user must input their password at
        least every 2 weeks."""
        days = self.config.auth.get("password_cache_duration", 14)
        query = "SELECT last_pw_use, username FROM mc_passwd_cache WHERE node_id = ?"
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

    def _setup_session_notifications(self):
        """Set up session manager notification callback for logout messages."""
        def send_logout_notification(session_id: str, message: str):
            """Send logout notification to a session via meshcore."""
            try:
                # Look up session state to get node_id
                state = self.session_mgr.get_session_state(session_id)
                if state and state.node_id:
                    # Use asyncio to schedule the async send_to_node call
                    asyncio.create_task(self.send_to_node(session_id, message))
                    log.debug(f"Scheduled logout notification for session {session_id}")
                else:
                    log.warning(f"Cannot send logout notification - no node_id for session {session_id}")
            except (OSError, RuntimeError) as e:
                log.error(f"Error sending logout notification to session {session_id}: {e}")
                raise

        self.session_mgr.set_notification_callback(send_logout_notification)

    async def insert_prompt(self, session_id, touser):
        if self.session_mgr.get_workflow(session_id):
            return touser

        session_state = self.session_mgr.get_session_state(session_id)
        if not session_state or not session_state.current_room:
            prompt = "What now? (H for help)"
        else:
            # Get room name
            from citadel.room.room import Room
            try:
                room = Room(self.db, self.config, session_state.current_room)
                await room.load()
                room_name = room.name
            except Exception:
                room_name = f"Room {session_state.current_room}"
            prompt = f"In {room_name}. What now? (H for help)"

        if isinstance(touser, ToUser):
            if touser.message:
                touser.message.content += f'\n{prompt}'
            else:
                touser.text += f'\n{prompt}'
        elif isinstance(touser, str):
            touser += f'\n{prompt}'

        return touser


class AdvertScheduler:
    """schedule an advert in a cancelable way.  modify the
    'advert_interval' setting in config.yaml with the number of hours
    between adverts.  defaults to 6 if no setting found."""
    def __init__(self, config, meshcore):
        self.config = config
        self.meshcore = meshcore
        self._stop_event = asyncio.Event()

    async def interval_advert(self):
        interval = self.config.transport.get("meshcore", {}).get("advert_interval", 6)
        try:
            while not self._stop_event.is_set():
                if self.meshcore:
                    # TODO: change this to flood=True when we're done
                    # testing quite so much
                    flood = False
                    log.info(f"Sending advert (flood={flood})")
                    result = await self.meshcore.commands.send_advert(flood=flood)
                    if result.type == EventType.ERROR:
                        raise TransportError(f"Unable to send advert: {result.payload}")
                try:
                    # Wait with cancellation support
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval * 3600)
                except asyncio.TimeoutError:
                    pass  # Timeout means it's time to run again
        except asyncio.CancelledError:
            log.info("interval_advert was cancelled")
        finally:
            log.info("interval_advert shutdown complete")

    def stop(self):
        self._stop_event.set()


class MessageDeduplicator:
    """a simple class to provide message de-duplication services"""
    def __init__(self, ttl=10):
        self.seen = {}  # message_hash: timestamp
        self.ttl = ttl  # seconds
        self._lock = asyncio.Lock()

    async def is_duplicate(self, node_id: str, message: str) -> bool:
        text = '::'.join([node_id, message])
        msg_hash = hashlib.sha256(text.encode()).hexdigest()
        async with self._lock:
            now = time.time()
            if msg_hash in self.seen and now - self.seen[msg_hash] < self.ttl:
                return True
            self.seen[msg_hash] = now
            return False

    async def clear_expired(self):
        """call this frequently to avoid the message hash table growing
        too large"""
        now = time.time()
        async with self._lock:
            for msg_hash, timestamp in self.seen.items():
                if now - self.seen[msg_hash] > self.ttl:
                    del self.seen[msg_hash]
