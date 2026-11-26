import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import memory_core as core
import oss_backend


@pytest.fixture
def server(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, method):
            path = urlsplit(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw) if raw else None
            calls.append((method, path.path, body, parse_qs(path.query)))
            if self.headers.get("X-API-Key") != "test-key":
                self.send_error(401)
                return
            if path.path == "/search" and (
                not any(scope in body["filters"] for scope in ("user_id", "agent_id", "run_id"))
                or set(body) - {"query", "filters", "top_k", "threshold"}
            ):
                self.send_error(400)
                return
            if path.path == "/memories" and method == "POST":
                assert body["infer"] and body["metadata"]["app_id"]
                assert "source" not in body and "app_id" not in body
                result = {"results": [{"id": "stored-id", "event": "ADD"}]}
            elif path.path == "/search":
                result = {"results": [{
                    "id": "result", "memory": "Use isolated environments", "score": 0.8
                }]}
            elif path.path == "/memories" and method == "GET":
                result = {"results": [
                    {"id": "selected", "metadata": {"app_id": "current"}},
                    {"id": "other", "metadata": {"app_id": "another"}},
                ]}
            elif path.path == "/memories/selected" and method == "DELETE":
                result = {"message": "deleted"}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def do_DELETE(self):
            self.respond("DELETE")

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        monkeypatch.setenv("MEM0_LOCAL_URL", f"http://127.0.0.1:{httpd.server_port}")
        monkeypatch.setenv("MEM0_LOCAL_API_KEY", "test-key")
        try:
            yield calls
        finally:
            httpd.shutdown()
            worker.join()


def test_capture_flushes_to_oss_and_recall_reads_without_cloud_event(server, tmp_path, monkeypatch):
    monkeypatch.setenv("MEM0_CODE_DATA_DIR", str(tmp_path / "data"))
    event = {"session_id": "s1", "cwd": str(tmp_path)}
    store = core.EvidenceStore()
    try:
        core.record_session_start(store, event)
        core.record_user_prompt(store, {
            **event,
            "prompt": 'Use isolated environments for tests. {"totp_secret":"test-secret-value"}',
        })
        first = core.flush_session(store, event, "session-end")
        assert first["status"] == "semantic-succeeded"
        assert first["memory_count"] == 2
        assert core.flush_session(store, event, "session-end")["status"] == "nothing-to-flush"
        repo = core.resolve_repo(str(tmp_path))
        recalled = core.search_memories(None, repo, None, "which environment?", run_id="s1")
        assert "Use isolated environments" in core.format_search_result(recalled)
    finally:
        store.close()
    writes = [body for method, path, body, _ in server if (method, path) == ("POST", "/memories")]
    assert len(writes) == 2
    assert "user_id" in writes[0] and "agent_id" not in writes[0]
    assert "agent_id" in writes[1] and "user_id" not in writes[1]
    assert "test-secret-value" not in json.dumps(writes[0])
    assert "[REDACTED]" in json.dumps(writes[0])
    assert writes[0]["run_id"] == "s1"
    searches = [body for _, path, body, _ in server if path == "/search"]
    assert len(searches) == 2
    assert all(body["filters"]["run_id"] == "s1" for body in searches)


def test_scoped_delete_checks_app_metadata(server):
    key = oss_backend.api_key()
    ids = oss_backend.scoped_ids(key, {"user_id": "tom", "agent_id": "project"}, "current")
    for memory_id in ids:
        oss_backend.delete(key, memory_id)
    assert ids == {"selected"}
    assert [(m, p) for m, p, _, _ in server] == [
        ("GET", "/memories"),
        ("DELETE", "/memories/selected"),
    ]


def test_endpoint_rejects_mem0_cloud(monkeypatch):
    monkeypatch.setenv("MEM0_LOCAL_URL", "https://api.mem0.ai")
    with pytest.raises(ValueError, match="self-hosted"):
        oss_backend.endpoint()


def test_stdio_tool_uses_workspace_filters(server, tmp_path):
    script = Path(core.__file__).with_name("mcp_server.py")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "search_memories",
            "arguments": {"query": "Which environment?", "scope": "mine", "category": "results"},
            "_meta": {"x-codex-turn-metadata": {"workspaces": {str(tmp_path): {}}}},
        }},
    ]
    result = subprocess.run(
        [sys.executable, str(script)], text=True, capture_output=True, timeout=10,
        check=True, input="".join(json.dumps(request) + "\n" for request in requests),
    )
    initialized, listed, recalled = [json.loads(line)["result"] for line in result.stdout.splitlines()]
    assert initialized["serverInfo"]["name"] == "mem0-local"
    assert listed["tools"][0]["name"] == "search_memories"
    assert "Use isolated environments" in recalled["content"][0]["text"]
    filters = server[0][2]["filters"]
    assert filters["app_id"] == core.resolve_repo(str(tmp_path)).app_id
    assert filters["data"] == {"contains": "[mem0-category:results]"}
    assert "user_id" in filters and "agent_id" not in filters
