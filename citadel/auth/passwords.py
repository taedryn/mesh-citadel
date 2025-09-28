# citadel/auth/passwords.py

import hashlib
import os
import base64

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

