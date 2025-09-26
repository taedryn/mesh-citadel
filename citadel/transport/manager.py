"""
Transport Manager for coordinating multiple transport engines.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from citadel.config import Config
from citadel.transport.engines.cli import CLITransportEngine


logger = logging.getLogger(__name__)


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

        logger.info("Starting transport manager")

        # Get transport configuration
        transport_config = self.config.transport
        engine_type = transport_config.get('engine', 'cli')

        if engine_type == 'cli':
            await self._start_cli_engine(transport_config)
        else:
            raise ValueError(f"Unknown transport engine: {engine_type}")

        self._running = True
        logger.info("Transport manager started")

    async def stop(self) -> None:
        """Stop all transport engines."""
        if not self._running:
            return

        logger.info("Stopping transport manager")

        # Stop all engines
        for name, engine in self.engines.items():
            logger.info(f"Stopping transport engine: {name}")
            if hasattr(engine, 'stop'):
                await engine.stop()

        self.engines.clear()
        self._running = False
        logger.info("Transport manager stopped")

    async def _start_cli_engine(self, config: Dict[str, Any]) -> None:
        """Start the CLI transport engine."""
        logger.info("Starting CLI transport engine")

        # Create Unix socket path
        socket_path = Path("/tmp/mesh-citadel-cli.sock")
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

        logger.info(f"CLI transport engine started on {socket_path}")

    @property
    def is_running(self) -> bool:
        """Check if the transport manager is running."""
        return self._running

    def get_engine(self, name: str) -> Optional[Any]:
        """Get a transport engine by name."""
        return self.engines.get(name)