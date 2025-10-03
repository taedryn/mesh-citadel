# citadel/auth/login_handler.py

import logging
import time

from citadel.user.user import User
from citadel.auth.passwords import verify_password

log = logging.getLogger(__name__)


class LoginHandler:
    def __init__(self, db_mgr):
        self.db = db_mgr

    async def authenticate(self, username_input: str, password_input: str):
        username = username_input.strip()  # Preserve case, User methods handle case-insensitive lookup

        # Check if user exists
        if not await User.username_exists(self.db, username):
            log.info(f"Unknown username '{username}'")
            return None

        # Get the actual stored username (with correct capitalization)
        actual_username = await User.get_actual_username(self.db, username)
        if not actual_username:
            log.info(f"Unknown username '{username}'")
            return None

        # Verify password
        if not await User.verify_password(self.db, username, password_input):
            log.warning(f"Failed login attempt for '{username}'")
            log.warning("Sleeping 5 seconds to spoil brute-force attacks.")
            time.sleep(5)
            return None

        # Return user object with actual stored username
        user = User(self.db, actual_username)
        await user.load()
        return user
