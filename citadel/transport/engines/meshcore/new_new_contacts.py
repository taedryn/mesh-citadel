"""
ContactManager design overview
------------------------------

We have two places where contacts live:

1. Node (MeshCore device) contact memory
   - Small, fixed-size, fallible.
   - If a contact is NOT on the node, the node cannot communicate with it.
   - This is the *operational* source of truth.

2. Database (mc_chat_contacts)
   - Persistent, reliable, in-memory SQLite.
   - Stores contact metadata and raw advert data.
   - Used to repopulate the node after faults or wipe.

Authority is conditional:

- If DB contact count <= node capacity:
    DB is authoritative.
    On sync, we push all DB contacts to the node (e.g. after node fault).
    We do NOT delete DB rows in this mode.

- If DB contact count > node capacity:
    Node is authoritative.
    On sync, we trim the DB to match the node's contacts.
    DB rows whose node_id is not present on the node are deleted.
    If the node has contacts that DB doesn't know about, we log a warning
    and insert minimal rows for them.

Eviction and capacity:

- Eviction is explicit capacity management:
    - We choose an eviction_candidate contact to remove.
    - We remove it from the node (by public_key).
    - If the removal succeeds, we delete the corresponding DB row.
    - If removal fails (hardware error), we DO NOT delete the DB row.

- We NEVER delete DB rows because of node add/remove *errors*.
  Database loss must not be caused by hardware faults.

Ingest path (from adverts):

- Node advertises a contact.
- BBS receives raw advert data, parses node_id/public_key/name/etc.
- BBS inserts/updates a row in mc_chat_contacts.
- BBS attempts to ensure the contact is present on the node:
    - If DB count <= capacity, we will eventually sync DB → node.
    - If node is full when adding a new contact, we evict one contact first.

Caching and performance:

- Node I/O is expensive; DB access is cheap (SQLite in-memory).
- We maintain a small in-memory cache: node_id → (public_key, last_seen, name)
- We DO NOT load the entire DB into memory.
- Cache is always kept in sync with DB writes.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

from .meshcore_events import EventType  # adjust import as needed

log = logging.getLogger(__name__)
UTC = timezone.utc


class ContactManager:
    def __init__(self, meshcore, db, config) -> None:
        self.db = db
        self.meshcore = meshcore
        self.config = config.transport.get(
            "meshcore", {}).get("contact_manager", {})

        # Minimal cache: node_id → (public_key, last_seen, name)
        self._cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Capacity helper
    # ------------------------------------------------------------------

    @property
    def effective_capacity(self) -> int:
        max_contacts = self.config.get("max_device_contacts", 100)
        buffer = self.config.get("contact_limit_buffer", 0)
        return max_contacts - buffer

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _count_contacts_in_db(self) -> int:
        rows = await self.db.execute("SELECT COUNT(*) FROM mc_chat_contacts")
        rows = rows or []
        return int(rows[0][0]) if rows else 0

    async def _load_cache_from_db(self) -> None:
        """
        Load the entire DB into the minimal cache.
        This is only done at initialization or sync.
        """
        rows = await self.db.execute(
            """
            SELECT node_id, public_key, last_seen, name
            FROM mc_chat_contacts
            """
        )
        rows = rows or []
        self._cache.clear()
        for node_id, public_key, last_seen, name in rows:
            if last_seen is None:
                last_seen = datetime.min.replace(tzinfo=UTC)
            self._cache[node_id] = (public_key, last_seen, name)

    async def _get_contact_row(self, node_id: str) -> Optional[tuple]:
        rows = await self.db.execute(
            """
            SELECT node_id,
                   public_key,
                   name,
                   node_type,
                   latitude,
                   longitude,
                   first_seen,
                   last_seen,
                   raw_advert_data
            FROM mc_chat_contacts
            WHERE node_id = ?
            """,
            (node_id,),
        )
        rows = rows or []
        return rows[0] if rows else None

    async def _upsert_contact_row(
        self,
        node_id: str,
        public_key: str,
        name: Optional[str],
        node_type: int,
        latitude: Optional[float],
        longitude: Optional[float],
        first_seen: datetime,
        last_seen: datetime,
        raw_advert_data: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO mc_chat_contacts (
                node_id,
                public_key,
                name,
                node_type,
                latitude,
                longitude,
                first_seen,
                last_seen,
                raw_advert_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                public_key = excluded.public_key,
                name = excluded.name,
                node_type = excluded.node_type,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                last_seen = excluded.last_seen,
                raw_advert_data = excluded.raw_advert_data
            """,
            (
                node_id,
                public_key,
                name,
                node_type,
                latitude,
                longitude,
                first_seen,
                last_seen,
                raw_advert_data,
            ),
        )

        # Update cache
        self._cache[node_id] = (public_key, last_seen, name)

    async def _delete_contact_row(self, node_id: str) -> None:
        await self.db.execute(
            "DELETE FROM mc_chat_contacts WHERE node_id = ?",
            (node_id,),
        )
        self._cache.pop(node_id, None)

    async def _iter_db_contacts_sorted_by_last_seen_desc(self) -> List[str]:
        rows = await self.db.execute(
            "SELECT node_id FROM mc_chat_contacts ORDER BY last_seen DESC"
        )
        rows = rows or []
        return [row[0] for row in rows]

    async def _iter_db_contacts_sorted_by_last_seen_asc(self) -> List[str]:
        rows = await self.db.execute(
            "SELECT node_id FROM mc_chat_contacts ORDER BY last_seen ASC"
        )
        rows = rows or []
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # MeshCore helpers
    # ------------------------------------------------------------------

    async def _get_device_contact_keys(self) -> List[str]:
        event = await self.meshcore.commands.get_contacts()
        if event.type == EventType.ERROR:
            log.error("MeshCore get_contacts failed: %s", event.payload)
            return []
        payload = event.payload or []
        if not isinstance(payload, list):
            log.error("Unexpected get_contacts payload type: %r", type(payload))
            return []
        return payload

    async def _get_device_contact_info(self, key_prefix: str) -> Optional[Dict[str, Any]]:
        try:
            result = self.meshcore.get_contact_by_key_prefix(key_prefix)
        except Exception:
            log.exception("MeshCore get_contact_by_key_prefix failed for %s", key_prefix)
            return None
        if result.type == EventType.ERROR:
            log.error(f"Unable to load '{key_prefix}' from node: {result.payload}")
            return None
        return result.payload

    async def _add_contact_to_device(self, raw_advert_data: str) -> bool:
        result = await self.meshcore.commands.add_contact(raw_advert_data)
        if result.type == EventType.ERROR:
            log.error("MeshCore add_contact failed: %s", result.payload)
            return False
        return True

    async def _remove_contact_from_device(self, public_key: str) -> bool:
        result = await self.meshcore.commands.remove_contact(public_key)
        if result.type == EventType.ERROR:
            log.error("MeshCore remove_contact failed for %s: %s", public_key, result.payload)
            return False
        return True

    # ------------------------------------------------------------------
    # Initialization / sync
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Reconcile DB and node according to conditional authority.
        """
        if self.meshcore:
            result = await self.meshcore.commands.set_manual_add_contacts(True)
            if result.type == EventType.ERROR:
                log.warning(
                    f"Unable to disable auto-add of contacts: {result.payload}")
            else:
                log.info("Disabled meshcore auto-add of contacts")

        await self._load_cache_from_db()

        db_count = await self._count_contacts_in_db()
        capacity = self.effective_capacity
        device_keys = await self._get_device_contact_keys()

        log.info(
            "ContactManager started. Contact counts: DB=%d, node=%d, capacity=%d",
            db_count,
            len(device_keys),
            capacity,
        )

        if self.config.get("update_contacts", False):
            if db_count <= capacity:
                log.info("Synchronizing contacts from DB -> node")
                await self._sync_db_as_authority()
            else:
                log.info("Synchronizing contacts from node -> DB")
                await self._sync_node_as_authority(device_keys)
        else:
            log.info("Contact update configured off, skipping")

    async def _sync_db_as_authority(self) -> None:
        """
        DB is authoritative (DB count <= capacity).
        Push all DB contacts to the node.
        """
        node_ids = await self._iter_db_contacts_sorted_by_last_seen_desc()

        for node_id in node_ids:
            row = await self._get_contact_row(node_id)
            if not row:
                log.warning(
                    "DB-authoritative sync: missing row for %s",
                    node_id
                )
                continue

            (
                _node_id,
                public_key,
                name,
                node_type,
                latitude,
                longitude,
                first_seen,
                last_seen,
                raw_advert_data,
            ) = row

            if not raw_advert_data:
                log.warning(
                    "DB-authoritative sync: %s missing raw_advert_data",
                    node_id
                )
                continue

            success = await self._add_contact_to_device(raw_advert_data)
            if not success:
                log.error(
                    "DB-authoritative sync: failed to add %s to node, skipping",
                    node_id,
                )

    async def _sync_node_as_authority(self, device_keys: List[str]) -> None:
        """
        Node is authoritative (DB count > capacity).
        Trim DB to match node.
        """
        device_node_ids: Dict[str, str] = {}

        # Build device node_id → public_key map
        for key_prefix in device_keys:
            info = await self._get_device_contact_info(key_prefix)
            if not info:
                continue

            node_id = key_prefix[:16]
            public_key = info.get("public_key")
            if not public_key:
                log.warning("Node-authoritative sync: %s missing public_key", key_prefix)
                continue

            device_node_ids[node_id] = public_key

            # If DB doesn't know this contact, insert minimal row
            if node_id not in self._cache:
                log.warning(
                    "Node-authoritative sync: device contact %s not in DB; inserting minimal",
                    node_id,
                )
                now = datetime.now(UTC)
                await self._upsert_contact_row(
                    node_id=node_id,
                    public_key=public_key,
                    name=info.get("adv_name"),
                    node_type=info.get("type", 1),
                    latitude=info.get
