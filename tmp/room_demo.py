import asyncio
from meshcore import MeshCore, EventType

# === Configuration ===
SERIAL_PORT = "/dev/ttyUSB0"  # Adjust as needed
BAUDRATE = 115200

# === Packet Handler ===
def handle_packet(packet):
    print("\n📦 Incoming Packet:")
    print(f"  Sender ID: {packet.sender_id}")
    print(f"  Packet Type: {packet.packet_type:#04x}")
    print(f"  Timestamp: {packet.timestamp}")
    print(f"  Raw Payload: {packet.payload}")
    try:
        decoded = packet.payload.decode("utf-8")
        print(f"  Decoded Payload: {decoded}")
    except Exception:
        print("  Payload could not be decoded as UTF-8.")

    if isinstance(packet.payload, dict):
        print("Showing packet contents as dict")
        for key, val in packet.payload.items():
            print(f"{key}: {val}")

# === Main Routine ===
async def main():
    print("🔌 Connecting to MeshCore USB node...")
    meshcore = await MeshCore.create_serial(SERIAL_PORT, baudrate=BAUDRATE)

    # Configure radio
    print("📡 Configuring radio parameters...")
    await meshcore.commands.set_radio(910.525, 62.5, 7, 5)
    await meshcore.commands.set_tx_power(1)

    # Set node identity
    print("🪪 Setting node identity...")
    await meshcore.commands.set_name("Citadel Test Node")
    await meshcore.commands.set_custom_var("role", "room_server")

    # Send room server handshake
    print("📣 Sending advert")
    await meshcore.commands.send_advert(flood=False)

    # Subscribe to incoming messages
    meshcore.subscribe(EventType.CONTACT_MSG_RECV, handle_packet)
    print("👂 Listening for incoming packets...")

    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())

