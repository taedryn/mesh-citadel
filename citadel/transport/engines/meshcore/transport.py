import asyncio
import logging
from datetime import datetime
from serial import SerialException
from meshcore.serial import MeshCoreSerial
from meshcore.packet import MeshCorePacket
from meshcore.command import MeshCoreCommand
from meshcore.event import EventType

log = logging.getLogger(__name__)


class MeshCoreTransport:
    def __init__(self, device_path, session_mgr, config, db):
        self.device_path = device_path
        self.session_mgr = session_mgr
        self.config = config
        self.db = db
        self.meshcore = None
        self._running = False

    async def start(self):
        try:
            self.meshcore = MeshCoreSerial(self.device_path)
            self._register_event_handlers()
            await self.meshcore.connect()
            self._running = True
            log.info(f"MeshCore device connected at {self.device_path}")
        except SerialException as e:
            log.error(f"Serial connection failed: {e}")
            raise
        except OSError as e:
            log.error(f"OS error during connection: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected startup error: {e}")
            raise

    async def stop(self):
        self._running = False
        if self.meshcore:
            try:
                await self.meshcore.disconnect()
                log.info(f"MeshCore device disconnected")
            except SerialException as e:
                log.warning(f"Serial disconnect error: {e}")
            except OSError as e:
                log.warning(f"OS error during disconnect: {e}")
            except Exception as e:
                log.warning(f"Unexpected disconnect error: {e}")
        else:
            log.warning("MeshCoreTransport.stop() called when already stopped")

    def _register_event_handlers(self):
        try:
            self.meshcore.subscribe(
                EventType.RESP_CODE_CONTACT_MSG_RECV_V3,
                self._handle_message
            )
            self.meshcore.subscribe(
                EventType.PUSH_CODE_ADVERT,
                self._handle_advert
            )
            self.meshcore.subscribe(
                EventType.PUSH_CODE_SEND_CONFIRMED,
                self._handle_confirmation
            )
            log.debug("Event subscriptions registered")
        except Exception as e:
            log.error(f"Failed to register handlers: {e}")
            raise

    def _handle_message(self, packet: MeshCorePacket):
        log.debug(f"Received message packet: {packet}")
        try:
            node_id = packet.sender_id
            payload = packet.payload.decode("utf-8")
            # TODO: this method needs to be created
            session_id = self.session_mgr.get_session_by_node(node_id)

            if not session_id:
                session_id = self.session_mgr.create_session()
                # TODO: this method needs to be created
                self.session_mgr.bind_node_to_session(node_id, session_id)

            if self._node_has_password_cache(node_id):
                self.session_mgr.mark_logged_in(session_id)
                log.info(f"Auto-login for cached node {node_id}")

            if not self.session_mgr.is_logged_in(session_id):
                # Treat payload as password attempt
                if self.session_mgr.authenticate(session_id, payload):
                    self.session_mgr.mark_logged_in(session_id)
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
            msg = FromUser(session_id=session_id, text=payload)
            asyncio.create_task(
                # TODO: this isn't a real function. send to command
                # processor instead
                self.session_mgr.process_input(session_id, msg)
            )
        except Exception as e:
            log.error(f"Error handling message from {node_id}: {e}")

    async def _send_login_prompt(self, session_id: str, node_id: str):
        payload = {
            "type": "room_server_handshake",
            "room_name": "Citadel BBS",
            "login_required": True,
            "challenge": "Please enter your password"
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

            self.db.execute(
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
