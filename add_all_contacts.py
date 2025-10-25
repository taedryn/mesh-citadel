"""this script will remove all non-chat nodes (ie, not type = 1) from
the connected USB companion."""

import logging
import asyncio

from meshcore import MeshCore, EventType

import sys
sys.path.append("..")

from citadel.transport.engines.meshcore.contacts import ContactManager
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.config import Config

log = logging.getLogger('add_all_contacts')
log.setLevel(logging.DEBUG)

async def main():
    config = Config()
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    mc = await MeshCore.create_serial('/dev/ttyACM0', 115200)
    contact_mgr = ContactManager(mc, db_mgr, config)
    await contact_mgr.start()

    result = await mc.commands.get_contacts()
    if result.type == EventType.ERROR:
        print(f"Foo: {result.payload}")
    contacts = result.payload

    i = 1
    for pubkey in contacts:
        node_id = pubkey[:16]
        details = await contact_mgr._get_contact_details(pubkey)
        print(f'Adding {details["adv_name"]} to database')
        await contact_mgr._update_contact_record(node_id, details)

    await db_mgr.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
