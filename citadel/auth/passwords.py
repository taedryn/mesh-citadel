# citadel/auth/passwords.py

import hashlib
import os
import base64
import logging
import time


log = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 100_000
HASH_LENGTH = 64
SALT_LENGTH = 16


def generate_salt() -> bytes:
    return os.urandom(SALT_LENGTH)


def hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=HASH_LENGTH
    )
    return base64.b64encode(dk).decode("utf-8")


def verify_password(password: str, salt: bytes, stored_hash: str) -> bool:
    computed = hash_password(password, salt)
    return computed == stored_hash


async def authenticate(db_mgr, username_input: str, password_input: str):
    from citadel.user.user import User
    # Preserve case, User methods handle case-insensitive lookup
    username = username_input.strip()

    # Check if user exists
    if not await User.username_exists(db_mgr, username):
        log.info(f"Unknown username '{username}'")
        return None

    # Get the actual stored username (with correct capitalization)
    actual_username = await User.get_actual_username(db_mgr, username)
    if not actual_username:
        log.info(f"Unknown username '{username}'")
        return None

    # Verify password
    if not await User.verify_password(db_mgr, username, password_input):
        log.warning(f"Failed login attempt for '{username}'")
        log.warning("Sleeping 5 seconds to spoil brute-force attacks.")
        time.sleep(5)
        return None

    # Return user object with actual stored username
    user = User(db_mgr, actual_username)
    await user.load()
    return user
