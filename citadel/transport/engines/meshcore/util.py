"""
Utility classes for MeshCore transport engine.

"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, UTC
from meshcore import EventType

from citadel.logging_lock import AsyncLoggingLock

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
        interval = self.config.transport.get(
            "meshcore", {}).get("advert_interval", 6)
        try:
            while not self._stop_event.is_set():
                if self.meshcore:
                    flood = self.config.transport.get(
                        'meshcore', {}).get('flood_advert', True)
                    log.info(f"Sending advert (flood={flood})")
                    result = await self.meshcore.commands.send_advert(flood=flood)
                    if result.type == EventType.ERROR:
                        from citadel.transport.manager import TransportError
                        raise TransportError(
                            f"Unable to send advert: {result.payload}")
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


class WatchdogFeeder:
    """Schedule the watchdog reset in a cancelable way."""

    def __init__(self, config, feeder_func):
        self.config = config
        self.feeder_func = feeder_func
        self._stop_event = asyncio.Event()
        if not feeder_func:
            raise RuntimeError("Feeder function must be callable function")

    async def start_feeder(self):
        timeout = self.config.transport.get(
            "meshcore", {}).get("watchdog_reset", 30)
        try:
            while not self._stop_event.is_set():
                self.feeder_func()
                try:
                    # Wait with cancellation support
                    await asyncio.wait_for(self._stop_event.wait(),
                                           timeout=timeout)
                except asyncio.TimeoutError:
                    pass  # Timeout means it's time to run again
        except asyncio.CancelledError:
            log.info("Watchdog feeder was cancelled")
        finally:
            log.info("Watchdog feeder shutdown complete")

    def stop(self):
        self._stop_event.set()


class MessageDeduplicator:
    """A simple class to provide message de-duplication services"""

    def __init__(self, ttl=30):
        self.seen = {}  # message_hash: timestamp
        self.ttl = ttl  # seconds
        self._lock = asyncio.Lock()

    async def is_duplicate(self, node_id: str, timestamp: int, message: str) -> bool:
        text = '::'.join([node_id, str(timestamp), message])
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
        while True:
            i = 0
            now = time.time()
            async with self._lock:
                for msg_hash in list(self.seen.keys()):
                    if now - self.seen[msg_hash] > self.ttl:
                        del self.seen[msg_hash]
                        i += 1
            log.debug(f"Dedupe ran and removed {i} messages from the pool")
            await asyncio.sleep(60)
