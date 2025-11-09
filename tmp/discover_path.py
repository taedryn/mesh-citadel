import asyncio
from pprint import pprint as pp

from meshcore import MeshCore

async def handle_ack(event):
    print(f"ack received: {event.payload['code']}")

async def main():
    mc = await MeshCore.create_serial("/dev/ttyACM0", baudrate=115200)
    # jade, tae's tag, busbot
    nodes = [
        "9b4792e0ff70ad4f9dd3c53740895f17b4ff6d34301eb325d74892d0108892cd",
        "0895dec9caa112d14c33207915a5558a9b4c4102332c4e273abe2574954d8a44",
        "5f2b6193ce9709564498bd0a934e3f1f287264da531b3801d2b356804ce34df1"]
    for node in nodes:
        event = await mc.commands.send_path_discovery(node)
        print(f"Outcome for {node}:")
        pp(event)
    i = 0
    while True:
        if i > 10:
            print("Timeout finished")
            return
        await asyncio.sleep(1)
        i += 1

if __name__ == '__main__':
    asyncio.run(main())
