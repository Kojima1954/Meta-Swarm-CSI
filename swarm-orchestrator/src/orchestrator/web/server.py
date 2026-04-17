"""FastAPI application — REST + WebSocket + static asset server."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator.web.state import AppState

if TYPE_CHECKING:
    from orchestrator.config import WebConfig

log = structlog.get_logger()

_STATIC_DIR = Path(__file__).parent / "static"


def _require_token(request: Request) -> None:
    """Bearer-token guard for mutating endpoints."""
    state: AppState = request.app.state.orchestrator
    expected = state.settings.web.api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control endpoints disabled — set web.api_token to enable.",
        )
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class TriggerResponse(BaseModel):
    ok: bool
    message: str


def _build_router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    @api.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @api.get("/status")
    async def get_status(request: Request) -> dict:
        state: AppState = request.app.state.orchestrator
        ctrl = state.controller
        txn = state.transcript
        events = state.events
        return {
            "node": state.settings.node.model_dump(),
            "phase": ctrl.phase.value if ctrl else "UNKNOWN",
            "round_number": ctrl.round_number if ctrl else 0,
            "mode": state.settings.rounds.mode,
            "interval_seconds": state.settings.rounds.interval_seconds,
            "message_threshold": state.settings.rounds.message_threshold,
            "transcript": {
                "message_count": txn.message_count if txn else 0,
                "participant_count": txn.participant_count if txn else 0,
                "token_estimate": txn.token_estimate() if txn else 0,
            },
            "uptime_seconds": state.uptime_seconds(),
            "websocket_subscribers": events.subscriber_count if events else 0,
        }

    @api.get("/topology")
    async def get_topology(request: Request) -> dict:
        state: AppState = request.app.state.orchestrator
        topo = state.topology
        if topo is None:
            return {"nodes": [], "self_id": None}
        return {
            "self_id": state.settings.node.id,
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "domain": n.domain,
                    "role": n.role,
                    "is_self": n.is_self,
                    "has_public_key": bool(n.public_key),
                    "actor_uri": n.actor_uri,
                }
                for n in topo.nodes
            ],
        }

    @api.get("/transcript")
    async def get_transcript(request: Request, limit: int = 100) -> dict:
        state: AppState = request.app.state.orchestrator
        txn = state.transcript
        if txn is None:
            return {"entries": [], "message_count": 0, "participant_count": 0}

        entries = txn._entries[-max(1, min(limit, 500)):]  # noqa: SLF001
        return {
            "message_count": txn.message_count,
            "participant_count": txn.participant_count,
            "token_estimate": txn.token_estimate(),
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "sender": e.sender,
                    "body": e.body,
                    "is_swarm_signal": e.is_swarm_signal,
                }
                for e in entries
            ],
        }

    @api.get("/summaries")
    async def list_summaries(request: Request, limit: int = 20) -> dict:
        """Recent summaries — pulled from the event bus history.

        Qdrant is vector-search oriented and doesn't give us stable
        "most recent" ordering without a payload index. The event bus
        keeps the most recent summaries in memory, which is what the UI
        needs for a live feed.
        """
        state: AppState = request.app.state.orchestrator
        events = state.events
        if events is None:
            return {"summaries": []}

        limit = max(1, min(limit, 100))
        items = [
            e.data for e in events.history
            if e.type == "summary.created" and "summary" in e.data
        ]
        items.reverse()
        return {"summaries": [it["summary"] for it in items[:limit]]}

    @api.get("/events/recent")
    async def recent_events(request: Request, limit: int = 100) -> dict:
        state: AppState = request.app.state.orchestrator
        events = state.events
        if events is None:
            return {"events": []}
        limit = max(1, min(limit, 500))
        history = events.history[-limit:]
        return {"events": [e.to_dict() for e in history]}

    @api.get("/config")
    async def get_config(request: Request) -> dict:
        state: AppState = request.app.state.orchestrator
        return state.safe_settings()

    @api.post(
        "/rounds/trigger",
        response_model=TriggerResponse,
        dependencies=[Depends(_require_token)],
    )
    async def trigger_round(request: Request) -> TriggerResponse:
        state: AppState = request.app.state.orchestrator
        if state.controller is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Round controller not available.",
            )
        state.controller.trigger_manual()
        if state.events:
            await state.events.publish("round.manual_trigger", source="api")
        return TriggerResponse(ok=True, message="Round trigger signalled.")

    return api


def build_app(app_state: AppState) -> FastAPI:
    """Construct the FastAPI app bound to an AppState."""
    app = FastAPI(
        title="Swarm Orchestrator",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.orchestrator = app_state

    cors = app_state.settings.web.cors_origins
    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(_build_router())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        events = app_state.events
        if events is None:
            await ws.close(code=1011, reason="event bus unavailable")
            return

        # Replay recent history so the client has immediate context
        for evt in events.history[-50:]:
            await ws.send_json(evt.to_dict())

        q = await events.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    await ws.send_json(event.to_dict())
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    await ws.send_json({"type": "ping", "data": {}, "timestamp": 0})
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warn("ws.error", error=str(exc))
        finally:
            await events.unsubscribe(q)

    if _STATIC_DIR.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_STATIC_DIR / "assets")),
            name="assets",
        )

        @app.get("/", include_in_schema=False)
        async def root() -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html")

        # SPA fallback for unknown paths that aren't /api or /ws.
        # response_model=None — FastAPI can't derive a response model from the
        # union FileResponse | JSONResponse.
        @app.get("/{path:path}", include_in_schema=False, response_model=None)
        async def spa_fallback(path: str):
            if path.startswith(("api/", "ws", "assets/")):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(_STATIC_DIR / "index.html")

    return app


async def serve(app_state: AppState, shutdown: asyncio.Event) -> None:
    """Run uvicorn as an asyncio task, stopping cleanly on shutdown."""
    cfg: "WebConfig" = app_state.settings.web
    if not cfg.enabled:
        log.info("web.disabled")
        await shutdown.wait()
        return

    app = build_app(app_state)
    config = uvicorn.Config(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level="warning",  # structlog handles logging for the orchestrator
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)

    async def wait_for_shutdown() -> None:
        await shutdown.wait()
        server.should_exit = True

    log.info("web.starting", host=cfg.host, port=cfg.port)
    stopper = asyncio.create_task(wait_for_shutdown(), name="web-shutdown-watcher")
    try:
        await server.serve()
    finally:
        stopper.cancel()
        try:
            await stopper
        except asyncio.CancelledError:
            pass
        log.info("web.stopped")
