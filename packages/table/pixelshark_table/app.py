"""HTTP and WebSocket API for the self-hosted table."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from pixelshark_schema import Decision, GameState, json_schema
from pixelshark_sim import HumanToAct, IllegalAction, TableConfigError
from pixelshark_table.manager import TableManager
from pixelshark_table.service import TableService
from pixelshark_table.settings import Settings

_STATIC = Path(__file__).resolve().parent / "static"


class CreateTable(BaseModel):
    seats: int = Field(default=6, ge=2, le=9)
    small_blind: int = Field(default=50, gt=0)
    big_blind: int = Field(default=100, gt=0)
    ante: int = Field(default=0, ge=0)
    starting_stack: int = Field(default=10_000, gt=0)
    stacks: list[int] | None = None
    button_seat: int = 0
    hero_seat: int | None = None
    bot_seats: list[int] | None = None
    bot_policy: Literal["scripted", "random"] = "scripted"
    seed: int = 0
    reveal: Literal["all", "hero", "showdown"] = "showdown"
    autoplay: bool = False
    shot_clock_ms: int = Field(default=20_000, ge=0)
    rebuy: bool = True

    @field_validator("big_blind")
    @classmethod
    def _blinds(cls, value: int, info) -> int:  # type: ignore[no-untyped-def]
        small = info.data.get("small_blind", 50)
        if value < small:
            raise ValueError("big blind must be greater than or equal to the small blind")
        return value


class ActionIn(BaseModel):
    seat: int
    kind: Literal["fold", "check", "call", "bet", "raise"]
    to_amount: int | None = None


class AutoplayIn(BaseModel):
    enabled: bool


class RevealIn(BaseModel):
    mode: Literal["all", "hero", "showdown"]


class HeroIn(BaseModel):
    seat: int | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings; the process uses the environment."""

    resolved = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = TableManager(resolved)
        manager.open_default()
        app.state.manager = manager
        app.state.settings = resolved
        manager.start()
        yield
        await manager.stop()

    app = FastAPI(title="Pixel Shark Table", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/schema")
    def schema() -> dict[str, object]:
        return json_schema()

    @app.get("/api/session")
    async def session(request: Request) -> dict[str, object]:
        manager: TableManager = request.app.state.manager
        if manager.default_id is None:
            raise HTTPException(status_code=404, detail="this server has no default table")
        service = _service(manager, manager.default_id)
        async with service.lock:
            return {"table_id": service.engine.table_id, "state": service.public()}

    @app.get("/api/tables")
    def list_tables(request: Request) -> dict[str, object]:
        manager: TableManager = request.app.state.manager
        return {"tables": list(manager.tables), "default": manager.default_id}

    @app.post("/api/tables", status_code=201)
    async def create_table(body: CreateTable, request: Request) -> dict[str, object]:
        manager: TableManager = request.app.state.manager
        try:
            service = manager.open(
                seats=body.seats,
                stacks=body.stacks if body.stacks is not None else body.starting_stack,
                small_blind=body.small_blind,
                big_blind=body.big_blind,
                ante=body.ante,
                button_seat=body.button_seat,
                hero_seat=body.hero_seat,
                bot_seats=body.bot_seats,
                bot_policy=body.bot_policy,
                seed=body.seed,
                reveal=body.reveal,
                autoplay=body.autoplay,
                shot_clock_ms=body.shot_clock_ms,
                rebuy=body.rebuy,
            )
        except (TableConfigError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        service.start()
        async with service.lock:
            return {"table_id": service.engine.table_id, "state": service.public()}

    @app.get("/api/tables/{table_id}")
    async def table_info(table_id: str, request: Request) -> dict[str, object]:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            return {"table_id": table_id, "state": service.public()}

    @app.get("/api/tables/{table_id}/state", response_model=GameState)
    async def table_state(table_id: str, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            return service.state()

    @app.post("/api/tables/{table_id}/actions", response_model=GameState)
    async def act(table_id: str, body: ActionIn, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            try:
                state = service.apply_decision(
                    body.seat,
                    Decision(kind=body.kind, to_amount=body.to_amount),
                )
            except (IllegalAction, HumanToAct) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            service.publish()
        return state

    @app.post("/api/tables/{table_id}/step", response_model=GameState)
    async def step(table_id: str, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            try:
                state = service.step()
            except (IllegalAction, HumanToAct) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            service.publish()
        return state

    @app.post("/api/tables/{table_id}/next", response_model=GameState)
    async def next_hand(table_id: str, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            try:
                state = service.next_hand()
            except IllegalAction as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            service.publish()
        return state

    @app.post("/api/tables/{table_id}/autoplay", response_model=GameState)
    async def autoplay(table_id: str, body: AutoplayIn, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            state = service.set_autoplay(body.enabled)
            service.publish()
        return state

    @app.post("/api/tables/{table_id}/reveal", response_model=GameState)
    async def reveal(table_id: str, body: RevealIn, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            state = service.set_reveal(body.mode)
            service.publish()
        return state

    @app.post("/api/tables/{table_id}/hero", response_model=GameState)
    async def hero(table_id: str, body: HeroIn, request: Request) -> GameState:
        service = _service(request.app.state.manager, table_id)
        async with service.lock:
            try:
                state = service.set_hero(body.seat)
            except TableConfigError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            service.publish()
        return state

    @app.websocket("/api/tables/{table_id}/ws")
    async def socket(websocket: WebSocket, table_id: str) -> None:
        manager: TableManager = websocket.app.state.manager
        service = manager.get(table_id)
        if service is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        async with service.lock:
            queue = service.subscribe()
        try:
            while True:
                payload = await queue.get()
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        finally:
            async with service.lock:
                service.unsubscribe(queue)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    return app


def _service(manager: TableManager, table_id: str) -> TableService:
    service = manager.get(table_id)
    if service is None:
        raise HTTPException(status_code=404, detail=f"no table {table_id}")
    return service


app = create_app()
