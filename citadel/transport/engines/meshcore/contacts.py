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

Expiration and capacity:

- Expiration is explicit capacity management:
    - We choose an expiration_candidate contact to remove.
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
    - If node is full when adding a new contact, we expire one contact first.

Caching and performance:

- Node I/O is expensive; DB access is cheap (SQLite in-memory).
- We maintain a small in-memory cache: node_id → (public_key, last_seen, name)
- We DO NOT load the entire DB into memory.
- Cache is always kept in sync with DB writes.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

from meshcore import EventType  # adjust import as needed

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
        if rows:
            return int(rows[0][0])
        return 0

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

    async def _get_device_contact(self, key_prefix: str) -> Optional[Dict[str, Any]]:
        try:
            info = self.meshcore.get_contact_by_key_prefix(key_prefix)
        except Exception:
            log.exception("MeshCore get_device_contact failed for %s", key_prefix)
            return None
        if not isinstance(info, dict):
            log.error("Unexpected contact info type for %s: %r", key_prefix, type(info))
            return None
        return info

    async def _add_contact_to_device(self, raw_advert_data: str) -> bool:
        event = await self.meshcore.commands.add_contact(raw_advert_data)
        if event.type == EventType.ERROR:
            log.error("MeshCore add_contact failed: %s", event.payload)
            return False
        log.debug("Added contact to device: {raw_advert_data}")
        return True

    async def _remove_contact_from_device(self, public_key: str) -> bool:
        event = await self.meshcore.commands.remove_contact(public_key)
        if event.type == EventType.ERROR:
            log.error("MeshCore remove_contact failed for %s: %s", public_key, event.payload)
            return False
        log.debug("Removed contact from device: {public_key[:16]}")
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

        capacity = self.effective_capacity
        contacts_loaded = 0

        for node_id in node_ids:
            if contacts_loaded >= capacity:
                log.info("Loaded {contacts_loaded} contacts into node")
                break
            row = await self._get_contact_row(node_id)
            if not row:
                log.warning("DB-authoritative sync: missing row for %s", node_id)
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
                log.warning("DB-authoritative sync: %s missing raw_advert_data", node_id)
                continue

            success = await self._add_contact_to_device(raw_advert_data)
            if success:
                contacts_loaded += 1
            else:
                log.error(
                    "DB-authoritative sync: failed to add %s to node; DB preserved",
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
            info = await self._get_device_contact(key_prefix)
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
                    latitude=info.get("adv_lat", 0.0),
                    longitude=info.get("adv_lon", 0.0),
                    first_seen=now,
                    last_seen=now,
                    raw_advert_data="",
                )

        # Delete DB rows not present on device
        rows = await self.db.execute("SELECT node_id FROM mc_chat_contacts")
        rows = rows or []
        for (node_id,) in rows:
            if node_id not in device_node_ids:
                log.info(
                    "Node-authoritative sync: deleting DB contact %s (not on device)",
                    node_id,
                )
                await self._delete_contact_row(node_id)

        # Rebuild cache
        await self._load_cache_from_db()

    # ------------------------------------------------------------------
    # Ingest path
    # ------------------------------------------------------------------

    async def ingest_contact(
        self,
        node_id: str,
        public_key: str,
        name: Optional[str],
        node_type: int,
        latitude: Optional[float],
        longitude: Optional[float],
        raw_advert_data: str,
    ) -> None:
        now = datetime.now(UTC)

        existing = await self._get_contact_row(node_id)
        if existing:
            first_seen = existing[6]
        else:
            first_seen = now

        await self._upsert_contact_row(
            node_id=node_id,
            public_key=public_key,
            name=name,
            node_type=node_type,
            latitude=latitude,
            longitude=longitude,
            first_seen=first_seen,
            last_seen=now,
            raw_advert_data=raw_advert_data,
        )

    # ------------------------------------------------------------------
    # Explicit add / delete
    # ------------------------------------------------------------------

    async def add_node(
        self,
        node_id: str,
        public_key: str,
        name: Optional[str],
        node_type: int,
        latitude: Optional[float],
        longitude: Optional[float],
        raw_advert_data: str,
    ) -> bool:
        """Add a node to the database and the node's contact memory.
        Returns True on success, or False if anything went wrong."""
        now = datetime.now(UTC)

        existing = await self._get_contact_row(node_id)
        if existing:
            first_seen = existing[6]
        else:
            first_seen = now

        await self._upsert_contact_row(
            node_id=node_id,
            public_key=public_key,
            name=name,
            node_type=node_type,
            latitude=latitude,
            longitude=longitude,
            first_seen=first_seen,
            last_seen=now,
            raw_advert_data=raw_advert_data,
        )

        db_count = await self._count_contacts_in_db()
        capacity = self.effective_capacity

        # TODO: this feels wrong: rather than blindly removing an old
        # contact from the node, we should be intelligently filling the
        # node to capacity, then stopping the load process, based on
        # the most recent {capacity} number of contacts.
        if db_count > capacity:
            await self._expire_one_contact()

        success = await self._add_contact_to_device(raw_advert_data)
        if not success:
            log.error("add_node: failed to add %s to node; DB preserved", node_id)
            return False

        return True

    async def delete_node(self, node_id: str) -> bool:
        """Remove the specified node from both the node and the
        database."""
        row = await self._get_contact_row(node_id)
        public_key = row[1] if row else None

        if not public_key:
            info = await self._get_device_contact(node_id)
            if info and "public_key" in info:
                public_key = info["public_key"]

        if public_key:
            success = await self._remove_contact_from_device(public_key)
            if not success:
                log.warning(
                    "delete_node: unable to remove contact for %s from device",
                    node_id,
                )
        else:
            log.warning("delete_node: no public_key found for %s; cannot remove from device", node_id)

        await self._delete_contact_row(node_id)
        return True

    # ------------------------------------------------------------------
    # Expiration logic
    # ------------------------------------------------------------------

    async def _expire_one_contact(self) -> Optional[str]:
        """
        Choose one contact in DB as an expiration_candidate and remove it
        from both node and DB.

        Strategy:
        - Use DB last_seen ascending to pick the oldest contact.
        - Use its public_key to remove from device.
        - If device removal fails, log and DO NOT delete from DB.
        """
        node_ids = await self._iter_db_contacts_sorted_by_last_seen_asc()
        if not node_ids:
            return None

        expiration_candidate_id = node_ids[0]
        row = await self._get_contact_row(expiration_candidate_id)
        if not row:
            log.warning(
                "Expiration: candidate %s vanished from DB; skipping",
                expiration_candidate_id,
            )
            return None

        (
            _node_id,
            public_key,
            _name,
            _ntype,
            _lat,
            _lon,
            _first_seen,
            _last_seen,
            _raw,
        ) = row

        # Remove from device first.
        success = await self._remove_contact_from_device(public_key)
        if not success:
            # Node is misbehaving; do NOT delete DB row.
            log.error(
                "Expiration: failed to remove contact %s from device; DB preserved",
                expiration_candidate_id,
            )
            return None

        # Now safe to delete from DB.
        await self._delete_contact_row(expiration_candidate_id)
        log.info("Expiration: removed contact %s from both node and DB",
                 expiration_candidate_id)

        return expiration_candidate_id

