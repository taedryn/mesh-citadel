import asyncio
import logging
from datetime import datetime
from serial import SerialException
from meshcore.serial import MeshCoreSerial
from meshcore.packet import MeshCorePacket
from meshcore.command import MeshCoreCommand
from meshcore.event import EventType
from meshcore import MeshCore, EventType

from citadel.transport.packets import FromUser, FromUserType, ToUser
from citadel.transport.manager import TransportError
from citadel.commands.processor import CommandProcessor
from citadel.transport.parser import TextParser

log = logging.getLogger(__name__)


class MeshCoreTransport:
    def __init__(self, session_mgr, config, db):
        self.session_mgr = session_mgr
        self.config = config
        self.db = db
        self.command_processor = CommandProcessor(config, db, session_mgr)
        self.text_parser = TextParser()
        self.meshcore = None
        self._running = False
        self.tasks = []

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

    async def interval_advert(self):
        interval = self.config.transport.get("meshcore", {}).get("advert_interval", 6)
        while True:
            if self.meshcore:
                self.meshcore.commands.send_advert(flood=True)
            await asyncio.sleep(interval * 60 * 60) # interval is hours

    async def start_meshcore(self):
        mc_config = self.config.transport.get("meshcore", {})
        serial_port = mc_config.get("serial_port", "/dev/ttyUSB0")
        baud_rate = mc_config.get("baud_rate", 115200)

        # radio settings default to US Recommended settings
        frequency = mc_config.get("frequency", 910.525)
        bandwidth = mc_config.get("bandwidth", 62.5)
        spreading_factor = mc_config.get("spreading_factor", 7)
        coding_rate = mc_config.get("coding_rate", 5)
        tx_power = mc_config.get("tx_power", 22)
        node_name = mc_config.get("name", "Mesh-Citadel BBS")

        log.info(f"Connecting MeshCore transport at {serial_port}")
        mc = await MeshCore.create_serial(serial_port, baudrate=baud_rate)
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
        log.info("Sending MeshCore flood advert")
        result = await mc.commands.send_advert(flood=True)
        if result.type == EventType.ERROR:
            raise TransportError(f"Unable to send advert: {result.payload}")
        self.tasks.append(asyncio.create_task(self.interval_advert()))
        self.meshcore = mc


    async def stop(self):
        if self._running:
            for task in self.tasks:
                task.cancel()
                await task
            if self.meshcore:
                try:
                    self.meshcore.stop()
                    log.info("MeshCore transport shut down")
            self._running = False
        else:
            log.warning("MeshCoreTransport.stop() called when already stopped")

    async def _register_event_handlers(self):
        try:
            self.priv_sub = self.meshcore.subscribe(
                EventType.CONTACT_MGS_RECV,
                self._handle_message
            )
            self.chan_sub = self.meshcore.subscribe(
                EventType.CHANNEL_MSG_RECV
                self._handle_advert
            )
            await self.meshcore.start_auto_message_fetching()
            log.debug("Event subscriptions registered")
        except Exception as e:
            log.error(f"Failed to register handlers: {e}")
            raise

    def _handle_message(self, packet: MeshCorePacket):
        log.debug(f"Received message packet: {packet}")
        try:
            node_id = packet.sender_id
            payload = packet.payload.decode("utf-8")
            session_id = self.session_mgr.get_session_by_node_id(node_id)

            if not session_id:
                session_id = self.session_mgr.create_session(node_id)

            if self._node_has_password_cache(node_id):
                self.session_mgr.mark_logged_in(session_id)
                self.session_mgr.touch_session(sesson_id)
                log.info(f"Auto-login for cached node {node_id}")

            if not self.session_mgr.is_logged_in(session_id):
                if not self.login_prompted.get(session_id, False):
                    self.login_prompted[session_id] = True
                   return self._send_login_prompt(session_id, node_id) 
                # Treat payload as password attempt
                if self.session_mgr.authenticate(session_id, payload):
                    self.session_mgr.mark_logged_in(session_id)
                    self.session_mgr.touch_session(sesson_id)
                    self.login_prompted[session_id] = False
                    log.info(f"Login successful for {node_id}")
                    asyncio.create_task(
                        self.send_to_node(session_id, "Login successful.")
                    )
                else:
                    log.info(f"Login failed for {node_id}")
                    asyncio.create_task(
                        self.send_to_node(session_id, "Invalid password.")
                    )
                return

            # If logged in, route to command processor
            command = self.text_parser.parse_command(payload)
            packet = FromUser(
                session_id=session_id,
                payload_type=FromUserType.COMMAND,
                payload=command
            )
            asyncio.create_task(
                self._process_command_packet(packet)
            )
        except Exception as e:
            log.error(f"Error handling message from {node_id}: {e}")

    async def _send_login_prompt(self, session_id: str, node_id: str):
        bbs_name = self.config.bbs.get("name", "Mesh-Citadel BBS")
        payload = {
            "type": "room_server_handshake",
            "room_name": bbs_name,
            "login_required": True,
            "challenge": "Please enter your login credentials",
            "username_required": True
        }
        try:
            command = MeshCoreCommand.send_application_message(payload)
            await self.meshcore.send_command(command)
            log.debug(f"Sent login prompt to {node_id}")
        except Exception as e:
            log.error(f"Failed to send login prompt to {node_id}: {e}")

    def _handle_advert(self, packet: MeshCorePacket):
        log.debug(f"Received advert packet: {packet}")
        try:
            node_id = packet.sender_id
            advert = packet.payload  # Assumes structured dict

            await self.db.execute(
                """
                INSERT INTO mc_adverts (
                    node_id, public_key, node_type,
                    last_heard, signal_strength, hop_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    public_key = excluded.public_key,
                    node_type = excluded.node_type,
                    last_heard = excluded.last_heard,
                    signal_strength = excluded.signal_strength,
                    hop_count = excluded.hop_count
                """,
                (
                    node_id,
                    advert["public_key"],
                    advert.get("node_type", "user"),
                    datetime.now().isoformat(),
                    advert.get("signal_strength", 0),
                    advert.get("hop_count", 0)
                )
            )
            log.debug(f"Updated advert for node {node_id}")
        except KeyError as e:
            log.error(f"Missing required field in advert from {node_id}: {e}")
        except (TypeError, ValueError) as e:
            log.error(f"Invalid advert data format from {node_id}: {e}")

    async def _handle_confirmation(self, packet: MeshCorePacket):
        """Handle delivery confirmation from MeshCore."""
        try:
            log.debug(f"Message delivery confirmed: {packet}")
            # TODO: Update packet tracking table with delivery status
            # For now, just log the confirmation
        except Exception as e:
            log.error(f"Error handling confirmation: {e}")

    def _node_has_password_cache(self, node_id: str) -> bool:
        """Check if node has valid password cache. This function forces
        password expiration such that a user must input their password at
        least every 2 weeks."""
        days = self.config.auth.get("password_cache_duration", 14)
        query = "SELECT last_pw_use FROM mc_passwd_cache WHERE node_id = ?"
        result = await self.db.execute(query, (node_id,))
        if result:
            dt = datetime.strptime(result[0][0], "%Y-%m-%d %H:%M:%S")
            two_weeks_ago = datetime.utcnow() - timedelta(days=days)
            if dt < two_weeks_ago:
                log.debug(f"Password cache for {node_id} is expired")
                return False # cache is expired
            return True # has a cache and it's not expired
        return False # has no cache at all

    async def send_to_node(self, session_id: str, message: str):
        """Send a message to a mesh node via MeshCore.

        TODO: This method needs full implementation:
        1. Look up node_id from session_id using SessionManager.get_nodes_for_session()
        2. Handle message chunking if message exceeds MeshCore packet size limits
        3. Create MeshCoreCommand to send application message
        4. Queue message for retry if delivery fails
        """
        log.debug(f"TODO: Send message to session {session_id}: {message[:50]}...")
        # Placeholder implementation
        pass
