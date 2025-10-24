import asyncio

from meshcore import MeshCore, EventType

async def main():
    outfile = "saved-contacts.out"
    mc = await MeshCore.create_serial('/dev/ttyACM0', 115200)
    result = await mc.commands.get_contacts()
    if result.type == EventType.ERROR:
        print(f"Foo: {result.payload}")
    contacts = result.payload

    i = 1
    for contact in contacts:
        node_id = contact[:16]
        full_info = mc.get_contact_by_key_prefix(node_id)
        if full_info['type'] != 1:
            print(f"removing {i}: {full_info}")
            result = await mc.commands.remove_contact(node_id)
            if result.type == EventType.ERROR:
                print(f"Unable to remove {node_id}: {result.payload}")
                continue
            print(f"Node {node_id} erased from device")
        i += 1

if __name__ == '__main__':
    asyncio.run(main())
