import asyncio
import inspect
import logging
import threading
import time

log = logging.getLogger(__name__)

class LoggingLock:
    def __init__(self, name="UnnamedLock"):
        self._lock = threading.Lock()
        self.name = name

    def _caller_info(self):
        stack = inspect.stack()
        if len(stack) > 3:
            frame = stack[3]
        else:
            frame = stack[-1]
        return f"{frame.function}() in {frame.filename}:{frame.lineno}"

    def acquire(self, blocking=True, timeout=-1):
        log.debug(f"🔒 Attempting to acquire lock: {self.name} from {self._caller_info()}")
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            log.debug(f"✅ Lock acquired: {self.name} from {self._caller_info()}")
        else:
            log.debug(f"⏳ Lock acquisition failed: {self.name} from {self._caller_info()}")
        return acquired

    def release(self):
        log.debug(f"🔓 Releasing lock: {self.name} from {self._caller_info()}")
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def locked(self):
        return self._lock.locked()

class AsyncLoggingLock:
    def __init__(self, name="UnnamedAsyncLock"):
        self._lock = asyncio.Lock()
        self.name = name

    def _caller_info(self):
        stack = inspect.stack()
        if len(stack) > 3:
            frame = stack[3]
        else:
            frame = stack[-1]
        return f"{frame.function}() in {frame.filename}:{frame.lineno}"

    async def acquire(self, timeout=None):
        log.debug(f"🔒 [async] Attempting to acquire lock: {self.name} from {self._caller_info()}")
        try:
            if timeout is not None:
                await asyncio.wait_for(self._lock.acquire(), timeout)
            else:
                await self._lock.acquire()
            log.debug(f"✅ [async] Lock acquired: {self.name} from {self._caller_info()}")
            return True
        except asyncio.TimeoutError:
            log.debug(f"⏳ [async] Lock acquisition timed out: {self.name} from {self._caller_info()}")
            return False

    def release(self):
        log.debug(f"🔓 [async] Releasing lock: {self.name} from {self._caller_info()}")
        self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def locked(self):
        return self._lock.locked()
