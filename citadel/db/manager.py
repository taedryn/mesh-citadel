import aiosqlite
import asyncio
import logging
import sqlite3
import threading
from typing import Optional, Callable

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

        self.db_path = config.database['db_path']
        self.conn = None
        self.lock = threading.Lock()

        self._initialized = True
        log.info("DatabaseManager initialized with blocking mode")

    async def start(self):
        self.conn = await aiosqlite.connect(self.db_path)

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
        await self.conn.close()
        log.info("DatabaseManager shut down cleanly.")
