"""
MeshCore Node Authentication Manager

Handles password caching and authentication for MeshCore nodes.
Extracted from the main transport engine for better separation of concerns.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Optional

log = logging.getLogger(__name__)


class NodeAuth:
    """Manages authentication and password caching for MeshCore nodes."""

    def __init__(self, config, db):
        self.config = config
        self.db = db

    async def node_has_password_cache(self, node_id: str) -> bool:
        """Check if node has valid password cache. This function forces
        password expiration such that a user must input their password at
        least every 2 weeks."""
        days = self.config.auth.get("password_cache_duration", 14)
        query = "SELECT last_pw_use, username FROM mc_passwd_cache WHERE node_id = ?"
        try:
            result = await self.db.execute(query, (node_id,))
            if result:
                dt = datetime.strptime(result[0][0], "%Y-%m-%d %H:%M:%S")
                two_weeks_ago = datetime.now() - timedelta(days=days)
                if dt < two_weeks_ago:
                    log.debug(f"Password cache for {node_id} is expired")
                    return False # cache is expired
                return result[0][1] # username, cache is valid
            log.debug(f'No passwd cache DB result: "{result}"')
            return False # has no cache at all
        except Exception as e:
            log.exception(f"Uncaught exception checking for password cache for {node_id}: {e}")
            return False

    async def set_cache_username(self, username: str, node_id: str):
        """this must be called after update_password_cache to
        completely cache a node_id's cache entry"""
        query = "UPDATE mc_passwd_cache SET username = ? WHERE node_id = ?"
        await self.db.execute(query, (username, node_id))

    async def touch_password_cache(self, username: str, node_id: str):
        """update this session to have a fresh password cache time.  the
        cache is not valid until set_cache_username is also called."""
        query = """INSERT INTO mc_passwd_cache
            (node_id, last_pw_use) VALUES (?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                last_pw_use = excluded.last_pw_use
        """
        log.debug(f"Updating MeshCore password cache for {username}")

        now = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
        await self.db.execute(query, (node_id, now))

    async def remove_cache_node_id(self, node_id: str):
        """remove a node_id from the password cache.  to be used when the
        user proactively logs out, not when their session expires due
        to inactivity or connectivity errors."""
        query = "DELETE FROM mc_passwd_cache WHERE node_id = ?"
        await self.db.execute(query, (node_id,))
        log.info(f"Removed {node_id} from MC password cache")