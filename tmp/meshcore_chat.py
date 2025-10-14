""" this script demonstrates a functional system to exchange messages
back and forth across meshcore DMs.  use it as a model for trading
messages back and forth between the BBS and remote nodes. """

import asyncio
from meshcore import MeshCore, EventType
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

SERIAL_PORT = "/dev/ttyUSB0"
BAUDRATE = 115200
RECIPIENT_ADDRESS = "d2ad8a40275e"

class MeshChatUI:
    def __init__(self, meshcore):
        self.mc = meshcore
        self._setup_ui()

    def _setup_ui(self):
        self.message_area = TextArea(
            text="📡 MeshCore Chat Client\n\n",
            read_only=True,
            scrollbar=True,
            wrap_lines=True,
            focusable=False,
        )
        self.input_area = TextArea(
            height=1,
            prompt="> ",
            multiline=False,
            wrap_lines=False,
        )
        self.status_bar = Window(
            content=FormattedTextControl(text="Connected to MeshCore"),
            height=1,
            style="class:status",
        )
        self.layout = Layout(HSplit([
            self.message_area,
            Window(height=1, char="-", style="class:line"),
            self.status_bar,
            self.input_area,
        ]))
        self.kb = KeyBindings()

        @self.kb.add("enter")
        def _(event):
            msg = self.input_area.text.strip()
            if msg:
                asyncio.create_task(self.send_message(msg))
                self._add_message(f"> {msg}")
                self.input_area.text = ""

        @self.kb.add("c-c")
        @self.kb.add("c-d")
        def _(event):
            event.app.exit()

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=Style.from_dict({
                "status": "reverse",
                "line": "#888888",
            }),
            full_screen=True,
        )
        self.app.layout.focus(self.input_area)

    def _add_message(self, text):
        self.message_area.text += text + "\n"
        self.message_area.buffer.cursor_position = len(self.message_area.text)

    async def send_message(self, msg):
        result = await self.mc.commands.send_msg(RECIPIENT_ADDRESS, msg)
        self._add_message(f"📤 Sent: {msg}")

    async def handle_incoming(self, packet):
        while True:
            packet = await self.mc.commands.get_msg()
            if packet.type == EventType.NO_MORE_MSGS:
                break
            elif packet.type == EventType.ERROR:
                self._add_message(f"❌ Error: {packet.payload}")
                break
            if isinstance(packet.payload, dict):
                sender = packet.payload.get("pubkey_prefix", "unknown")
                body = packet.payload.get("text", "")
                self._add_message(f"📥 {sender}: {body}")
            else:
                self._add_message(f"📥 {packet.payload}")

    async def run(self):
        self.mc.subscribe(EventType.MESSAGES_WAITING, self.handle_incoming)
        await self.app.run_async()

async def main():
    mc = await MeshCore.create_serial(SERIAL_PORT, baudrate=BAUDRATE)
    await mc.commands.set_radio(910.525, 62.5, 7, 5)
    await mc.commands.set_tx_power(1)
    await mc.commands.set_name("Citadel Test Node")
    await mc.commands.send_advert(flood=False)

    ui = MeshChatUI(mc)
    await ui.run()

if __name__ == "__main__":
    asyncio.run(main())

