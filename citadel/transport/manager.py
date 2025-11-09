"""
Transport Manager for coordinating multiple transport engines.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from citadel.config import Config
from citadel.transport.engines.cli import CLITransportEngine
from citadel.transport.engines.meshcore import MeshCoreTransportEngine


log = logging.getLogger(__name__)

class TransportError(Exception):
    """Indicates an error has occurred in the transport system"""

class TransportManager:
    """
    Manages multiple transport engines and coordinates their lifecycle.

    Currently supports CLI transport, with future support planned for
    MeshCore protocol and other transport mechanisms.
    """

    def __init__(self, config: Config, db_manager, session_manager):
        self.config = config
        self.db_manager = db_manager
        self.session_manager = session_manager
        self.engines: Dict[str, Any] = {}
        self._running = False

    async def start(self) -> None:
        """Start all configured transport engines."""
        if self._running:
            return

        log.info("Starting transport manager")

        # Get transport configuration
        transport_config = self.config.transport
        for engine_type in transport_config:
            if engine_type == 'cli':
                await self._start_cli_engine(transport_config)
            elif engine_type == 'meshcore':
                await self._start_meshcore_engine()
            else:
                raise ValueError(f"Unknown transport engine: {engine_type}")

        self._running = True
        num_engines = len(self.engines)
        e_word = "engine" if num_engines == 1 else "engines"
        if "meshcore" in self.engines:
            self.mc_watchdog = WatchdogController(
                "MeshCore",
                60,
                reset_meshcore
            )
        log.info(f"Transport manager started with {num_engines} {e_word} running")

    async def stop(self) -> None:
        """Stop all transport engines."""
        if not self._running:
            return

        log.info("Stopping transport manager")

        # Stop all engines
        for name, engine in self.engines.items():
            log.info(f"Stopping transport engine: {name}")
            if hasattr(engine, 'stop'):
                await engine.stop()

        self.engines.clear()
        self._running = False
        log.info("Transport manager stopped")

    async def _start_cli_engine(self, config: Dict[str, Any]) -> None:
        """Start the CLI transport engine."""
        log.info("Starting CLI transport engine")

        # Create Unix socket path
        socket_name = self.config.transport.get("cli",
                                                {}).get("socket",
                                                "/tmp/mesh-citadel-cli.sock")
        socket_path = Path(socket_name)
        if socket_path.exists():
            socket_path.unlink()

        engine = CLITransportEngine(
            socket_path=socket_path,
            config=self.config,
            db_manager=self.db_manager,
            session_manager=self.session_manager
        )

        await engine.start()
        self.engines['cli'] = engine

        log.info(f"CLI transport engine started on {socket_path}")

    async def _start_meshcore_engine(self) -> None:
        """Start the MeshCore transport engine"""
        engine = MeshCoreTransportEngine(
            session_mgr=self.session_manager,
            config=self.config,
            db=self.db_manager,
        )
        try:
            await engine.start()
        except:
            log.error("*** Unable to start MeshCore engine! Skipping")
            return
        self.engines['meshcore'] = engine
        log.info("MeshCore engine started")

    def restart_meshcore(self):
        """stop and start the meshcore engine to reset the connection"""
        # TODO: implement this
        if "meshcore" in self.engines:
            engine = self.engines["meshcore"]
            log.info(f"Stopping transport engine: {name}")
            if hasattr(engine, 'stop'):
                await engine.stop()
            await _start_meshcore_engine()
            log.info("MeshCore engine restarted")

    @property
    def is_running(self) -> bool:
        """Check if the transport manager is running."""
        return self._running

    def get_engine(self, name: str) -> Optional[Any]:
        """Get a transport engine by name."""
        return self.engines.get(name)


class WatchdogController:
    def __init__(self, name: str, timeout: int=60, reset_callback: Callable=None):
        self.name = name
        self.reset_callback = reset_callback
        self._reset_event = asyncio.Event()
        self._timeout = timeout
        self._watchdog_task = None
        self._shutdown = False

    async def start(self):
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    def get_reset_callback(self):
        async def reset():
            self._reset_event.set()
        return reset

    async def _watchdog_loop(self):
        while not self._shutdown:
            self._reset_event.clear()
            try:
                await asyncio.wait_for(self._reset_event.wait(), timeout=self._timeout)
                # Reset received — continue loop
            except asyncio.TimeoutError:
                log.error(f"{name} watchdog timed out. Resetting {name}")
                if self.reset_callback:
                    reset_callback()

    async def shutdown(self):
        self._shutdown = True
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

