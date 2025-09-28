import pytest
from citadel.auth import passwords

def test_generate_salt_is_random_and_correct_length():
    salt1 = passwords.generate_salt()
    salt2 = passwords.generate_salt()
    assert isinstance(salt1, bytes)
    assert isinstance(salt2, bytes)
    assert len(salt1) == passwords.SALT_LENGTH
    assert len(salt2) == passwords.SALT_LENGTH
    assert salt1 != salt2  # Should be random

def test_hash_password_is_consistent_for_same_input():
    password = "securepassword123"
    salt = b"static_salt_123456"  # 16 bytes
    hash1 = passwords.hash_password(password, salt)
    hash2 = passwords.hash_password(password, salt)
    assert isinstance(hash1, str)
    assert hash1 == hash2

def test_hash_password_differs_with_different_salts():
    password = "securepassword123"
    salt1 = b"salt_one_12345678"
    salt2 = b"salt_two_87654321"
    hash1 = passwords.hash_password(password, salt1)
    hash2 = passwords.hash_password(password, salt2)
    assert hash1 != hash2

def test_verify_password_success():
    password = "mysecret"
    salt = passwords.generate_salt()
    hashed = passwords.hash_password(password, salt)
    assert passwords.verify_password(password, salt, hashed) is True

def test_verify_password_failure():
    password = "mysecret"
    wrong_password = "notmysecret"
    salt = passwords.generate_salt()
    hashed = passwords.hash_password(password, salt)
    assert passwords.verify_password(wrong_password, salt, hashed) is False

