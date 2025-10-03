import asyncio
import tempfile
import pytest
from pathlib import Path

from citadel.auth.passwords import generate_salt, hash_password
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.config import Config
from citadel.session.manager import SessionManager
from citadel.transport.engines.cli import CLITransportEngine
from citadel.config import Config
from citadel.user.user import User


@pytest.mark.skip
@pytest.mark.asyncio
async def test_full_login_flow_through_cli(tmp_path):
    # Setup test user
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = Config()
    config.database['db_path'] = temp_db
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)
    session_mgr = SessionManager(config, db_mgr)

    salt = generate_salt()
    pw_hash = hash_password("secret", salt)
    await User.create(config, db_mgr, "bob", pw_hash, salt)

    # Setup CLI engine
    socket_path = tmp_path / "cli.sock"
    engine = CLITransportEngine(socket_path, config, db_mgr, session_mgr)
    await engine.start()

    try:
        # Connect to CLI socket
        reader, writer = await asyncio.open_unix_connection(str(socket_path))

        async def read_until(prompt):
            lines = []
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=1)
                if not line:
                    break
                decoded = line.decode().strip()
                lines.append(decoded)
                if prompt in decoded:
                    break
            return lines

        # Initial connection
        await read_until("Welcome")

        # Start login workflow
        writer.write(b"/connect testnode\n")
        await writer.drain()
        await read_until("Enter your username:")

        # Send username
        writer.write(b"bob\n")
        await writer.drain()
        await read_until("Enter your password:")

        # Send password
        writer.write(b"secret\n")
        await writer.drain()
        response = await read_until("Welcome, bob")

        assert any("Welcome, bob" in line for line in response)

    finally:
        await engine.stop()
        await db_mgr.shutdown()
        os.unlink(temp_db)

