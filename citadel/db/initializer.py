import logging

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def initialize_database(db_manager):
    log.info("Initializing database schema...")

    user_table = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt BLOB NOT NULL,
        display_name TEXT,
        last_login TIMESTAMP,
        permission TEXT NOT NULL CHECK(permission IN (
            'unverified', 'twit', 'user', 'aide', 'sysop'
        ))
    );
    """

    # Future tables like messages, rooms, etc. can be added here
    tables = [user_table]

    for sql in tables:
        try:
            db_manager.execute(sql)
            log.info("Table initialized successfully.")
        except RuntimeError as e:
            log.error(f"Failed to initialize table: {e}")

