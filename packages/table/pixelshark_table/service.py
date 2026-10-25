"""Autoplay and fan-out around a synchronous :class:`pixelshark_sim.Table`.

The engine does not sleep. This service decides when a bot acts, when a human
shot clock expires, and when the next hand starts. HTTP handlers and the
background loop share one lock per table.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from pixelshark_schema import Decision, GameState
from pixelshark_sim import HumanToAct, IllegalAction, Table

logger = logging.getLogger(__name__)


class TableService:
    """One table, its subscribers, and the autoplay clock."""

    def __init__(
        self,
        engine: Table,
        *,
        between_hands_s: float = 2.0,
        bot_delay_s: tuple[float, float] = (0.45, 1.05),
    ) -> None:
        self.engine = engine
        self.between_hands_s = between_hands_s
        self.bot_delay_s = bot_delay_s
        self.autoplay_enabled = engine.autoplay
        self.wait_until: float | None = None
        self.act_at = 0.0
        self.human_deadline_mono = 0.0
        self.lock = asyncio.Lock()
        self.subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._arm_actor()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def public(self) -> dict[str, Any]:
        return self.engine.snapshot().model_dump(mode="json")

    def state(self) -> GameState:
        return self.engine.snapshot()

    def apply_decision(self, seat: int, decision: Decision) -> GameState:
        state = self.engine.apply(seat, decision)
        self._after_action()
        return state

    def step(self) -> GameState:
        if not self.engine.betting:
            state = self.engine.start_hand()
            self.wait_until = None
            self._arm_actor()
            return state
        state = self.engine.step_bot()
        self._after_action()
        return state

    def next_hand(self) -> GameState:
        if self.engine.betting:
            raise IllegalAction("the current hand is still in progress")
        state = self.engine.start_hand()
        self.wait_until = None
        self._arm_actor()
        return state

    def set_autoplay(self, enabled: bool) -> GameState:
        self.autoplay_enabled = enabled
        self.engine.autoplay = enabled
        if enabled:
            self._arm_actor()
        return self.engine.snapshot()

    def set_reveal(self, reveal: str) -> GameState:
        self.engine.set_reveal(reveal)  # type: ignore[arg-type]
        return self.engine.snapshot()

    def set_hero(self, seat: int | None) -> GameState:
        self.engine.set_hero(seat)
        self._arm_actor()
        return self.engine.snapshot()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a queue that already holds the current snapshot. Caller holds ``lock``."""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self.subscribers.append(queue)
        queue.put_nowait(self.public())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def publish(self) -> None:
        """Push the current snapshot. Caller holds ``lock``."""

        payload = self.public()
        for queue in self.subscribers:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    def tick(self) -> bool:
        """Advance autoplay by at most one action. Caller holds ``lock``."""

        if not self.autoplay_enabled:
            return False
        now = self.engine.clock.monotonic()
        if self.wait_until is not None:
            if now < self.wait_until:
                return False
            self.wait_until = None
            if not self.engine.betting:
                self.engine.start_hand()
                self._arm_actor()
                return True
        if not self.engine.betting:
            return False
        actor = self.engine.actor_seat()
        if actor is None:
            return False
        if actor in self.engine.bot_seats:
            if now < self.act_at:
                return False
            self.engine.step_bot()
            self._after_action()
            return True
        if self.engine.shot_clock_ms <= 0:
            return False
        if now >= self.human_deadline_mono:
            self.engine.apply(actor, self.engine.timeout_decision())
            self._after_action()
            return True
        return False

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                async with self.lock:
                    if self.tick():
                        self.publish()
            except (IllegalAction, HumanToAct):
                logger.exception("autoplay skipped an action on %s", self.engine.table_id)
            except Exception:
                logger.exception("autoplay failed on %s", self.engine.table_id)
            await asyncio.sleep(0.05)

    def _after_action(self) -> None:
        if not self.engine.betting:
            self.wait_until = self.engine.clock.monotonic() + self.between_hands_s
        else:
            self._arm_actor()

    def _arm_actor(self) -> None:
        actor = self.engine.actor_seat()
        now = self.engine.clock.monotonic()
        if actor is None:
            return
        if actor in self.engine.bot_seats:
            low, high = self.bot_delay_s
            if high <= low:
                self.act_at = now + low
            else:
                # A dedicated stream so think-time does not change the cards or the policy.
                span = high - low
                fraction = ((self.engine.hand_number * 17 + actor * 3) % 100) / 100
                self.act_at = now + low + span * fraction
            return
        self.human_deadline_mono = now + self.engine.shot_clock_ms / 1000
