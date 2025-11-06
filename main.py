import asyncio
import argparse
import cProfile
import logging
import pstats
import sys
import tracemalloc

from citadel.commands.base import CommandContext
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.loginit import initialize_logging
from citadel.room.room import Room
from citadel.session.manager import SessionManager
from citadel.message.manager import MessageManager
from citadel.transport.manager import TransportManager

log = None
profiler = None

async def initialize_system(log_level=None, config_path=None):
    """Initialize all system components."""
    global log
    tracemalloc.start(20)
    config = Config(path=config_path) if config_path else Config()
    if log_level:
        config.logging["log_level"] = log_level
    initialize_logging(config)

    log = logging.getLogger('citadel')
    log.info(f'Starting {config.bbs["name"]}')
    log.info(f'Mesh-Citadel software version {config.version} by taedryn')

    # Initialize database
    log.info('Starting database system')
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    # Initialize other managers
    session_mgr = SessionManager(config, db_mgr)
    message_mgr = MessageManager(config, db_mgr)
    await Room.initialize_room_order(db_mgr, config)

    log.info('System initialization complete')

    return config, db_mgr, session_mgr, message_mgr


async def shutdown(db_mgr, session_mgr, transport_mgr=None):
    """Gracefully shutdown system components."""
    global log
    global profiler
    log.info('Shutting down system...')

    # Stop transport layer first
    if transport_mgr:
        await transport_mgr.stop()

    # Session cleanup handled automatically by SessionManager

    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('cumtime')
    stats.print_stats(50)  # top 50 functions by cumulative time

    # Close database connections
    if db_mgr:
        await db_mgr.shutdown()

    log.info('Shutdown complete')


def profile_main():
    global profiler
    profiler = cProfile.Profile()
    profiler.enable()

    asyncio.run(main())


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Mesh-Citadel BBS Server')
    parser.add_argument('-d', '--debug', action='store_true',
                       help='Enable debug logging')
    parser.add_argument('-c', '--config', type=str, default=None,
                       help='Path to config file (default: config.yaml)')
    return parser.parse_args()


async def main():
    """Main entry point."""
    global log
    config = db_mgr = session_mgr = message_mgr = None

    args = parse_arguments()
    log_level = "DEBUG" if args.debug else None

    try:
        # Initialize system components
        config, db_mgr, session_mgr, message_mgr = await initialize_system(log_level, args.config)

        # Start transport layer
        transport_mgr = TransportManager(config, db_mgr, session_mgr)
        await transport_mgr.start()

        # Keep server running until interrupted
        log.info('Server running. Press Ctrl+C to shutdown.')
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        log.info('Shutdown requested via keyboard interrupt')
    except Exception as e:
        log.error(f'System error: {e}')
        raise
    finally:
        # Always attempt graceful shutdown
        if 'transport_mgr' in locals():
            await shutdown(db_mgr, session_mgr, transport_mgr)
        elif db_mgr or session_mgr:
            await shutdown(db_mgr, session_mgr)



if __name__ == '__main__':
    try:
        asyncio.run(profile_main())
    except KeyboardInterrupt:
        # Clean exit - shutdown already handled in main()
        pass
