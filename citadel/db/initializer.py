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

    user_blocks_table = """
    CREATE TABLE IF NOT EXISTS user_blocks (
        blocker TEXT NOT NULL,
        blocked TEXT NOT NULL,
        PRIMARY KEY (blocker, blocked),
        FOREIGN KEY (blocker) REFERENCES users(username) ON DELETE CASCADE,
        FOREIGN KEY (blocked) REFERENCES users(username) ON DELETE CASCADE
    );
    """

    messages_table = """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        recipient TEXT,  -- nullable for public messages
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    """

    rooms_table = """
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        read_only BOOLEAN DEFAULT FALSE,
        permission_level TEXT DEFAULT 'user', -- unverified/twit/user/aide/sysop
        next_neighbor INTEGER REFERENCES rooms(id),
        prev_neighbor INTEGER REFERENCES rooms(id)
    );
    """

    room_messages_table = """
    CREATE TABLE IF NOT EXISTS room_messages (
        room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        timestamp TEXT NOT NULL,
        PRIMARY KEY (room_id, message_id)
    );
    """

    user_room_state_table = """
    CREATE TABLE IF NOT EXISTS user_room_state (
        username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        last_seen_message_id INTEGER REFERENCES messages(id),
        PRIMARY KEY (username, room_id)
    );
    """

    # all tables to be initialized
    tables = [
        user_table,
        user_blocks_table,
        messages_table,
        rooms_table,
        room_messages_table,
        user_room_state_table,
    ]

    for sql in tables:
        try:
            db_manager.execute(sql)
        except RuntimeError as e:
            log.error(f"Failed to initialize table: {e}")

    log.info("Tables initialized successfully")
