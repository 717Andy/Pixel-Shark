"""The set of live tables inside one server process."""

from __future__ import annotations

import uuid

from pixelshark_sim import Table
from pixelshark_table.service import TableService
from pixelshark_table.settings import Settings


class TableManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tables: dict[str, TableService] = {}
        self.default_id: str | None = None

    def open_default(self) -> TableService | None:
        if not self.settings.create_default:
            return None
        service = self.open(
            table_id="home",
            seats=self.settings.seats,
            small_blind=self.settings.small_blind,
            big_blind=self.settings.big_blind,
            stacks=self.settings.starting_stack,
            seed=self.settings.seed,
            hero_seat=self.settings.hero_seat,
            reveal=self.settings.reveal,
            autoplay=self.settings.autoplay,
            shot_clock_ms=self.settings.shot_clock_ms,
            bot_policy=self.settings.bot_policy,
        )
        self.default_id = service.engine.table_id
        return service

    def open(self, **kwargs: object) -> TableService:
        table_id = str(kwargs.pop("table_id", "") or f"t-{uuid.uuid4().hex[:8]}")
        engine = Table(table_id=table_id, **kwargs)  # type: ignore[arg-type]
        service = TableService(engine)
        self.tables[table_id] = service
        return service

    def get(self, table_id: str) -> TableService | None:
        return self.tables.get(table_id)

    def start(self) -> None:
        for service in self.tables.values():
            service.start()

    async def stop(self) -> None:
        for service in self.tables.values():
            await service.stop()
