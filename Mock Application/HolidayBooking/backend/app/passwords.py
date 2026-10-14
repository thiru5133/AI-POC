"""Password hashing with the standard library (scrypt): "scrypt$N$r$p$salt$hash"."""

import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
MIN_LENGTH, MAX_LENGTH = 8, 128


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


# Verified against when the email is unknown, so login timing does not reveal which accounts exist.
DUMMY_HASH = hash_password("not-a-real-password")


def generate_password(length: int = 14) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike characters
    return "".join(secrets.choice(alphabet) for _ in range(length))
