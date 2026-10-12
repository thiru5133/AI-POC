"""Protections for admin-supplied MCP endpoints: secrets are encrypted at rest and URLs are checked before the
server makes any request to them (an admin must not be able to turn the backend into a proxy to internal hosts)."""

import base64
import hashlib
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.errors import AppError, ConfigurationError


class InvalidMcpUrlError(AppError):
    status_code = 422
    code = "invalid_mcp_url"


def _fernet(settings: Settings) -> Fernet:
    if settings.mcp_secret_key:
        return Fernet(settings.mcp_secret_key.encode())
    # No dedicated key: derive one from the JWT secret so a deployment that sets only JWT_SECRET is still safe.
    digest = hashlib.sha256(f"mcp-secrets:{settings.jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(settings: Settings, plain: str) -> str:
    return _fernet(settings).encrypt(plain.encode()).decode()


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        raise ConfigurationError("A stored MCP credential cannot be decrypted; re-enter it (key changed?)") from None


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def apply_localhost_alias(url: str, alias: str) -> str:
    """Docker development helper: connect to `alias` (e.g. host.docker.internal) instead of localhost/127.0.0.1.
    The saved URL is left as the admin typed it; only the connection is redirected."""
    if not alias:
        return url
    parts = urlsplit(url)
    if parts.hostname not in _LOCAL_HOSTS:
        return url
    return urlunsplit(parts._replace(netloc=f"{alias}:{parts.port}" if parts.port else alias))


def is_local_url(url: str) -> bool:
    return urlsplit(url).hostname in _LOCAL_HOSTS


def validate_mcp_url(url: str, allow_private_hosts: bool) -> str:
    """Returns the cleaned URL or raises InvalidMcpUrlError.

    Always refused: non-http(s) schemes, embedded credentials, and link-local / metadata / unspecified / multicast
    addresses. Loopback and private-network hosts are refused unless `allow_private_hosts` (local development,
    where the MCP server runs on the same machine).
    """
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise InvalidMcpUrlError("That is not a valid URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidMcpUrlError("The URL must start with http:// or https:// and include a host")
    if parts.username or parts.password:
        raise InvalidMcpUrlError("Put credentials in the access token field, not in the URL")
    try:
        infos = socket.getaddrinfo(parts.hostname, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise InvalidMcpUrlError(f"The host '{parts.hostname}' could not be resolved") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise InvalidMcpUrlError("That address is not allowed")
        if ip.is_loopback or ip.is_private:
            if not allow_private_hosts:
                raise InvalidMcpUrlError("Private and local network addresses are not allowed")
        elif ip.is_reserved:
            raise InvalidMcpUrlError("That address is not allowed")
    return url
