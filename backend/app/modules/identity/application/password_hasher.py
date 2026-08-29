"""Argon2id password hashing service."""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import VerifyMismatchError


class PasswordHasher:
    """Thin wrapper around argon2-cffi using OWASP-recommended parameters."""

    def __init__(self) -> None:
        self._hasher = _Argon2(
            time_cost=3,
            memory_cost=64 * 1024,
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, hashed: str, password: str) -> bool:
        try:
            return self._hasher.verify(hashed, password)
        except VerifyMismatchError:
            return False

    def needs_rehash(self, hashed: str) -> bool:
        return self._hasher.check_needs_rehash(hashed)
