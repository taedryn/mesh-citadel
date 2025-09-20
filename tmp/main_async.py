import asyncio
import logging
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.loginit import initialize_logging


async def main():
    config = Config()
    initialize_logging(config)

    log = logging.getLogger('citadel')
    log.info(f'Starting {config.bbs["system_name"]}')

    # Create and start database
    db_manager = DatabaseManager(config)
    await db_manager.start()

    try:
        log.info('Initializing database schema')
        await initialize_database(db_manager)  # This will need to be async too

        log.info('Startup complete')

        # Your main application loop here
        # await run_bbs(config, db_manager)

    finally:
        await db_manager.close()


if __name__ == '__main__':
    asyncio.run(main())