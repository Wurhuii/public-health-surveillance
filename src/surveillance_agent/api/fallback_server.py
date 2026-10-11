from __future__ import annotations

import json
import re
from typing import Any, Dict

from ..config import PROJECT_ROOT, load_config
from ..storage import Storage
from ..signal_catalog import catalog_document
from . import _run_once
from .institution_catalog import load_institution_catalog


def _db_path() -> str:
    return str(PROJECT_ROOT / "var" / "surveillance.db")


_OPENAPI_SPEC = {
    "openapi": "3.0.2",
    "info": {"title": "省级公共卫生风险监测多 Agent 系统", "version": "0.1.0"},
    "paths": {
        "/api/health": {"get": {"summary": "健康检查", "responses": {"200": {"description": "ok"}}}},
        "/api/config": {"get": {"summary": "查询配置", "responses": {"200": {"description": "ok"}}}},
        "/api/agents": {"get": {"summary": "查询Agent角色", "responses": {"200": {"description": "ok"}}}},
        "/api/institutions": {"get": {"summary": "查询机构名称与编号", "responses": {"200": {"description": "ok"}}}},
        "/api/signal-catalog": {"get": {"summary": "查询信号目录21至28", "responses": {"200": {"description": "ok"}}}},
        "/api/runs": {
            "get": {"summary": "查询运行记录", "responses": {"200": {"description": "ok"}}},
            "post": {"summary": "启动一次处理", "responses": {"200": {"description": "ok"}}},
        },
        "/api/risks": {"get": {"summary": "查询风险结果", "responses": {"200": {"description": "ok"}}}},
        "/api/signals/{signal_id}/review": {"post": {"summary": "更新信号核查状态", "responses": {"200": {"description": "ok"}}}},
    },
}


def _json_response(payload: Any, status: int = 200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body


class Handler:
    def __init__(self):
        pass

    def dispatch(self, method: str, path: str, body: bytes):
        if method == "GET" and path == "/api/health":
            return _json_response({"status": "ok"})
        if method == "GET" and path == "/api/config":
            return _json_response(load_config())
        if method == "GET" and path == "/api/agents":
            from ..agent import list_roles
            return _json_response({"agents": list_roles()})
        if method == "GET" and path == "/api/institutions":
            return _json_response({"institutions": load_institution_catalog()})
        if method == "GET" and path == "/api/signal-catalog":
            return _json_response(catalog_document())
        if method == "GET" and path == "/api/runs":
            storage = Storage(_db_path())
            try:
                return _json_response({"runs": storage.query_runs()})
            finally:
                storage.close()
        if method == "GET" and path == "/api/risks":
            storage = Storage(_db_path())
            try:
                return _json_response({"risks": storage.query_signals()})
            finally:
                storage.close()
        if method == "POST" and path == "/api/runs":
            payload = json.loads(body.decode("utf-8")) if body else {}
            summary = _run_once(
                inject=payload.get("inject_outbreak", False),
                shape=payload.get("injection_shape", "gradual"),
                magnitude=float(payload.get("injection_magnitude", 10)),
                use_langgraph=payload.get("use_langgraph", False),
                autonomy_stage=payload.get("autonomy_stage", None),
            ).get("summary", {})
            return _json_response(summary)
        review_match = re.fullmatch(r"/api/signals/([^/]+)/review", path)
        if method == "POST" and review_match:
            payload = json.loads(body.decode("utf-8")) if body else {}
            storage = Storage(_db_path())
            try:
                try:
                    result = storage.update_signal_review(
                        signal_id=review_match.group(1),
                        action=str(payload.get("action", "")),
                        result=str(payload.get("result", "")),
                        reason=str(payload.get("reason", "")),
                        reviewer=str(payload.get("reviewer", "")),
                        task_name=str(payload.get("task_name", "")),
                        task_owner=str(payload.get("task_owner", "")),
                        task_due_at=str(payload.get("task_due_at", "")),
                        observation_period=str(payload.get("observation_period", "")),
                        task_status=str(payload.get("task_status", "")),
                    )
                    return _json_response(result)
                except KeyError:
                    return _json_response({"error": "signal_not_found"}, 404)
                except ValueError as exc:
                    return _json_response({"error": str(exc)}, 422)
            finally:
                storage.close()
        if method == "GET" and path == "/docs":
            return self._serve_static("/static/swagger-ui/swagger.html")
        if method == "GET" and path == "/openapi.json":
            return _json_response(_OPENAPI_SPEC)
        if path == "/" or path.startswith("/static"):
            return self._serve_static(path)
        return _json_response({"error": "not_found"}, 404)

    def _serve_static(self, path: str):
        import os
        if path in ("/", ""):
            path = "/static/index.html"
        rel = path.lstrip("/")
        static_root = PROJECT_ROOT / "src" / "surveillance_agent"
        full = static_root / rel
        root_real = os.path.normpath(os.path.realpath(str(static_root)))
        full_real = os.path.normpath(os.path.realpath(str(full)))
        if not (full_real == root_real or full_real.startswith(root_real + os.sep)):
            return _json_response({"error": "not_found"}, 404)
        if not os.path.isfile(full_real):
            return _json_response({"error": "not_found"}, 404)
        with open(full_real, "rb") as fh:
            data = fh.read()
        ctype = "text/html; charset=utf-8" if full_real.endswith(".html") else "application/octet-stream"
        return 200, data, ctype


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    handler = Handler()

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._respond("GET", self.path, b"")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self._respond("POST", self.path, body)

        def _respond(self, method, path, body):
            try:
                result = handler.dispatch(method, path, body)
                if len(result) == 3:
                    status, payload, ctype = result
                else:
                    status, payload = result
                    ctype = "application/json; charset=utf-8"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                err = _json_response({"error": str(exc)}, 500)
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(err[1])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"标准库回退服务器已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
