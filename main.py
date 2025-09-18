import logging

from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.loginit import initialize_logging

def main():
    config = Config()
    initialize_logging(config)

    log = logging.getLogger('citadel')

    log.info(f'Starting {config.bbs["system_name"]}')

    log.info('Starting database system')
    db_mgr = DatabaseManager(config)
    initialize_database(db_mgr)

    log.info('Startup complete')


if __name__ == '__main__':
    main()
