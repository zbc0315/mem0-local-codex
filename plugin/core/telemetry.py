# Modified from the Mem0 Codex plugin for self-hosted REST integration.
"""Telemetry is disabled for the self-hosted plugin."""
from __future__ import annotations
import urllib.error


def init(*args, **kwargs):
    pass


def record(*args, **kwargs):
    pass


def data_dir_was_empty():
    return False


def claim_install(*args, **kwargs):
    return None


def claim_version_change():
    return None


def spawn_flush():
    return False


def error_kind(exc: BaseException | str) -> str:
    """Coarse, content-free label for a failure, safe to send."""
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "401" in lowered or "403" in lowered or "unauthor" in lowered or "forbidden" in lowered:
        return "auth"
    if "429" in lowered or "rate limit" in lowered:
        return "rate-limited"
    if any(code in lowered for code in ("500", "502", "503", "504")):
        return "server-error"
    if "400" in lowered or "422" in lowered:
        return "bad-request"
    if isinstance(exc, str):
        return "other"
    if isinstance(exc, urllib.error.URLError):
        return "network"
    return type(exc).__name__
