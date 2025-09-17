import sqlite3
import threading
import logging
from collections import deque
from typing import Optional, Callable

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
        self._initialized = True

        self.db_path = config.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path)
        self.lock = threading.Lock()
        self.write_queue = deque()
        self.running = True

        self._start_write_worker()

    def _start_write_worker(self):
        thread = threading.Thread(target=self._write_worker,
daemon=True)
        thread.start()

    def _write_worker(self):
        while self.running:
            if self.write_queue:
                query, params, callback = self.write_queue.popleft()
                self._process_write(query, params, callback)

    def execute(self, query: str, params: tuple = (), callback:
Optional[Callable] = None):
        if self._is_write_query(query):
            self.write_queue.append((query, params, callback))
        else:
            while self.write_queue:
                pass  # Wait for writes to flush
            return self._process_read(query, params)

    def _process_write(self, query: str, params: tuple, callback:
Optional[Callable]):
        try:
            with self.lock:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                self.conn.commit()
                if callback:
                    callback(cursor)
        except sqlite3.OperationalError as e:
            logger.error(f"SQLite operational error during write:
{e}")
            raise RuntimeError("Database write failed. Please try
again.")
        except sqlite3.DatabaseError as e:
            logger.error(f"SQLite database error: {e}")
            raise RuntimeError("Database error occurred.")
        except Exception as e:
            logger.exception(f"Unexpected error during write: {e}")
            raise RuntimeError("Unexpected error during database
write.")

    def _process_read(self, query: str, params: tuple):
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.error(f"SQLite operational error during read:
{e}")
            raise RuntimeError("Database read failed. Please try
again.")
        except sqlite3.DatabaseError as e:
            logger.error(f"SQLite database error: {e}")
            raise RuntimeError("Database error occurred.")
        except Exception as e:
            logger.exception(f"Unexpected error during read: {e}")
            raise RuntimeError("Unexpected error during database
read.")

    def _is_write_query(self, query: str) -> bool:
        write_keywords = ("INSERT", "UPDATE", "DELETE", "REPLACE",
"CREATE", "DROP", "ALTER")
        return query.strip().upper().startswith(write_keywords)

    def shutdown(self):
        self.running = False
        self.conn.close()
        logger.info("DatabaseManager shut down cleanly.")

