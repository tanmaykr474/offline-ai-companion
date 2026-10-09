"""Canonical loopback URLs avoid DNS, alternate IP spellings and proxies."""

import ipaddress
from urllib.parse import urlsplit


def local_endpoint(host: str) -> str:
    error = "Ollama requires an HTTP(S) loopback URL without credentials, path, query or fragment."
    if not isinstance(host, str) or any(c.isspace() or ord(c) < 32 for c in host) or "\\" in host or "%" in host:
        raise ValueError(error)
    try:
        parsed = urlsplit(host)
        port = parsed.port
        name = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not name
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or "?" in host or "#" in host or port == 0):
            raise ValueError(error)
        if name.lower().rstrip(".") == "localhost":
            address = ipaddress.ip_address("127.0.0.1")
        else:
            address = ipaddress.ip_address(name)
            mapped = getattr(address, "ipv4_mapped", None)
            if not address.is_loopback and not (mapped and mapped.is_loopback):
                raise ValueError(error)
            if mapped is not None:
                address = mapped
        literal = f"[{address}]" if address.version == 6 else str(address)
        return f"{parsed.scheme}://{literal}" + (f":{port}" if port is not None else "")
    except (ValueError, TypeError) as exc:
        raise ValueError(error) from exc
