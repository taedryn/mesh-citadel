import aiosqlite
import asyncio
import logging
import sqlite3
import threading
from typing import Optional, Callable

from citadel.logging_lock import AsyncLoggingLock, LoggingLock

log = logging.getLogger(__name__)


class DatabaseManager:
    _instance = None

    def __new__(cls, config):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config):
        if self._initialized:
            return

        self.config = config
        self.db_path = config.database['db_path']
        self.conn = None
        #self.lock = LoggingLock('DatabaseManager')
        self.lock = threading.Lock()
        self._shutdown_event = asyncio.Event()

        self._initialized = True
        log.info("DatabaseManager initialized with blocking mode")

    async def start(self):
        disk_conn = await aiosqlite.connect(self.db_path)
        self.conn = await aiosqlite.connect(":memory:")
        await disk_conn.backup(self.conn)
        await disk_conn.close()
        self._persist_task = asyncio.create_task(self._persist_loop())
        seconds = self.config.bbs.get("database_save_interval", 300)
        log.info(f"Database loaded into memory; will save to disk every {seconds}s")

    async def _persist_loop(self):
        while not self._shutdown_event.is_set():
            seconds = self.config.bbs.get("database_save_interval", 300)
            try:
                await asyncio.sleep(seconds)
                await self.persist_to_disk()
            except Exception as e:
                log.error(f"Error during periodic DB persist: {e}")

    async def persist_to_disk(self):
        log.debug("Persisting database to disk")
        disk_conn = await aiosqlite.connect(self.db_path)
        await self.conn.backup(disk_conn)
        await disk_conn.close()


    @classmethod
    def reset(cls):
        cls._instance = None

    async def execute(self, query: str, params: tuple = (), callback: Optional[Callable] = None):
        if self._is_write_query(query):
            return await self._process_write(query, params, callback)
        else:
            return await self._process_read(query, params)

    async def _process_write(self, query: str, params: tuple, callback: Optional[Callable]):
        try:
            async with self.conn.execute(query, params) as cursor:
                await self.conn.commit()
                if callback:
                    callback(cursor)
                return cursor.rowcount
        except sqlite3.OperationalError as e:
            log.error(f"SQLite operational error during write: {e}")
            raise RuntimeError("Database write failed. Please try again.")
        except sqlite3.DatabaseError as e:
            log.error(f"SQLite database error: {e}")
            raise RuntimeError("Database error occurred.")
        except Exception as e:
            log.exception(f"Unexpected error during write: {e}")
            raise RuntimeError("Unexpected error during database write.")

    async def _process_read(self, query: str, params: tuple):
        try:
            async with self.conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return rows
        except sqlite3.OperationalError as e:
            log.error(f"SQLite operational error during read: {e}")
            raise RuntimeError("Database read failed. Please try again.")
        except sqlite3.DatabaseError as e:
            log.error(f"SQLite database error: {e}")
            raise RuntimeError("Database error occurred.")
        except Exception as e:
            log.exception(f"Unexpected error during read: {e}")
            raise RuntimeError("Unexpected error during database read.")

    def _is_write_query(self, query: str) -> bool:
        write_keywords = ("INSERT", "UPDATE", "DELETE",
                          "REPLACE", "CREATE", "DROP", "ALTER")
        return query.strip().upper().startswith(write_keywords)

    async def shutdown(self):
        log.info("Shutting down DatabaseManager")
        self._shutdown_event.set()
        if self._persist_task:
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                log.info("Database persisting task cancelled")
        await self.persist_to_disk()
        await self.conn.close()
        log.info("DatabaseManager shut down cleanly.")

