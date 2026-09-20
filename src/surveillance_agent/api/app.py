from __future__ import annotations

import time
from typing import Any, Dict

from ..config import PROJECT_ROOT, load_config
from ..storage import Storage
from . import _run_once


def _db_path() -> str:
    return str(PROJECT_ROOT / "var" / "surveillance.db")


def create_app():
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(
        title="省级公共卫生风险监测多 Agent 系统",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    static_dir = PROJECT_ROOT / "src" / "surveillance_agent" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/docs", include_in_schema=False)
    def swagger_docs():
        return FileResponse(str(static_dir / "swagger-ui" / "swagger.html"))

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_schema():
        schema = app.openapi()
        schema["openapi"] = "3.0.2"
        return schema

    @app.get("/api/health")
    def health():
        return {"status": "ok", "time": time.strftime("%Y-%m-%dT%H:%M:%S")}

    @app.get("/api/config")
    def config():
        return load_config()

    @app.get("/api/agents")
    def agents():
        from ..agent import list_roles
        return {"agents": list_roles()}

    @app.post("/api/runs")
    def start_run(body: Dict[str, Any]):
        use_langgraph = body.get("use_langgraph", False)
        autonomy_stage = body.get("autonomy_stage", None)
        inject = body.get("inject_outbreak", False)
        shape = body.get("injection_shape", "gradual")
        magnitude = float(body.get("injection_magnitude", 10))
        result = _run_once(inject=inject, shape=shape, magnitude=magnitude,
                           use_langgraph=use_langgraph, autonomy_stage=autonomy_stage)
        return result.get("summary", {})

    @app.get("/api/runs")
    def runs():
        storage = Storage(_db_path())
        try:
            return {"runs": storage.query_runs()}
        finally:
            storage.close()

    @app.get("/api/risks")
    def risks():
        storage = Storage(_db_path())
        try:
            return {"risks": storage.query_signals()}
        finally:
            storage.close()

    return app


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn
    print(f"FastAPI 服务器已启动: http://{host}:{port}", flush=True)
    print(f"风险展示页面: http://{host}:{port}/", flush=True)
    print(f"API 文档:     http://{host}:{port}/docs", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
