import serial
import json
import time

# === Configuration ===
SERIAL_PORT = "/dev/ttyUSB0"  # Adjust as needed
BAUDRATE = 115200

# === Room Server Parameters ===
config = {
    "cmd": "CMD_SET_OTHER_PARAMS",
    "payload": {
        "node_name": "Citadel Autoconf BBS",
        "node_type": "room_server",
        "room_name": "Citadel Autoconf BBS",
        "login_required": True,
        "username_required": True
    }
}

def send_config():
    try:
        print("🔌 Connecting to MeshCore USB node...")
        ser = serial.Serial(SERIAL_PORT, baudrate=BAUDRATE, timeout=1)
        time.sleep(0.5)  # Give the device time to initialize

        message = json.dumps(config) + "\n"
        print("📤 Sending room server configuration...")
        ser.write(message.encode("utf-8"))

        i = 0
        while i < 10:
            time.sleep(0.5)
            response = ser.readline().decode("utf-8").strip()
            if response:
                print("📨 Response:", response)
                break
            else:
                print("✅ Configuration sent. No response received yet.")
                i += 1
        ser.close()

    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    send_config()

