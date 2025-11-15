"""
Contact management for MeshCore transport engine.

Manages chat node contacts with automatic cleanup when approaching storage limits.
Memory-optimized for Raspberry Pi Zero.
"""

import asyncio
import json
import logging
from datetime import datetime, UTC
from meshcore import EventType

log = logging.getLogger(__name__)


class ContactManager:
    """Manages chat node contacts with automatic cleanup when approaching storage limits."""

    def __init__(self, meshcore, db, config):
        self.meshcore = meshcore
        self.db = db
        self.config = config.transport.get(
            "meshcore", {}).get("contact_manager", {})
        # Minimal cache: node_id -> name (all entries are chat nodes by definition)
        self._contacts_cache = {}

    async def start(self):
        """Initialize contact manager and load essential contact info."""
        await self._load_essential_contacts()

        # Disable meshcore auto-contact updates to give us full control
        if self.meshcore:
            result = await self.meshcore.commands.set_manual_add_contacts(True)
            if result.type == EventType.ERROR:
                log.warning(
                    f"Unable to disable auto-add of contacts: {result.payload}")
            else:
                log.info("Disabled meshcore auto-add of contacts")

        log.info(
            f"ContactManager started with {len(self._contacts_cache)} cached contacts")

    async def _load_essential_contacts(self):
        """Load only essential contact info into cache."""
        contacts = await self.db.execute(
            "SELECT node_id, name FROM mc_chat_contacts"
        )

        for row in contacts:
            node_id, name = row
            self._contacts_cache[node_id] = name or 'Unknown'

        log.debug(f"Loaded {len(self._contacts_cache)} contacts into cache")

    async def sync_db_to_node(self):
        """Load only essential contact info into cache."""
        log.info("Synchronizing contacts down to MC node")
        for node_id in self._contacts_cache.keys():
            log.debug(f"Syncing {node_id} down to node")
            await self.add_node(node_id, quiet=True)

        log.info(f"Synced {len(self._contacts_cache)} contacts into node")

    def _is_chat_node(self, advert_data: dict) -> bool:
        """Determine if this is a chat node (companion) we want to track."""
        node_type = advert_data.get('type', 0)
        return node_type == 1

    async def handle_advert(self, event):
        """Handle incoming advertisement - only store chat nodes."""
        try:
            advert_data = event.payload

            public_key = advert_data.get('public_key', '')
            if not public_key:
                log.warning("Advert missing public key")
                return

            node_id = public_key[:16]

            # Query meshcore device for full contact details
            if event.type == EventType.NEW_CONTACT:
                contact_details = advert_data
            else:
                contact_details = await self._get_contact_details(public_key)
            if not contact_details:
                log.debug(f"Could not retrieve contact details for {node_id}")
                return

            if not self._is_chat_node(contact_details):
                log.debug(f"Rejecting non-chat node: {contact_details}")
                return  # Not a chat node, ignore

            name = contact_details.get(
                'adv_name', contact_details.get('name', 'Unknown'))

            await self._update_contact_record(node_id, contact_details)

            self._contacts_cache[node_id] = name

            # Trigger cleanup if we're approaching limits
            await self._cleanup_if_needed()
            await self.add_node(node_id)

            log.info(f"Recorded advert: {name} ({node_id})")
        except Exception as e:
            log.exception(f"Unhandled exception in handle_advert: {e}")

    async def _get_contact_details(self, public_key: str):
        """Get full contact details from the meshcore device."""
        if not self.meshcore:
            return None

        # Try to get contact by key prefix
        node_id = public_key[:16]
        try:
            contact = self.meshcore.get_contact_by_key_prefix(node_id)
            if contact:
                log.debug(f"Found {node_id} in device: {contact}")
            else:
                log.debug(f"{node_id} contact details not found in device")
            return contact
        except AttributeError:
            pass

        # Fallback: get all contacts and search
        try:
            result = await self.meshcore.commands.get_contacts()
        except (OSError, AttributeError) as e:
            log.debug(f"Error getting contacts: {e}")
            return None

        if result.type == EventType.ERROR:
            log.warning(
                f"Unable to get all contacts from device: {result.payload}")
            return None

        contacts = result.payload

        for contact_key, contact_data in contacts.items():
            if contact_data.get('public_key', contact_key) == public_key:
                log.debug(
                    f"Found contact {node_id} by searching: {contact_data}")
                return contact_data

        log.debug("No method found to get {node_id} from device")
        return None

    async def _update_contact_record(self, node_id: str, contact_data: dict):
        """Update contact record in database."""
        public_key = contact_data.get('public_key', '')
        name = contact_data.get(
            'adv_name', contact_data.get('name', 'Unknown'))
        node_type = contact_data.get('type', 1)  # usually 1 for chat node
        latitude = contact_data.get('adv_lat', contact_data.get('lat'))
        longitude = contact_data.get('adv_lon', contact_data.get('lon'))
        now = datetime.now(UTC).isoformat()

        try:
            raw_data_json = json.dumps(contact_data)
        except (TypeError, ValueError) as e:
            log.warning(f"Failed to serialize contact data for {node_id}: {e}")
            raw_data_json = "{}"

        await self.db.execute("""
            INSERT INTO mc_chat_contacts
            (node_id, public_key, name, node_type, latitude, longitude,
                first_seen, last_seen, raw_advert_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                public_key = excluded.public_key,
                name = excluded.name,
                node_type = excluded.node_type,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                last_seen = excluded.last_seen,
                raw_advert_data = excluded.raw_advert_data
        """, (node_id, public_key, name, node_type, latitude, longitude, now, now, raw_data_json))

    async def add_node(self, node_id: str, quiet: bool=False) -> bool:
        """Add a chat node to the meshcore device, expiring oldest if at limit."""
        if node_id not in self._contacts_cache:
            log.warning(f"Cannot add unknown node: {node_id}")
            return False

        # Check if we're at the contact limit and need to make room
        current_contacts = await self._get_device_contact_count()
        max_contacts = self.config.get('max_device_contacts', 240)
        buffer_size = self.config.get('contact_limit_buffer', 10)

        if current_contacts >= (max_contacts - buffer_size):
            if not await self._expire_oldest_contact():
                name = self._contacts_cache[node_id]
                log.warning(
                    f"Cannot add {name}: at contact limit and failed to expire oldest")
                return False

        if not self.meshcore:
            log.error("MeshCore not available for adding contact")
            return False

        # Get full contact data from database for adding
        result = await self.db.execute(
            "SELECT raw_advert_data FROM mc_chat_contacts WHERE node_id = ?",
            (node_id,)
        )
        if not result:
            log.error(f"No stored data for node {node_id}, cannot add")
            return False

        try:
            contact_data = json.loads(result[0][0])
        except (json.JSONDecodeError, TypeError) as e:
            log.error(
                f"Failed to parse stored contact data for {node_id}: {e}")
            return False

        log.debug(f"Preparing to add {node_id} to device contacts")
        try:
            result = await self.meshcore.commands.add_contact(contact_data)
        except (OSError, AttributeError) as e:
            log.error(f"Error adding contact {node_id}: {e}")
            return False

        if result and result.type != EventType.ERROR:
            await self.db.execute(
                """UPDATE mc_chat_contacts
                   SET added_manually = TRUE, last_seen = ?
                   WHERE node_id = ?""",
                (datetime.now(UTC).isoformat(), node_id)
            )
            name = self._contacts_cache[node_id]
            if quiet:
                log.debug(f"Added contact to MC device: {name} ({node_id})")
            else:
                log.info(f"Added contact to MC device: {name} ({node_id})")
            return True
        else:
            name = self._contacts_cache[node_id]
            log.error(
                f"Failed to add contact {name}: {result.payload if result else 'No data'}")
            return False

    async def delete_node(self, node_id: str) -> bool:
        """Remove a chat node from meshcore device."""
        if not self.meshcore:
            log.error("MeshCore not available for deleting contact")
            return False

        query = "SELECT public_key FROM mc_chat_contacts WHERE node_id = ?"
        result = await self.db.execute(query, (node_id,))
        if result:
            pubkey = result[0][0]
        else:
            log.warning(f"Unable to remove {node_id}; node not in DB")
            return False

        try:
            result = await self.meshcore.commands.remove_contact(pubkey)
        except (OSError, AttributeError) as e:
            log.error(f"Error removing contact {node_id}: {e}")
            return False

        if result and result.type != EventType.ERROR:
            log.info(f"Removed contact from MC device: {node_id}")
            return True
        else:
            log.warning(
                f"Failed to remove contact {node_id}: {result.payload if result else 'No result'}")
            return False

    async def get_node(self, node_id: str) -> dict:
        """Get complete information about a chat node from database."""
        if node_id not in self._contacts_cache:
            return None

        result = await self.db.execute(
            """SELECT node_id, public_key, name, latitude, longitude,
                      first_seen, last_seen, added_manually, raw_advert_data
               FROM mc_chat_contacts WHERE node_id = ?""",
            (node_id,)
        )

        if not result:
            return None

        row = result[0]
        raw_data = {}
        if row[8]:
            try:
                raw_data = json.loads(row[8])
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            'node_id': row[0],
            'public_key': row[1],
            'name': row[2],
            'latitude': row[3],
            'longitude': row[4],
            'first_seen': row[5],
            'last_seen': row[6],
            'added_manually': bool(row[7]),
            'raw_advert_data': raw_data
        }

    async def get_all_nodes(self) -> dict:
        """Get basic info for all known chat nodes (cached data only)."""
        return {node_id: {'name': name} for node_id, name in self._contacts_cache.items()}

    async def _get_device_contact_count(self) -> int:
        """Get current number of contacts on the device."""
        if not self.meshcore:
            return 0

        try:
            result = await self.meshcore.commands.get_contacts()
        except (OSError, AttributeError) as e:
            log.error(f"Error getting device contact count: {e}")
            return 0

        if not result:
            log.warning("No data from contact count request")
            return 0

        if result.type == EventType.ERROR:
            log.warning(f"Unable to get device contact list: {result.payload}")
            return 0

        contacts = result.payload
        return len(contacts) if contacts else 0

    async def _cleanup_if_needed(self):
        """Check if cleanup is needed and perform it."""
        current_count = await self._get_device_contact_count()
        max_contacts = self.config.get('max_device_contacts', 240)
        buffer_size = self.config.get('contact_limit_buffer', 10)

        if current_count >= (max_contacts - buffer_size):
            log.info(
                f"Contact cleanup triggered: {current_count}/{max_contacts} contacts")
            await self._expire_oldest_contact()

    async def _expire_oldest_contact(self) -> bool:
        """Remove the oldest contact from the device to make room."""
        if not self.meshcore:
            return False

        try:
            result = await self.meshcore.commands.get_contacts()
        except (OSError, AttributeError) as e:
            log.error(f"Error getting device contacts for expiry: {e}")
            return False

        if result.type == EventType.ERROR:
            log.warning(
                f"No device contacts found to expire: {result.payload}")
            return False

        device_contacts = result.payload

        # Find the oldest contact from our database
        oldest_node_id = None
        oldest_time = datetime.now(UTC)

        for contact_key, contact_data in device_contacts.items():
            node_id = contact_data.get('public_key', contact_key)[:16]

            result = await self.db.execute(
                "SELECT last_seen FROM mc_chat_contacts WHERE node_id = ?",
                (node_id,)
            )

            if result:
                try:
                    last_seen = datetime.fromisoformat(result[0][0])
                except ValueError:
                    continue

                if last_seen < oldest_time:
                    oldest_time = last_seen
                    oldest_node_id = node_id
            else:
                # No database record, this is very old
                oldest_node_id = node_id
                break

        if oldest_node_id:
            contact_name = "Unknown"
            if oldest_node_id in self._contacts_cache:
                contact_name = self._contacts_cache[oldest_node_id]

            days = (datetime.now(UTC) - oldest_time).days
            if await self.delete_node(oldest_node_id):
                log.info(
                    f"Expired oldest contact to make room: {contact_name} ({oldest_node_id}) - {days}d old")
                return True
            else:
                log.error(
                    f"Failed to expire oldest contact: {contact_name} ({oldest_node_id}) - {days}d old")
                return False
        else:
            log.warning("Could not identify oldest contact to expire")
            return False

    async def get_contact_usage_stats(self) -> dict:
        """Get contact usage statistics."""
        current_count = await self._get_device_contact_count()
        max_contacts = self.config.get('max_device_contacts', 240)
        buffer = self.config.get('contact_limit_buffer', 10)

        return {
            'current_contacts': current_count,
            'max_contacts': max_contacts,
            'available_slots': max(0, max_contacts - current_count),
            'buffer_slots': buffer,
            'usage_percentage': (current_count / max_contacts) * 100,
            'is_near_limit': current_count >= (max_contacts - buffer),
            'is_at_limit': current_count >= max_contacts,
            'cached_nodes': len(self._contacts_cache)
        }
