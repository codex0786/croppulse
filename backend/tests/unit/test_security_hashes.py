"""Password-hash serialization must fail closed for malformed stored values."""

import pytest

from croppulse.security import hash_password, verify_password


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "pbkdf2_sha256",
        "unknown$1000$c2FsdHNhbHRzYWx0c2FsdA==$eA==",
        "pbkdf2_sha256$not-a-number$c2FsdHNhbHRzYWx0c2FsdA==$eA==",
        "pbkdf2_sha256$0$c2FsdHNhbHRzYWx0c2FsdA==$eA==",
        "pbkdf2_sha256$999999999999999999999999$c2FsdHNhbHRzYWx0c2FsdA==$eA==",
        "pbkdf2_sha256$1000$%%%$eA==",
        "pbkdf2_sha256$1000$c2FsdA==$eA==",
        "pbkdf2_sha256$1000$c2FsdHNhbHRzYWx0c2FsdA==$eA==",
    ],
)
def test_malformed_password_hash_returns_false(encoded: str) -> None:
    assert verify_password("some-password", encoded) is False


def test_valid_password_hash_verifies() -> None:
    encoded = hash_password("a-valid-password", iterations=1_000)
    assert verify_password("a-valid-password", encoded) is True
    assert verify_password("a-different-password", encoded) is False
