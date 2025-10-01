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
        username = username_input.strip().lower()

        # Check if user exists
        if not await User.username_exists(self.db, username):
            log.info(f"Unknown username '{username}'")
            return None

        # Verify password
        if not await User.verify_password(self.db, username, password_input):
            log.warning(f"Failed login attempt for '{username}'")
            log.warning("Sleeping 5 seconds to spoil brute-force attacks.")
            time.sleep(5)
            return None

        # Return user object
        user = User(self.db, username)
        return await user.load()

