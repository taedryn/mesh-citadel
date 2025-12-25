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
    On sync, we trim the DB to match the contacts currently on the node.
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
- We maintain a small in-memory cache: node_id → {name, public_key, last_seen}
- We DO NOT load the entire DB into memory.
- Most queries are performed via direct DB calls, not via a large cache.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from meshcore import EventType  # adjust import as needed

log = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass
class CachedContact:
    name: Optional[str]
    public_key: str
    last_seen: datetime


class ContactManager:
    def __init__(self, meshcore, db, config) -> None:
        """
        meshcore: MeshCore instance.
        db: async DB wrapper. execute(sql, params?) -> rows or None.
        config: existing config object, expected to expose:
            - config.max_device_contacts
            - config.contact_limit_buffer
        """
        self.db = db
        self.meshcore = meshcore
        self.config = config.transport.get(
            "meshcore", {}).get("contact_manager", {})

        # Minimal cache: node_id -> CachedContact
        self._cache: Dict[str, CachedContact] = {}

    # ------------------------------------------------------------------
    # Capacity helper
    # ------------------------------------------------------------------

    @property
    def effective_capacity(self) -> int:
        """
        Effective contact capacity for the node, leaving a buffer.
        """
        max_contacts = self.config.get("max_device_contacts", 100)
        buffer = self.config.get("contact_limit_buffer", 10)
        return max_contacts - buffer

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _count_contacts_in_db(self) -> int:
        rows = await self.db.execute("SELECT COUNT(*) FROM mc_chat_contacts")
        if not rows or not isinstance(rows, list):
            return 0
        return int(rows[0][0])

    async def _load_cache_for_node_ids(self, node_ids: List[str]) -> None:
        """
        Ensure cache entries exist for the given node_ids, loading only what we
        need from the DB. This keeps the cache small.
        """
        missing = [nid for nid in node_ids if nid not in self._cache]
        if not missing:
            return

        placeholders = ",".join("?" for _ in missing)
        sql = f"""
            SELECT node_id, name, public_key, last_seen
            FROM mc_chat_contacts
            WHERE node_id IN ({placeholders})
        """
        rows = await self.db.execute(sql, tuple(missing))
        rows = rows or []
        for row in rows:
            node_id, name, public_key, last_seen = row
            if last_seen is None:
                last_seen = datetime.min.replace(tzinfo=UTC)
            self._cache[node_id] = CachedContact(
                name=name,
                public_key=public_key,
                last_seen=last_seen,
            )

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
        # Update cache minimally
        self._cache[node_id] = CachedContact(
            name=name,
            public_key=public_key,
            last_seen=last_seen,
        )

    async def _delete_contact_row(self, node_id: str) -> None:
        await self.db.execute(
            "DELETE FROM mc_chat_contacts WHERE node_id = ?",
            (node_id,),
        )
        self._cache.pop(node_id, None)

    async def _iter_db_contacts_sorted_by_last_seen_desc(self) -> List[str]:
        """
        Return node_ids of contacts in DB, sorted by last_seen descending.
        We only return node_ids to keep memory low.
        """
        rows = await self.db.execute(
            "SELECT node_id FROM mc_chat_contacts ORDER BY last_seen DESC"
        )
        rows = rows or []
        return [row[0] for row in rows]

    async def _iter_db_contacts_sorted_by_last_seen_asc(self) -> List[str]:
        """
        Return node_ids of contacts in DB, sorted by last_seen ascending.
        Used for eviction selection.
        """
        rows = await self.db.execute(
            "SELECT node_id FROM mc_chat_contacts ORDER BY last_seen ASC"
        )
        rows = rows or []
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # MeshCore helpers
    # ------------------------------------------------------------------

    async def _get_device_contact_keys(self) -> List[str]:
        """
        Get a list of contact keys from MeshCore via get_contacts().
        Each element is a key prefix (node_id-like string) as per your example.
        """
        event = await self.meshcore.commands.get_contacts()
        if event.type == EventType.ERROR:
            log.error("MeshCore get_contacts failed: %s", event.payload)
            return []

        payload = event.payload or []
        if not isinstance(payload, list):
            log.error("Unexpected get_contacts payload type: %r", type(payload))
            return []

        # payload is a list of contact key prefixes (strings)
        return payload

    async def _get_device_contact_info(self, key_prefix: str) -> Optional[Dict[str, Any]]:
        """
        Look up full contact info for a given key prefix, using
        meshcore.get_contact_by_key_prefix().
        """
        try:
            info = self.meshcore.get_contact_by_key_prefix(key_prefix)
        except Exception:  # if it can throw
            log.exception("MeshCore get_contact_by_key_prefix failed for %s", key_prefix)
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
        return True

    async def _remove_contact_from_device(self, public_key: str) -> bool:
        event = await self.meshcore.commands.remove_contact(public_key)
        if event.type == EventType.ERROR:
            log.error("MeshCore remove_contact failed for %s: %s", public_key, event.payload)
            return False
        return True

    # ------------------------------------------------------------------
    # Initialization / sync
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Reconcile DB and node according to conditional authority:

        - If DB count <= capacity: DB is authoritative.
          We attempt to push all DB contacts into the node.

        - If DB count > capacity: node is authoritative.
          We trim DB to match the node's contacts.
        """
        db_count = await self._count_contacts_in_db()
        capacity = self.effective_capacity

        contact_keys = await self._get_device_contact_keys()
        log.info(
            "ContactManager init: DB=%d, node=%d, capacity=%d",
            db_count,
            len(contact_keys),
            capacity,
        )

        if db_count <= capacity:
            await self._sync_db_as_authority()
        else:
            await self._sync_node_as_authority(contact_keys)

    async def sync_db_to_node(self) -> None:
        """
        External API: perform the same reconciliation as initialize().
        """
        await self.initialize()

    async def _sync_db_as_authority(self) -> None:
        """
        DB is authoritative (DB count <= capacity).

        - Fetch all DB contacts (node_ids) sorted by last_seen desc.
        - For each, retrieve raw_advert_data and call add_contact().
        - We do not check if the contact is already on the node.
        - On hardware error, we log but do NOT modify the DB.
        """
        node_ids = await self._iter_db_contacts_sorted_by_last_seen_desc()
        for node_id in node_ids:
            row = await self._get_contact_row(node_id)
            if not row:
                # Row disappeared between calls; log and continue.
                log.warning(
                    "DB-authoritative sync: contact %s missing in DB while iterating",
                    node_id,
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
                    "DB-authoritative sync: contact %s has no raw_advert_data; skipping",
                    node_id,
                )
                continue

            success = await self._add_contact_to_device(raw_advert_data)
            if not success:
                # Node may be in an error state; DO NOT delete DB rows.
                log.error(
                    "DB-authoritative sync: failed to add contact %s to node; DB preserved",
                    node_id,
                )

    async def _sync_node_as_authority(self, contact_keys: List[str]) -> None:
        """
        Node is authoritative (DB count > capacity).

        - contact_keys is the list returned by get_contacts().payload.
        - For each key, get full info to find node_id/public_key.
        - Any DB rows not corresponding to node contacts are deleted.
        - Any node contacts not in DB are logged and minimally inserted.
        """
        # Map node_id -> public_key for contacts on device.
        device_node_ids: Dict[str, str] = {}

        for key_prefix in contact_keys:
            info = await self._get_device_contact_info(key_prefix)
            if not info:
                continue

            node_id = key_prefix[:16]  # matches your example
            public_key = info.get("public_key")
            if not public_key:
                log.warning(
                    "Node-authoritative sync: contact %s missing public_key in device info",
                    key_prefix,
                )
                continue

            device_node_ids[node_id] = public_key

            # If DB doesn't know this contact, log and insert minimal row.
            row = await self._get_contact_row(node_id)
            if not row:
                log.warning(
                    "Node-authoritative sync: device contact %s not in DB; inserting minimal record",
                    node_id,
                )
                now = datetime.now(UTC)
                await self._upsert_contact_row(
                    node_id=node_id,
                    public_key=public_key,
                    name=info.get("adv_name"),
                    node_type=info.get("type", 1),
                    latitude=info.get("adv_lat"),
                    longitude=info.get("adv_lon"),
                    first_seen=now,
                    last_seen=now,
                    raw_advert_data="",
                )

        # Now delete DB rows whose node_id is not present on device.
        rows = await self.db.execute("SELECT node_id FROM mc_chat_contacts")
        rows = rows or []
        for (node_id,) in rows:
            if node_id not in device_node_ids:
                log.info(
                    "Node-authoritative sync: deleting DB contact %s (not on device)",
                    node_id,
                )
                await self._delete_contact_row(node_id)

    # ------------------------------------------------------------------
    # Ingest path (from adverts)
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
        """
        Called when a contact advert is received.

        - Insert/update row in mc_chat_contacts.
        - Update last_seen.
        - Capacity management is handled by eviction when we try to add
          contacts to the node and it is full.
        """
        now = datetime.now(UTC)

        existing = await self._get_contact_row(node_id)
        if existing:
            (
                _node_id,
                _pub,
                _name,
                _ntype,
                _lat,
                _lon,
                first_seen,
                _last_seen,
                _raw,
            ) = existing
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

        # We do NOT automatically push to the node here.
        # DB-authoritative sync will take care of populating the node,
        # and eviction is handled there or in add_node().

    # ------------------------------------------------------------------
    # Explicit add / delete APIs
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
        """
        Public API: ensure a contact exists in DB and, if possible, on the node.

        - Inserts/updates DB.
        - If we are at/over capacity on the node, we choose an eviction_candidate
          and remove it (from node and DB) before adding this contact.
        - If add_contact fails due to hardware, we keep the DB entry and
          log an error.
        """
        now = datetime.now(UTC)

        existing = await self._get_contact_row(node_id)
        if existing:
            (
                _node_id,
                _pub,
                _name,
                _ntype,
                _lat,
                _lon,
                first_seen,
                _last_seen,
                _raw,
            ) = existing
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

        # Check capacity: if DB size is already > capacity, this implies
        # node-authoritative mode in a global sense, but here we just enforce
        # that before adding we may need to evict one.
        # To know if node is "full enough to require eviction", we should
        # look at the count in DB vs capacity, or explicitly evict when DB
        # exceeds capacity.
        db_count = await self._count_contacts_in_db()
        capacity = self.effective_capacity
        if db_count > capacity:
            await self._evict_one_contact()

        # Now attempt to add to device (idempotent from our perspective).
        success = await self._add_contact_to_device(raw_advert_data)
        if not success:
            # Node may be in error state; DB is preserved.
            log.error(
                "add_node: failed to add contact %s to node; DB preserved",
                node_id,
            )
            return False

        return True

    async def delete_node(self, node_id: str) -> bool:
        """
        Public API: remove a contact from both node and DB.

        - If DB has a row, use its public_key to remove from node.
        - If DB does not have a row, we attempt to infer from device data if possible.
        - On node removal failure, we log but still delete DB row only if this is
          an intentional delete (not a hardware-driven eviction).
        """
        row = await self._get_contact_row(node_id)
        public_key: Optional[str] = None
        if row:
            public_key = row[1]  # public_key

        # If we don't know public_key from DB, we can try to find it on device.
        if not public_key:
            contact_keys = await self._get_device_contact_keys()
            for key_prefix in contact_keys:
                if key_prefix.startswith(node_id[:16]):
                    info = await self._get_device_contact_info(key_prefix)
                    if info and "public_key" in info:
                        public_key = info["public_key"]
                        break

        if public_key:
            success = await self._remove_contact_from_device(public_key)
            if not success:
                log.warning(
                    "delete_node: device removal failed for %s; DB will still be deleted",
                    node_id,
                )
        else:
            log.warning(
                "delete_node: no public_key found for %s; cannot remove from device",
                node_id,
            )

        await self._delete_contact_row(node_id)
        return True

    # ------------------------------------------------------------------
    # Eviction logic
    # ------------------------------------------------------------------

    async def _evict_one_contact(self) -> Optional[str]:
        """
        Choose one contact in DB as an eviction_candidate and remove it
        from both node and DB.

        Strategy:
        - Use DB last_seen ascending to pick the oldest contact.
        - Use its public_key to remove from device.
        - If device removal fails, log and DO NOT delete from DB.
        """
        node_ids = await self._iter_db_contacts_sorted_by_last_seen_asc()
        if not node_ids:
            return None

        eviction_candidate_id = node_ids[0]
        row = await self._get_contact_row(eviction_candidate_id)
        if not row:
            log.warning(
                "Eviction: candidate %s vanished from DB; skipping",
                eviction_candidate_id,
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
                "Eviction: failed to remove contact %s from device; DB preserved",
                eviction_candidate_id,
            )
            return None

        # Now safe to delete from DB.
        await self._delete_contact_row(eviction_candidate_id)
        log.info("Eviction: removed contact %s from both node and DB", eviction_candidate_id)

        return eviction_candidate_id

