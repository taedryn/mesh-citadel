"""This module presents the MqttPublisher class, which publishes
packet telemetry and online/offline status to one or more MQTT
brokers, replacing the standalone meshcore-packet-capture observer
that used to run alongside this BBS.

# Auth

The target brokers (rflab, MeshMapper) are "letsmesh"-style brokers
that authenticate connections via a JWT-like token signed with the
node's own Ed25519 identity key. Signing happens entirely on-device
(via meshcore's commands.sign(), a sign_start/sign_data/sign_finish
handshake) -- the private key never leaves the radio and this module
never sees or handles it directly.

The resulting token deliberately isn't a standard JWT: header and
payload are base64url-encoded JSON as usual, but the signature segment
is lowercase hex, not base64url. This matches what the brokers expect
and must be preserved exactly.

# Topics

Topics follow the "letsmesh" convention: meshcore/{IATA}/{PUBLIC_KEY}/{kind},
where kind is "status" (retained online/offline) or "packets" (one
message per received RF packet).
"""

import asyncio
import base64
import hashlib
import json
import logging
import ssl
import time
from datetime import datetime, UTC

import paho.mqtt.client as mqtt
from meshcore import EventType

log = logging.getLogger(__name__)

DEFAULT_JWT_TTL = 86400
DEFAULT_JWT_RENEW_MARGIN = 21600
RENEWAL_CHECK_INTERVAL = 900
TRACE_PAYLOAD_TYPE = 9


class MqttPublisher:
    def __init__(self, config, meshcore, create_task_func, command_lock):
        self.meshcore = meshcore
        self.create_task_func = create_task_func
        self.command_lock = command_lock

        mc_config = config.transport.get("meshcore", {})
        self.mqtt_config = mc_config.get("mqtt", {})
        # Read from config, not meshcore.self_info["name"] -- self_info is
        # only populated once at connect time and isn't refreshed after
        # start_meshcore() later calls set_name(), so it can go stale.
        self.node_name = mc_config.get("name", "Mesh-Citadel BBS")

        self.device_public_key = ""
        self._brokers = {}
        self._running = False
        self._renewal_task = None

    #------------------------------------------------------------
    # Lifecycle
    #------------------------------------------------------------

    async def start(self):
        """Start publishing to all enabled, configured brokers. A no-op
        (with a log line) if MQTT publishing isn't configured/enabled,
        or if there's no live MeshCore connection to sign with."""
        if not self.meshcore:
            log.warning("MqttPublisher: no MeshCore connection, skipping")
            return

        if not self.mqtt_config.get("enabled", False):
            log.info("MQTT publishing disabled in config")
            return

        self.device_public_key = self.meshcore.self_info.get("public_key", "").upper()
        if not self.device_public_key:
            log.error("MqttPublisher: no device public key available, skipping")
            return

        brokers = self.mqtt_config.get("brokers", [])
        enabled_brokers = [b for b in brokers if b.get("enabled", False)]
        if not enabled_brokers:
            log.info("No enabled MQTT brokers configured")
            return

        for broker_cfg in enabled_brokers:
            await self._start_broker(broker_cfg)

        if not self._brokers:
            log.warning("MqttPublisher: no brokers connected successfully")
            return

        self._running = True
        self._renewal_task = self.create_task_func(
            self._renewal_loop(), "mqtt_jwt_renewal")
        log.info(f"MqttPublisher started with {len(self._brokers)} broker(s)")

    async def stop(self):
        """Cancel renewal, announce offline, and tear down all broker
        connections."""
        self._running = False

        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except (asyncio.CancelledError, Exception):
                pass

        for name, broker in self._brokers.items():
            client = broker["client"]
            try:
                topic = self._topic(broker["cfg"], "status")
                client.publish(
                    topic, json.dumps(self._status_payload("offline")),
                    qos=1, retain=True
                )
            except Exception as err:
                log.debug(f"MQTT[{name}]: offline publish failed: {err}")
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass

        self._brokers.clear()
        log.info("MqttPublisher stopped")

    #------------------------------------------------------------
    # Broker setup
    #------------------------------------------------------------

    async def _start_broker(self, broker_cfg):
        name = broker_cfg.get("name")
        host = broker_cfg.get("host")
        if not name or not host:
            log.error(f"Skipping malformed MQTT broker entry: {broker_cfg}")
            return

        try:
            jwt, expiry = await self._generate_jwt(broker_cfg)
        except Exception as err:
            log.error(f"MQTT[{name}]: failed to generate initial JWT, skipping: {err}")
            return

        port = broker_cfg.get("port", 443)
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"mesh-citadel-{self.device_public_key[:12]}-{name}",
            transport="websockets"
        )
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.username_pw_set(f"v1_{self.device_public_key}", jwt)
        client.user_data_set(name)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect

        status_topic = self._topic(broker_cfg, "status")
        offline_payload = json.dumps(self._status_payload("offline"))
        # Must be set before connect() -- an LWT set afterward is silently
        # ignored by the broker.
        client.will_set(status_topic, offline_payload, qos=1, retain=True)

        self._brokers[name] = {"cfg": broker_cfg, "client": client, "jwt_expiry": expiry}

        try:
            await asyncio.to_thread(client.connect, host, port, keepalive=60)
        except Exception as err:
            log.error(f"MQTT[{name}]: connect failed: {err}")
            del self._brokers[name]
            return

        client.loop_start()
        log.info(f"MQTT[{name}]: connecting to {host}:{port}")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        broker_name = userdata
        if reason_code.is_failure:
            log.error(f"MQTT[{broker_name}]: connect failed, reason_code={reason_code}")
            return

        log.info(f"MQTT[{broker_name}]: connected (reason_code={reason_code})")
        broker = self._brokers.get(broker_name)
        if not broker:
            return
        topic = self._topic(broker["cfg"], "status")
        client.publish(
            topic, json.dumps(self._status_payload("online")),
            qos=1, retain=True
        )

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        log.warning(f"MQTT[{userdata}]: disconnected, reason_code={reason_code}")

    #------------------------------------------------------------
    # JWT / on-device signing
    #------------------------------------------------------------

    async def _generate_jwt(self, broker_cfg):
        """Build and sign a JWT-like token for the given broker using the
        node's own Ed25519 identity key. Signing happens on-device; we
        never see the private key. Returns (token, expiry_epoch)."""
        now = int(time.time())
        ttl = self.mqtt_config.get("jwt_ttl", DEFAULT_JWT_TTL)
        exp = now + ttl

        header = {"alg": "Ed25519", "typ": "JWT"}
        payload = {
            "publicKey": self.device_public_key,
            "iat": now,
            "exp": exp,
            "aud": broker_cfg.get("audience", broker_cfg.get("host", "")),
        }
        header_b64 = self._b64url_json(header)
        payload_b64 = self._b64url_json(payload)
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

        # commands.sign() is a stateful multi-frame handshake
        # (sign_start/sign_data/sign_finish) against the same serial
        # connection other commands use -- must not be interleaved.
        async with self.command_lock:
            result = await self.meshcore.commands.sign(signing_input)

        if result.type != EventType.SIGNATURE:
            raise RuntimeError(f"device signing failed: {result.payload}")

        # Non-standard JWT quirk, preserved intentionally: the signature
        # segment is lowercase hex, not base64url, to match what these
        # brokers expect.
        signature_hex = result.payload["signature"].hex()
        token = f"{header_b64}.{payload_b64}.{signature_hex}"
        return token, exp

    async def _renewal_loop(self):
        margin = self.mqtt_config.get("jwt_renew_margin", DEFAULT_JWT_RENEW_MARGIN)
        while self._running:
            await asyncio.sleep(RENEWAL_CHECK_INTERVAL)
            now = int(time.time())
            for name, broker in list(self._brokers.items()):
                if broker["jwt_expiry"] - now > margin:
                    continue
                try:
                    jwt, expiry = await self._generate_jwt(broker["cfg"])
                    broker["client"].username_pw_set(f"v1_{self.device_public_key}", jwt)
                    broker["jwt_expiry"] = expiry
                    # username_pw_set() alone doesn't affect an already-open
                    # connection -- only a fresh CONNECT sends credentials.
                    await asyncio.to_thread(broker["client"].reconnect)
                    log.info(f"MQTT[{name}]: JWT renewed, new expiry {expiry}")
                except Exception as err:
                    log.error(f"MQTT[{name}]: JWT renewal failed: {err}")

    @staticmethod
    def _b64url_json(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    #------------------------------------------------------------
    # Packet publishing
    #------------------------------------------------------------

    async def handle_rx_log_data(self, event):
        """Subscribed to EventType.RX_LOG_DATA; publishes one "packets"
        message per received RF packet to every connected broker."""
        if not self._brokers:
            return

        data = event.payload or {}
        raw_hex = data.get("payload")
        if not raw_hex:
            return

        now = datetime.now(UTC)
        payload_type = data.get("payload_type")
        pkt_payload = data.get("pkt_payload") or b""
        path_len = data.get("path_len") or 0

        packet = {
            "origin": self.node_name,
            "origin_id": self.device_public_key,
            "timestamp": now.isoformat(),
            "type": "PACKET",
            "direction": "rx",
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%d/%m/%Y"),
            "len": str(data.get("payload_length", 0)),
            "raw": raw_hex.upper(),
            "SNR": str(data.get("snr", "")),
            "RSSI": str(data.get("rssi", "")),
            "hash": self._calculate_packet_hash(payload_type, path_len, pkt_payload),
        }

        if self.mqtt_config.get("include_header_fields", True):
            packet["route_type"] = data.get("route_type")
            packet["payload_type"] = payload_type
            packet["path_len"] = path_len
            packet["path"] = data.get("path", "")

        payload_json = json.dumps(packet)
        for name, broker in self._brokers.items():
            topic = self._topic(broker["cfg"], "packets")
            try:
                broker["client"].publish(topic, payload_json, qos=0, retain=False)
            except Exception as err:
                log.debug(f"MQTT[{name}]: packet publish failed: {err}")

    @staticmethod
    def _calculate_packet_hash(payload_type, path_len, pkt_payload) -> str:
        """sha256 over payload_type byte (+ 2-byte-LE path_len, TRACE
        packets only) + payload bytes, first 16 hex chars, uppercased.
        This is a different value from meshcore's own internal pkt_hash
        dedup field -- don't conflate the two."""
        prefix = bytes([payload_type]) if payload_type is not None else b""
        if payload_type == TRACE_PAYLOAD_TYPE:
            prefix += int(path_len).to_bytes(2, "little")
        return hashlib.sha256(prefix + pkt_payload).hexdigest()[:16].upper()

    #------------------------------------------------------------
    # Shared helpers
    #------------------------------------------------------------

    def _topic(self, broker_cfg, kind: str) -> str:
        iata = (broker_cfg.get("iata") or self.mqtt_config.get("iata", "LOC")).upper()
        return f"meshcore/{iata}/{self.device_public_key}/{kind}"

    def _status_payload(self, status: str) -> dict:
        return {
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "origin": self.node_name,
            "origin_id": self.device_public_key,
        }
