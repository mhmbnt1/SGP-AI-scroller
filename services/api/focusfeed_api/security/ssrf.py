"""SSRF guard for any server-side fetch of user- or page-supplied URLs.

Checks scheme, host, port, resolved addresses (all A/AAAA records), and is
re-applied on every redirect hop by ``SafeFetcher``. Private, loopback,
link-local, multicast, reserved and cloud-metadata destinations are refused.

Locally configured inference (Ollama) is a *separate privileged path* and must
never go through this guard with a user-controlled URL; see providers/ollama.py.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

ALLOWED_SCHEMES = {"https", "http"}
ALLOWED_PORTS = {80, 443}
BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
MAX_REDIRECTS = 3
MAX_BYTES_DEFAULT = 5_000_000


class UnsafeURL(ValueError):
    pass


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))  # CGNAT
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("169.254.169.254/32"))
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    )


def resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"could not resolve host: {host}") from exc
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not out:
        raise UnsafeURL(f"no addresses for host: {host}")
    return out


def validate_url(url: str, *, allowed_domains: set[str] | None = None, resolver=resolve_host) -> str:
    """Return the normalized URL or raise ``UnsafeURL``.

    ``allowed_domains`` restricts to those registrable domains (and subdomains).
    """
    if not isinstance(url, str) or len(url) > 2048:
        raise UnsafeURL("url too long or not a string")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"scheme not allowed: {parts.scheme or 'none'}")
    if parts.username or parts.password:
        raise UnsafeURL("credentials in URL are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURL("missing host")
    if host in BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".internal") or host.endswith(".local"):
        raise UnsafeURL(f"host not allowed: {host}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURL(f"port not allowed: {port}")
    # literal IP?
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public_ip(literal):
            raise UnsafeURL("destination address is not public")
    else:
        if allowed_domains is not None and not any(host == d or host.endswith("." + d) for d in allowed_domains):
            raise UnsafeURL(f"domain not in allowlist: {host}")
        for ip in resolver(host):
            if not _is_public_ip(ip):
                raise UnsafeURL("host resolves to a non-public address")
    return parts.geturl()


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str


class SafeFetcher:
    """HTTP(S) fetcher that validates every hop and bounds the body size."""

    def __init__(self, *, allowed_domains: set[str] | None = None, max_bytes: int = MAX_BYTES_DEFAULT,
                 timeout: float = 15.0, resolver=resolve_host) -> None:
        self.allowed_domains = allowed_domains
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.resolver = resolver

    def fetch(self, url: str) -> FetchResult:
        current = validate_url(url, allowed_domains=self.allowed_domains, resolver=self.resolver)
        with httpx.Client(follow_redirects=False, timeout=self.timeout, headers={"User-Agent": "FocusFeed/0.1"}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise UnsafeURL("redirect without location")
                        current = validate_url(
                            str(httpx.URL(current).join(location)), allowed_domains=self.allowed_domains,
                            resolver=self.resolver,
                        )
                        continue
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > self.max_bytes:
                            raise UnsafeURL("response exceeds size limit")
                    return FetchResult(current, resp.status_code, bytes(buf), resp.headers.get("content-type", ""))
        raise UnsafeURL("too many redirects")
