"""SSRF guard — validates user-supplied image URLs before server-side fetch."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

# Allowlist: suffix match against the URL hostname.
# Add new museum CDN domains here as new providers are integrated.
_ALLOWED_SUFFIXES = (
    ".wikimedia.org",
    ".wikipedia.org",
    ".metmuseum.org",
    ".rijksmuseum.nl",
    ".clevelandart.org",
    ".artic.edu",
    ".iiif.io",
    # AWS CloudFront distributions used by Met and AIC
    ".cloudfront.net",
)

_PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata endpoints
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        return any(ip in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def validate_image_url(url: str) -> None:
    """Raise HTTP 400 if url is not a safe, allowlisted image source.

    Checks (in order):
    1. Scheme must be http or https.
    2. Hostname must match an allowlisted museum/commons suffix.
    3. DNS resolution must not return a private or loopback address
       (blocks DNS-rebinding attacks against internal services).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image URL")

    if parsed.scheme not in ("https", "http"):
        raise HTTPException(status_code=400, detail="Image URL must use http or https")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise HTTPException(status_code=400, detail="Image URL has no host")

    allowed = any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_SUFFIXES)
    if not allowed:
        raise HTTPException(status_code=400, detail=f"Image host not in allowlist: {host}")

    # Resolve and verify — catches DNS rebinding where an allowlisted hostname
    # is temporarily pointed at an internal IP.
    try:
        for info in socket.getaddrinfo(host, None):
            resolved = info[4][0]
            if _is_private(resolved):
                raise HTTPException(
                    status_code=400,
                    detail="Image URL resolves to a private address",
                )
    except HTTPException:
        raise
    except OSError:
        raise HTTPException(status_code=400, detail="Image URL host could not be resolved")
