"""
Utility classes for MeshCore transport engine.
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, UTC
from meshcore import EventType

log = logging.getLogger(__name__)


class AdvertScheduler:
    """Schedule an advert in a cancelable way. Modify the
    'advert_interval' setting in config.yaml with the number of hours
    between adverts. Defaults to 6 if no setting found."""

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
                        from citadel.transport.manager import TransportError
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
    """A simple class to provide message de-duplication services"""

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
        """Call this frequently to avoid the message hash table growing
        too large"""
        now = time.time()
        async with self._lock:
            for msg_hash, timestamp in self.seen.items():
                if now - self.seen[msg_hash] > self.ttl:
                    del self.seen[msg_hash]