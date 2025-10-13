import asyncio
from meshcore import MeshCore, EventType

mc = None

# === Configuration ===
SERIAL_PORT = "/dev/ttyUSB0"  # Adjust as needed
BAUDRATE = 115200

# === Packet Handler ===
async def handle_incoming(packet):
    res = True
    while res:
        packet = await mc.commands.get_msg()
        if packet.type == EventType.NO_MORE_MSGS:
            res = False
            print("All messages retrieved")
            break
        elif packet.type == EventType.ERROR:
            res = False
            print(f"Error encountered: {packet.payload}")
            break
        info = packet.payload

        print("\n📦 Incoming Packet:")
        if isinstance(packet.payload, dict):
            print("Showing packet contents as dict")
            for key, val in packet.payload.items():
                print(f"{key}: {val}")

# === Main Routine ===
async def main():
    global mc
    print("🔌 Connecting to MeshCore USB node...")
    meshcore = await MeshCore.create_serial(SERIAL_PORT, baudrate=BAUDRATE)
    mc = meshcore

    # Configure radio
    print("📡 Configuring radio parameters...")
    result = await meshcore.commands.set_radio(910.525, 62.5, 7, 5)
    print('setting radio')
    print(result)
    result = await meshcore.commands.set_tx_power(1)
    print('setting tx power')
    print(result)

    """
    # Set node identity
    print("🪪 Setting node identity...")
    await meshcore.commands.set_name("Citadel Test Node")

    # note that the following block fails every time
    custom_vars = {
        "role": "room_server",
        "type": "2",
    }
    for key, value in custom_vars.items():
        result = await meshcore.commands.set_custom_var(key, value)
        print(f'setting "{key}: {value}"')
        print(result)
    # end failure block
    """

    # Send room server handshake
    print("📣 Sending advert")
    result = await meshcore.commands.send_advert(flood=False)
    print('sending advert')
    print(result)

    # Subscribe to incoming messages
    print("👂 Listening for incoming packets...")
    result = meshcore.subscribe(EventType.MESSAGES_WAITING, handle_incoming)
    print('subscribing to event')
    print(result)

    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())

