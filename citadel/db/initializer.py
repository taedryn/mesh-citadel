import logging

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


async def initialize_database(db_manager, config=None):
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

    room_ignores_table = """
    CREATE TABLE IF NOT EXISTS room_ignores (
        username INTEGER NOT NULL REFERENCES users(username),
        room_id INTEGER NOT NULL REFERENCES rooms(id),
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
        room_ignores_table,
    ]

    for sql in tables:
        try:
            await db_manager.execute(sql)
        except RuntimeError as e:
            log.error(f"Failed to initialize table: {e}")

    log.info("Tables initialized successfully")

    # Initialize system rooms if config is provided
    if config:
        await initialize_system_rooms(db_manager, config)


async def initialize_system_rooms(db_manager, config):
    """Initialize the five core system rooms that must always exist."""
    from citadel.room.room import Room

    log.info("Initializing system rooms...")

    # Get room names from config
    room_names = Room.get_system_room_names(config)

    # System room definitions: (id, name, description, permission_level)
    system_rooms = [
        (Room.LOBBY_ID, room_names[Room.LOBBY_ID],
         "Main discussion area", "user"),
        (Room.MAIL_ID, room_names[Room.MAIL_ID],
         "Private message area", "user"),
        (Room.AIDES_ID, room_names[Room.AIDES_ID],
         "Aide discussion room", "aide"),
        (Room.SYSOP_ID, room_names[Room.SYSOP_ID],
         "Sysop discussion room", "sysop"),
        (Room.SYSTEM_ID, room_names[Room.SYSTEM_ID],
         "System events and logs", "sysop")
    ]

    # Set up linear room chain: NULL <- 1 <-> 2 <-> 3 <-> 4 <-> 5 -> NULL
    for i, (room_id, name, description, permission_level) in enumerate(system_rooms):
        # NULL for first room
        prev_id = system_rooms[i-1][0] if i > 0 else None
        # NULL for last room
        next_id = system_rooms[i+1][0] if i < len(system_rooms)-1 else None

        # Insert or update room
        await db_manager.execute("""
            INSERT OR REPLACE INTO rooms
            (id, name, description, read_only, permission_level, prev_neighbor, next_neighbor)
            VALUES (?, ?, ?, FALSE, ?, ?, ?)
        """, (room_id, name, description, permission_level, prev_id, next_id))

    log.info("System rooms initialized successfully")
