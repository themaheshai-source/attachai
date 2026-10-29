from __future__ import annotations
import base64
import hashlib
import hmac
import os
import re
from urllib.parse import urlsplit


def generate_api_key() -> str:
    raw = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")
    return "tai_" + raw


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def normalize_domain(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Invalid domain")
    parsed = urlsplit(raw if "://" in raw else "https://" + raw)
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Invalid domain")
    host = parsed.hostname.lower().rstrip(".")
    if not host or any(ch.isspace() for ch in host):
        raise ValueError("Invalid domain")
    port = parsed.port
    return f"{host}:{port}" if port else host


def normalize_origin(value: str) -> str:
    """Normalize an HTTP(S) origin while preserving its scheme and non-default port."""
    raw = value.strip()
    if not raw or any(ch in raw for ch in "\r\n\t"):
        raise ValueError("Invalid origin")
    parsed = urlsplit(raw)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Invalid origin")
    host = parsed.hostname.lower().rstrip(".")
    if not host or any(ch.isspace() for ch in host):
        raise ValueError("Invalid origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid origin port") from exc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    authority = f"{host}:{port}" if port and port != default_port else host
    return f"{parsed.scheme.lower()}://{authority}"


def origin_matches(origin: str, allowed: list[str] | tuple[str, ...]) -> bool:
    """Match an HTTP(S) browser origin against a tenant host/optional-port allowlist.

    Use origin parsing rather than URL-as-domain parsing so non-HTTP schemes are
    rejected and default ports (https:443/http:80) match their canonical origin.
    Non-default ports remain significant.
    """
    try:
        normalized = normalize_origin(origin)
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        candidate = f"{host}:{port}" if port else host
        return candidate in allowed
    except (ValueError, TypeError):
        return False


def safe_segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Unsafe path segment")
    return value


def clean_filename(name: str) -> str:
    # Use basename first, then a conservative ASCII allowlist like the original adapter.
    base = name.replace("\\", "/").split("/")[-1]
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not clean or clean in {".", ".."}:
        raise ValueError("Unsafe filename")
    return clean
