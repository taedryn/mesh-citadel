"""this script will remove all non-chat nodes (ie, not type = 1) from
the connected USB companion."""

import logging
import asyncio

from meshcore import MeshCore, EventType

log = logging.getLogger('list_contacts')
log.setLevel(logging.DEBUG)

async def main():
    mc = await MeshCore.create_serial('/dev/ttyACM0', 115200)
    result = await mc.commands.get_contacts()
    if result.type == EventType.ERROR:
        print(f"Foo: {result.payload}")
    contacts = result.payload

    i = 1
    for contact in contacts:
        node_id = contact[:16]
        full_info = mc.get_contact_by_key_prefix(node_id)
        print(f"found {full_info['adv_name']}")

if __name__ == '__main__':
    asyncio.run(main())
