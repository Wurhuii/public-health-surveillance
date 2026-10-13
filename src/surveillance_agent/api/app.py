from __future__ import annotations

import time
from typing import Any, Dict

from ..config import PROJECT_ROOT, load_config
from ..storage import Storage
from ..signal_catalog import catalog_document
from . import _run_once
from .institution_catalog import load_institution_catalog
from .school_governance import school_governance_summary


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

    @app.get("/api/institutions")
    def institutions():
        return {"institutions": load_institution_catalog()}

    @app.get("/api/signal-catalog")
    def signal_catalog_endpoint():
        return catalog_document()

    @app.get("/api/school-governance")
    def school_governance_endpoint():
        return school_governance_summary()

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
    def risks(latest_only: bool = False, run_id: str = ""):
        storage = Storage(_db_path())
        try:
            selected_run_id = run_id.strip()
            if latest_only and not selected_run_id:
                selected_run_id = storage.latest_run_id()
            rows = storage.query_signals(selected_run_id) if selected_run_id else (
                [] if latest_only else storage.query_signals()
            )
            return {"risks": rows, "run_id": selected_run_id}
        finally:
            storage.close()

    @app.post("/api/signals/{signal_id}/review")
    def review_signal(signal_id: str, body: Dict[str, Any]):
        storage = Storage(_db_path())
        try:
            try:
                return storage.update_signal_review(
                    signal_id=signal_id,
                    action=str(body.get("action", "")),
                    result=str(body.get("result", "")),
                    reason=str(body.get("reason", "")),
                    reviewer=str(body.get("reviewer", "")),
                    task_name=str(body.get("task_name", "")),
                    task_owner=str(body.get("task_owner", "")),
                    task_due_at=str(body.get("task_due_at", "")),
                    observation_period=str(body.get("observation_period", "")),
                    task_status=str(body.get("task_status", "")),
                )
            except KeyError:
                return JSONResponse({"error": "signal_not_found"}, status_code=404)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
        finally:
            storage.close()

    return app


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn
    print(f"FastAPI 服务器已启动: http://{host}:{port}", flush=True)
    print(f"风险展示页面: http://{host}:{port}/", flush=True)
    print(f"API 文档:     http://{host}:{port}/docs", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
