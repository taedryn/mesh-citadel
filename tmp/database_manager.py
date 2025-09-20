import aiosqlite
import logging

log = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, config):
        self.db_path = config.database['db_path']
        self.conn = None
        log.info(f"DatabaseManager initialized for {self.db_path}")

    async def start(self):
        """Initialize the database connection"""
        self.conn = await aiosqlite.connect(self.db_path)
        log.info("Database connection established")

    async def close(self):
        """Clean shutdown"""
        if self.conn:
            await self.conn.close()
            log.info("Database connection closed")

    async def execute(self, query: str, params: tuple = ()):
        """Execute a database query"""
        if not self.conn:
            raise RuntimeError("Database not started. Call start() first.")

        try:
            cursor = await self.conn.cursor()
            await cursor.execute(query, params)

            if self._is_write_query(query):
                await self.conn.commit()
                return cursor.rowcount
            else:
                return await cursor.fetchall()
        except Exception as e:
            log.error(f"Database error executing '{query}': {e}")
            raise

    def _is_write_query(self, query: str) -> bool:
        """Check if query modifies data"""
        return query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))