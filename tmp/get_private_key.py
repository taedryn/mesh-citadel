"""this script will remove all non-chat nodes (ie, not type = 1) from
the connected USB companion."""

import logging
import asyncio
from pprint import pprint as pp

from meshcore import MeshCore, EventType

log = logging.getLogger('list_contacts')
log.setLevel(logging.DEBUG)

async def main():
    mc = await MeshCore.create_serial('/dev/ttyACM0', 115200)
    result = await mc.commands.export_private_key()
    if result.type == EventType.ERROR:
        print(f"Foo: {result.payload}")
    priv_key = result.payload['private_key'].hex()

    pp(priv_key)


if __name__ == '__main__':
    asyncio.run(main())
