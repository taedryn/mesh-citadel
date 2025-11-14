"""
MeshCore Protocol Handler

Handles low-level packet transmission, chunking, ACK management, and message formatting.
Extracted from the main transport engine for better separation of concerns.
"""

import asyncio
import logging
from datetime import datetime, UTC
from serial import SerialException
from typing import Union, List

from citadel.message.manager import format_timestamp
from citadel.transport.packets import ToUser
from citadel.commands.responses import MessageResponse
from meshcore import EventType
from dateutil.parser import parse as dateparse

log = logging.getLogger(__name__)


class ProtocolHandler:
    """Handles low-level MeshCore protocol operations."""

    def __init__(self, config, db, meshcore):
        self.config = config
        self.db = db
        self.meshcore = meshcore
        self._acks = {}  # ACK tracking dictionary
        # Derive mc_config from main config
        self.mc_config = config.transport.get("meshcore", {})
        # Set up the appropriate send method
        self._setup_send_method()

    def _setup_send_method(self):
        """Set up the send method with retry configuration."""
        if hasattr(self.meshcore, 'commands') and hasattr(self.meshcore.commands, 'send_msg_with_retry'):
            # Use MeshCore's built-in retry functionality
            self.send_msg = self.meshcore.commands.send_msg_with_retry
        else:
            # Fallback: create manual retry wrapper
            async def send_with_manual_retry(node_id, message):
                max_retries = self.mc_config.get("max_retries", 3)
                retry_delay = self.mc_config.get("retry_delay", 1.0)

                for attempt in range(max_retries):
                    try:
                        result = await self.meshcore.commands.send_msg(node_id, message)
                        if result:
                            return result
                    except Exception as e:
                        log.warning(f"Send attempt {attempt + 1} failed: {e}")

                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

                return None

            self.send_msg = send_with_manual_retry

    def format_message(self, message: MessageResponse) -> str:
        """Format a BBS message for transmission to a node."""
        utc_timestamp = dateparse(message.timestamp)
        timestamp = format_timestamp(self.config, utc_timestamp)
        to_str = ""
        if message.recipient:
            to_str = f" To: {message.recipient}"
        header = f"[{message.id}] From: {message.display_name} ({message.sender}){to_str} - {timestamp}"
        content = "[Message from blocked sender]" if message.blocked else message.content
        return f"{header}\n{content}"

    def _chunk_message(self, message: Union[str, List], max_packet_length: int) -> List[str]:
        """Split the message into appropriately sized chunks. Returns a list of strings."""
        if message:
            if isinstance(message, list):
                log.error(f"Don't know how to split '{message}'")
                return ["Oops, check the log"]
            words = message.split(" ")
        else:
            return [""]

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

    async def _send_packet(self, username: str, node_id: str, chunk: str) -> bool:
        """Send a single packet to a node. This assumes that the packet
        is a safe size to send. Blocks until the ack has been
        received."""
        log.debug(
            f'Sending packet to {username} at {node_id}: {len(chunk)} bytes, content: "{chunk[:50]}..."')

        # Use the pre-configured send method
        try:
            result = await self.send_msg(node_id, chunk)
        except KeyError as e:
            log.error(f"Unexpected error sending packet: {e}")
            return False

        if result and result.type == EventType.ERROR:
            log.error(
                f"Error sending '{chunk[:50]}...' to {username} at {node_id}! {result.payload}")
            return False
        elif not result:
            log.error(
                f"Failed to send '{chunk[:50]}...' to {username} at {node_id}")
            return False

        # Wait for ACK with the configured timeout
        exp_ack = result.payload["expected_ack"].hex()
        # Increased from 5 to 8 seconds
        ack_timeout = self.mc_config.get("ack_timeout", 8)
        log.debug(f"Waiting for ACK {exp_ack} with timeout {ack_timeout}s")

        ack = await self.get_ack(exp_ack, ack_timeout)

        if ack:
            log.debug(f"✅ ACK received for packet to {node_id}")
            return True

        # Log ACK timeout for debugging (this is normal in mesh communication)
        log.debug(
            f"❌ ACK timeout ({ack_timeout}s) for packet '{chunk[:30]}...' to {username} at {node_id}")
        return False

    async def get_ack(self, code: str, timeout: int = 10) -> bool:
        """Await this function to see if a named ack has been received.
        Returns True or False."""
        i = 0
        while True:
            if i > timeout:
                return False
            if code in self._acks:
                # Check if ACK is not too old (matching original logic)
                now = datetime.now(UTC)
                if (now - self._acks[code]).seconds <= 20:
                    del self._acks[code]
                    return True
                else:
                    # ACK is too old, remove it
                    del self._acks[code]
            await asyncio.sleep(1)
            i += 1

    async def handle_ack(self, event):
        """Handle incoming ACKs from MeshCore events."""
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
            log.warning(f'Received an ACK without a code: {event.payload}')

    async def send_to_node(self, node_id: str, username: str, message: Union[str, ToUser, List]) -> bool:
        """Send a message to a mesh node via MeshCore. Returns False if
        the message couldn't be sent."""
        # TODO: probably need to handle ToUser packets more intelligently than this
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
