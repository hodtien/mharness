"""WebUI password-based auth storage.

Persists a password hash and token data under ``~/.harness/webui/`` to
isolate WebUI auth from the rest of the OpenHarness config.

Compatibility: if ``~/.openharness/webui_auth.json`` exists, it is migrated
on first read and then unused.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------- Paths ----------------

_HARNESS_DIR = ".harness"
_WEBUI_DIR = "webui"
_AUTH_FILE = "auth.json"
_OLD_AUTH_FILE = "webui_auth.json"
_PASSWORD_KDF = "pbkdf2_sha256"
_LEGACY_PASSWORD_KDF = "sha256_salted"
_PASSWORD_ITERATIONS = 260_000


def _get_harness_dir() -> Path:
    """Return ~/.harness/, creating it if needed."""
    config_dir = Path.home() / _HARNESS_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _get_webui_dir() -> Path:
    """Return ~/.harness/webui/, creating it if needed."""
    d = _get_harness_dir() / _WEBUI_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _auth_path() -> Path:
    return _get_webui_dir() / _AUTH_FILE


def _old_auth_path() -> Path:
    """Legacy path in ~/.openharness/ for migration."""
    return Path.home() / ".openharness" / _OLD_AUTH_FILE


# ---------------- Helpers ----------------


def _hash_password(
    password: str,
    salt: str | None = None,
    iterations: int = _PASSWORD_ITERATIONS,
) -> tuple[str, str, int]:
    """Hash password with PBKDF2-HMAC-SHA256. Returns (hash, salt, iterations)."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return digest, salt, iterations


def _legacy_hash_password(password: str, salt: str) -> str:
    """Return the pre-P17.9 salted SHA-256 password digest."""
    return hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()


def _verify_password(
    password: str,
    hash_: str,
    salt: str,
    kdf: str,
    iterations: int,
) -> bool:
    """Constant-time comparison for password verification."""
    if kdf == _LEGACY_PASSWORD_KDF:
        computed = _legacy_hash_password(password, salt)
    else:
        computed, _, _ = _hash_password(password, salt, iterations)
    return secrets.compare_digest(computed, hash_)


def _set_password(auth: WebUIAuth, password: str, *, is_default_password: bool) -> None:
    hash_, salt, iterations = _hash_password(password)
    auth.password_hash = hash_
    auth.password_salt = salt
    auth.password_kdf = _PASSWORD_KDF
    auth.password_iterations = iterations
    auth.is_default_password = is_default_password


# ---------------- Token helpers ----------------


def _new_access_token() -> str:
    return secrets.token_urlsafe(32)


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def _hash_token(token: str) -> str:
    """Return a stable digest for a high-entropy bearer token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _verify_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(_hash_token(token), token_hash)


# ---------------- Data model ----------------


@dataclass
class TokenPair:
    """Access + refresh token pair with expiry timestamps."""

    access_token: str
    refresh_token: str
    access_expires_at: int  # Unix timestamp (seconds)
    refresh_expires_at: int  # Unix timestamp (seconds)


@dataclass
class StoredTokenPair:
    """Persisted token pair containing only token digests."""

    access_token_hash: str
    refresh_token_hash: str
    access_expires_at: int  # Unix timestamp (seconds)
    refresh_expires_at: int  # Unix timestamp (seconds)

    @classmethod
    def from_token_pair(cls, token_pair: TokenPair) -> StoredTokenPair:
        return cls(
            access_token_hash=_hash_token(token_pair.access_token),
            refresh_token_hash=_hash_token(token_pair.refresh_token),
            access_expires_at=token_pair.access_expires_at,
            refresh_expires_at=token_pair.refresh_expires_at,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredTokenPair:
        access_token_hash = data.get("access_token_hash")
        if access_token_hash is None:
            access_token_hash = _hash_token(str(data["access_token"]))

        refresh_token_hash = data.get("refresh_token_hash")
        if refresh_token_hash is None:
            refresh_token_hash = _hash_token(str(data["refresh_token"]))

        return cls(
            access_token_hash=str(access_token_hash),
            refresh_token_hash=str(refresh_token_hash),
            access_expires_at=int(data["access_expires_at"]),
            refresh_expires_at=int(data["refresh_expires_at"]),
        )


@dataclass
class WebUIAuth:
    """Root auth document stored in ~/.harness/webui/auth.json."""

    password_hash: str
    password_salt: str
    password_kdf: str = _PASSWORD_KDF
    password_iterations: int = _PASSWORD_ITERATIONS
    is_default_password: bool = True
    token_pair: StoredTokenPair | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "password_hash": self.password_hash,
            "password_salt": self.password_salt,
            "password_kdf": self.password_kdf,
            "password_iterations": self.password_iterations,
            "is_default_password": self.is_default_password,
        }
        if self.token_pair:
            d["token_pair"] = asdict(self.token_pair)
        else:
            d["token_pair"] = None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebUIAuth:
        token_pair = None
        if data.get("token_pair"):
            token_pair = StoredTokenPair.from_dict(data["token_pair"])
        password_kdf = data.get("password_kdf")
        if password_kdf is None:
            password_kdf = _LEGACY_PASSWORD_KDF
        return cls(
            password_hash=data["password_hash"],
            password_salt=data["password_salt"],
            password_kdf=password_kdf,
            password_iterations=int(data.get("password_iterations", _PASSWORD_ITERATIONS)),
            is_default_password=data.get("is_default_password", True),
            token_pair=token_pair,
        )


# ---------------- Storage ----------------


def _load() -> WebUIAuth:
    """Load auth data, migrating from legacy path if needed."""
    path = _auth_path()

    # Migrate legacy file on first run
    old_path = _old_auth_path()
    if old_path.exists() and not path.exists():
        try:
            data = json.loads(old_path.read_text(encoding="utf-8"))
            auth = WebUIAuth.from_dict(data)
            _save(auth)
            log.info("Migrated webui auth from ~/.openharness/")
            return auth
        except Exception as exc:
            log.warning("Failed to migrate legacy auth file: %s", exc)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            auth = WebUIAuth.from_dict(data)
            if auth.to_dict() != data:
                _save(auth)
            return auth
        except Exception as exc:
            log.warning("Failed to read auth file, reinitializing: %s", exc)

    # Fresh install: create with default password
    return _create_default()


def _save(auth: WebUIAuth) -> None:
    """Persist auth data to ~/.harness/webui/auth.json (mode 600)."""
    path = _auth_path()
    text = json.dumps(auth.to_dict(), indent=2) + "\n"
    # Use atomic write with strict permissions
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _create_default() -> WebUIAuth:
    """Create new auth with the default password (123456)."""
    hash_, salt, iterations = _hash_password("123456")
    auth = WebUIAuth(
        password_hash=hash_,
        password_salt=salt,
        password_kdf=_PASSWORD_KDF,
        password_iterations=iterations,
        is_default_password=True,
    )
    _save(auth)
    return auth


# ---------------- Public API ----------------


def get_auth() -> WebUIAuth:
    """Return the current auth state (singleton per process)."""
    return _load()


def verify_password(password: str) -> bool:
    """Verify the provided password against the stored hash."""
    auth = _load()
    valid = _verify_password(
        password,
        auth.password_hash,
        auth.password_salt,
        auth.password_kdf,
        auth.password_iterations,
    )
    if valid and auth.password_kdf != _PASSWORD_KDF:
        _set_password(auth, password, is_default_password=auth.is_default_password)
        _save(auth)
    return valid


def change_password(old_password: str, new_password: str) -> bool:
    """Change the password. Returns True on success, False if old password wrong."""
    auth = _load()
    if not _verify_password(
        old_password,
        auth.password_hash,
        auth.password_salt,
        auth.password_kdf,
        auth.password_iterations,
    ):
        return False
    _set_password(auth, new_password, is_default_password=False)
    # Clear existing tokens on password change (logout all sessions)
    auth.token_pair = None
    _save(auth)
    return True


def create_tokens(expires_in: int = 3600, refresh_expires_in: int = 604800) -> TokenPair:
    """Generate new access + refresh token pair.

    Args:
        expires_in: Access token lifetime in seconds (default 1 hour).
        refresh_expires_in: Refresh token lifetime in seconds (default 7 days).
    """
    now = int(time.time())
    return TokenPair(
        access_token=_new_access_token(),
        refresh_token=_new_refresh_token(),
        access_expires_at=now + expires_in,
        refresh_expires_at=now + refresh_expires_in,
    )


def store_tokens(token_pair: TokenPair) -> None:
    """Persist a token pair to the auth file."""
    auth = _load()
    auth.token_pair = StoredTokenPair.from_token_pair(token_pair)
    _save(auth)


def get_token_pair() -> StoredTokenPair | None:
    """Return the stored token pair, or None if none exists."""
    return _load().token_pair


def clear_tokens() -> None:
    """Revoke stored tokens (used on logout)."""
    auth = _load()
    auth.token_pair = None
    _save(auth)


def is_access_token_valid(token: str) -> bool:
    """Check if an access token is present and not expired."""
    pair = get_token_pair()
    if pair is None:
        return False
    if not _verify_token(token, pair.access_token_hash):
        return False
    return time.time() < pair.access_expires_at


def is_refresh_token_valid(token: str) -> bool:
    """Check if a refresh token is present and not expired."""
    pair = get_token_pair()
    if pair is None:
        return False
    if not _verify_token(token, pair.refresh_token_hash):
        return False
    return time.time() < pair.refresh_expires_at


def refresh_tokens(
    refresh_token: str,
    expires_in: int = 3600,
    refresh_expires_in: int = 604800,
) -> TokenPair | None:
    """Rotate tokens: consume stored refresh token, return new pair if valid."""
    auth = _load()
    stored_pair = auth.token_pair
    if stored_pair is None:
        return None
    if time.time() >= stored_pair.refresh_expires_at:
        auth.token_pair = None
        _save(auth)
        return None
    if not _verify_token(refresh_token, stored_pair.refresh_token_hash):
        return None

    new_pair = create_tokens(
        expires_in=expires_in,
        refresh_expires_in=refresh_expires_in,
    )
    auth.token_pair = StoredTokenPair.from_token_pair(new_pair)
    _save(auth)
    return new_pair


def is_default_password() -> bool:
    """Return True if the current password is still the default (123456)."""
    return _load().is_default_password
