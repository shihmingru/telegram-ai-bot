"""SSRF-aware public URL fetching with redirect checks."""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse
import requests

def validate_public_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("URL is missing or too long.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Local hostnames are not allowed.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("The URL hostname could not be resolved.") from exc
    if not addresses or any(not ip.is_global for ip in addresses):
        raise ValueError("Private, local, or reserved network destinations are not allowed.")
    return url

def safe_get(url, *, headers=None, params=None, timeout=10, max_bytes=2000000):
    current = validate_public_url(url)
    for _ in range(5):
        response = requests.get(current, headers=headers, params=params, timeout=timeout, allow_redirects=False, stream=True)
        params = None
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("Redirect did not include a destination.")
            current = validate_public_url(urljoin(current, location))
            continue
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > max_bytes:
                response.close()
                raise ValueError("The remote response exceeded the size limit.")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response._content_consumed = True
        response.url = current
        return response
    raise ValueError("Too many redirects.")
