import asyncio
import logging
from datetime import datetime, UTC, timedelta
from serial import SerialException
from meshcore import MeshCore, EventType

from citadel.transport.packets import FromUser, FromUserType, ToUser
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser
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
        self.text_parser = TextParser()
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
            await self._register_event_handlers()
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

        log.info(f"Connecting MeshCore transport at {serial_port}")
        mc = await MeshCore.create_serial(serial_port, baud_rate)
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
        from citadel.transport.manager import TransportError
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
        self.scheds = []
        # set up adverts, one right now, then every N hours (config.yaml)
        scheduler = AdvertScheduler(self.config, mc)
        self.scheds.append(scheduler)
        self.tasks.append(asyncio.create_task(scheduler.interval_advert()))
        self.meshcore = mc

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

    async def send_to_node(self, session_id: str, message: str | ToUser):
        """Send a message to a mesh node via MeshCore. """
        # TODO: probably need to handle ToUser packets more intelligently than
        # this
        if isinstance(message, ToUser):
            if message.message:
                log.debug("Formatting BBS message")
                message = self.format_message(message.message)
            else:
                message = message.text
        # TODO: figure out actual packet size measurement algo
        max_packet_length = 140 # stay safe for now
        node_id = self.session_mgr.get_session_state(session_id).node_id

        packets = self._chunk_message(message, max_packet_length)
        for packet in packets:
            await self._send_packet(node_id, packet)

    #------------------------------------------------------------
    # communication helpers
    #------------------------------------------------------------

    def format_message(self, message) -> str:
        timestamp = dateparse(message.timestamp).strftime('%d%b%y %H:%M')
        header = f"[{message.id}] From: {message.display_name} ({message.sender}) - {timestamp}"
        content = "[Message from blocked sender]" if message.blocked else message.content                                                                   
        return f"{header}\n{content}"

    async def _send_packet(self, node_id, chunk) -> bool:
        """Send a single packet to a node. This assumes that the packet
        is a safe size to send. Blocks until the ack has been
        received."""
        log.debug(f'Sending packet to {node_id}: {chunk}')
        result = await self.meshcore.commands.send_msg(node_id, chunk)
        if result.type == EventType.ERROR:
            log.error(f"Unable to send '{chunk}' to '{node_id}'! "
                      f"{result.payload}")
            return False
        exp_ack = result.payload["expected_ack"].hex()
        ack = await self.meshcore.wait_for_event(
            EventType.ACK,
            attribute_filters={"code": exp_ack},
            timeout=self.mc_config.get("ack_timeout", 5)
        )
        if ack:
            return True
        # this is a normal part of mesh communication, so we don't need
        # to log it absolutely every time it happens in prod conditions
        log.debug(f"Didn't receive an ack to '{chunk}'")
        return False

    def _chunk_message(self, message, max_packet_length):
        """split the message into appropriately sized chunks"""
        words = message.split()
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
                    log.debug(f'Received BBS msg for {session_id}: {message}')
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
                self._handle_mc_advert
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
            await self.touch_password_cache(session_id)
            await self.set_cache_username(session_id)
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
        return await self.send_to_node(session_id, touser)


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

    async def set_cache_username(self, session_id: str):
        """this must be called after update_password_cache to
        completely cache a node_id's cache entry"""
        query = "UPDATE mc_passwd_cache SET username = ? WHERE node_id = ?"
        state = self.session_mgr.get_session_state(session_id)
        await self.db.execute(query, (state.username, state.node_id))

    async def touch_password_cache(self, session_id: str):
        """update this session to have a fresh password cache time.  the
        cache is not valid until set_cache_username is also called."""
        query = """INSERT INTO mc_passwd_cache
            (node_id, last_pw_use) VALUES (?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                last_pw_use = excluded.last_pw_use
        """
        state = self.session_mgr.get_session_state(session_id)
        log.debug(f"Updating MeshCore password cache for {state.username}")

        now = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
        await self.db.execute(query, (state.node_id, now))



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

