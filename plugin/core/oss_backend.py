"""Client for Mem0 OSS REST. Runs inside the Codex plugin, with no relay."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # A redirect must never forward the key or captured session content.
        return None


def config() -> dict[str, str]:
    path = Path(os.environ.get("MEM0_LOCAL_CONFIG", "~/.config/mem0-codex/config.json")).expanduser()
    try:
        with path.open(encoding="utf-8") as handle:
            if os.fstat(handle.fileno()).st_mode & 0o077:
                raise ValueError("Mem0 config must be private (chmod 600)")
            values = json.load(handle)
    except FileNotFoundError:
        values = {}
    if not isinstance(values, dict):
        raise ValueError("Mem0 config must be a JSON object")
    return values


def api_key() -> str:
    return (os.environ.get("MEM0_LOCAL_API_KEY") or config().get("api_key") or "").strip()


def endpoint() -> str:
    value = (os.environ.get("MEM0_LOCAL_URL") or config().get("url") or "").rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname == "mem0.ai"
        or parsed.hostname.endswith(".mem0.ai")
    ):
        raise ValueError("Configure a self-hosted Mem0 HTTP(S) URL")
    return value


def request(
    method: str, path: str, key: str, body: dict[str, Any] | None = None, timeout: float = 15
) -> tuple[Any, int, int]:
    raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        endpoint() + path,
        data=raw,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        data = response.read()
    return json.loads(data or b"{}"), len(raw or b""), len(data)


def results(value: Any) -> list[dict[str, Any]]:
    rows = value.get("results") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Unexpected response from Mem0 OSS")
    return rows


def search(key: str, payload: dict[str, Any], timeout: float):
    fields = ("query", "filters", "top_k", "threshold")
    body = {k: payload[k] for k in fields if k in payload}
    # OSS validates that each search has a top-level entity. Search each
    # scoped branch independently and merge their nearest results.
    branches = body["filters"].get("OR")
    if not branches:
        return request("POST", "/search", key, body, timeout)
    with ThreadPoolExecutor(max_workers=len(branches)) as pool:
        pending = [
            pool.submit(request, "POST", "/search", key, {**body, "filters": branch}, timeout)
            for branch in branches
        ]
        replies = [future.result() for future in pending]
    unique = {}
    for response, _, _ in replies:
        for row in results(response):
            memory_id = row["id"]
            if memory_id not in unique or score(row) > score(unique[memory_id]):
                unique[memory_id] = row
    ranked = sorted(unique.values(), key=score, reverse=True)
    return (
        {"results": ranked[:body["top_k"]]},
        sum(reply[1] for reply in replies),
        sum(reply[2] for reply in replies),
    )


def score(row: dict[str, Any]) -> float:
    return float(row.get("score") or 0)


def scoped_ids(key: str, filters: dict[str, str], app_id: str) -> set[str]:
    limit = 1000  # OSS list API has a limit but no cursor.
    query = urllib.parse.urlencode({**filters, "top_k": limit, "show_expired": "true"})
    rows = results(request("GET", "/memories?" + query, key)[0])
    if len(rows) >= limit:
        raise ValueError("Mem0 OSS listing may be truncated; no memories were deleted")
    return {
        str(row["id"])
        for row in rows
        if row.get("id") and (row.get("metadata") or {}).get("app_id") == app_id
    }


def delete(key: str, memory_id: str) -> None:
    request("DELETE", "/memories/" + urllib.parse.quote(memory_id, safe=""), key)
