import asyncio
import logging

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.loginit import initialize_logging
from citadel.session.manager import SessionManager
from citadel.message.manager import MessageManager
from citadel.transport.manager import TransportManager


async def initialize_system():
    """Initialize all system components."""
    config = Config()
    initialize_logging(config)

    log = logging.getLogger('citadel')
    log.info(f'Starting {config.bbs["system_name"]}')

    # Initialize database
    log.info('Starting database system')
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    # Initialize other managers
    session_mgr = SessionManager(config)
    message_mgr = MessageManager(config, db_mgr)

    log.info('System initialization complete')

    return config, db_mgr, session_mgr, message_mgr


async def shutdown(db_mgr, session_mgr):
    """Gracefully shutdown system components."""
    log = logging.getLogger('citadel')
    log.info('Shutting down system...')

    # Clean up sessions
    if session_mgr:
        session_mgr.cleanup_all_sessions()

    # Close database connections
    if db_mgr and hasattr(db_mgr, 'close'):
        await db_mgr.close()

    log.info('Shutdown complete')


async def main():
    """Main entry point."""
    config = db_mgr = session_mgr = message_mgr = None

    try:
        # Initialize system components
        config, db_mgr, session_mgr, message_mgr = await initialize_system()

        # Start transport layer
        transport_mgr = TransportManager(config, db_mgr, session_mgr, message_mgr)
        await transport_mgr.start()

    except KeyboardInterrupt:
        # TODO: Remove this once CLI transport handles KeyboardInterrupt properly
        logging.getLogger('citadel').info('Shutdown requested via keyboard interrupt')
    except Exception as e:
        logging.getLogger('citadel').error(f'System error: {e}')
        raise
    finally:
        # Always attempt graceful shutdown
        if db_mgr or session_mgr:
            await shutdown(db_mgr, session_mgr)


if __name__ == '__main__':
    asyncio.run(main())
