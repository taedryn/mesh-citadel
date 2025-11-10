"""
Transport Manager for coordinating multiple transport engines.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from citadel.config import Config
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
        self.mc_watchdog = None
        self._running = False

    async def start(self) -> None:
        """Start all configured transport engines."""
        if self._running:
            return

        log.info("Starting transport manager")

        timeout = self.config.transport.get('meshcore', {}).get('watchdog_timeout', 60)
        self.mc_watchdog = WatchdogController(
            "MeshCore",
            timeout,
            self.restart_meshcore
        )

        # Get transport configuration
        transport_config = self.config.transport
        for engine_type in transport_config:
            if engine_type == 'cli':
                await self._start_cli_engine(transport_config)
            elif engine_type == 'meshcore':
                await self._start_meshcore_engine()
                await self.mc_watchdog.start()
            else:
                raise ValueError(f"Unknown transport engine: {engine_type}")

        self._running = True
        num_engines = len(self.engines)
        e_word = "engine" if num_engines == 1 else "engines"
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

        from citadel.transport.engines.cli import CLITransportEngine
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
            feed_watchdog=self.mc_watchdog.feed_watchdog
        )
        try:
            await engine.start()
        except:
            log.error("*** Unable to start MeshCore engine! Skipping")
            return
        self.engines['meshcore'] = engine
        log.info("MeshCore engine started")

    async def restart_meshcore(self):
        """stop and start the meshcore engine to reset the connection"""
        if "meshcore" in self.engines:
            engine = self.engines["meshcore"]
            log.info(f"Stopping transport engine: {name}")
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
    def __init__(self, name: str, timeout: int=60, timeout_action: Callable=None):
        self.name = name
        self.timeout_action = timeout_action
        self._feed_event = asyncio.Event()
        self._timeout = timeout
        self._watchdog_task = None
        self._shutdown = False

    async def start(self):
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        log.info(f"Starting watchdog timer for {self.name} engine")
        log.info(f"Set watchdog timeout to {self._timeout}s")

    def get_feed_callback(self):
        async def feed():
            self._feed_event.set()
            log.debug("Watchdog fed with feed()")
        return feed

    async def _watchdog_loop(self):
        while not self._shutdown:
            self._feed_event.clear()
            try:
                log.info("Waiting for watchdog to expire")
                await asyncio.wait_for(self._feed_event.wait(), timeout=self._timeout)
                # Reset received — continue loop
                log.info("Watchdog was fed, starting from 0")
            except asyncio.TimeoutError:
                log.error(f"{name} watchdog timed out. Restarting {name}")
                if self.timeout_action:
                    await timeout_action()

    async def shutdown(self):
        self._shutdown = True
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

    def feed_watchdog(self):
        self._feed_event.set()
        log.debug("Watchdog fed with feed_watchdog()")
